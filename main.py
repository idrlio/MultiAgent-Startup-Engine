"""
main.py
=======
AgentForge — entry point.

Usage:
    python main.py
    python main.py --objective "Build a B2B SaaS CRM for freelancers"
    python main.py --objective "..." --no-critic --no-feedback --iterations 5
    python main.py --objective "..." --output-dir ./my-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import structlog
from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging(log_level: str, log_format: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        stream=sys.stdout,
    )
    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AgentForge — autonomous multi-agent AI startup simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python main.py --objective "Build an AI-native CRM for freelancers"\n'
            '  python main.py --no-feedback --iterations 5\n'
        ),
    )
    parser.add_argument("--objective", type=str, default="", help="Startup objective (prompted if omitted)")
    parser.add_argument("--no-critic", action="store_true", help="Skip critic agent")
    parser.add_argument("--no-feedback", action="store_true", help="Disable feedback loop")
    parser.add_argument("--no-vector-memory", action="store_true", help="Disable FAISS RAG layer")
    parser.add_argument("--iterations", type=int, default=None, help="Override max_iterations")
    parser.add_argument("--output-dir", type=str, default=None, help="Override artifacts directory")
    parser.add_argument("--load-memory", action="store_true", help="Load persisted vector memory from disk")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    # Import settings after arg parse so we can override before use
    from config import settings
    _configure_logging(settings.log_level, settings.log_format)

    if args.iterations:
        settings.max_iterations = args.iterations
    if args.no_critic:
        settings.enable_critic = False
    if args.no_feedback:
        settings.enable_feedback_loop = False
    if args.no_vector_memory:
        settings.enable_vector_memory = False

    # ---- Banner --------------------------------------------------------
    console.print(
        Panel.fit(
            "[bold cyan]🚀 AgentForge[/bold cyan]\n"
            "[dim]Autonomous multi-agent AI startup simulator[/dim]\n"
            "[dim]RAG · Feedback Loops · Structured Workflows[/dim]",
            border_style="cyan",
        )
    )

    # ---- Objective -----------------------------------------------------
    objective = args.objective.strip()
    if not objective:
        objective = console.input("\n[bold yellow]Enter your startup objective:[/bold yellow] ").strip()

    if not objective:
        console.print("[red]Error:[/red] No objective provided.")
        sys.exit(1)

    console.print(f"\n[bold]Objective:[/bold] {objective}\n")

    # ---- Infrastructure ------------------------------------------------
    from core.memory import MemoryManager
    from core.messaging import MessageBus
    from core.orchestrator import Orchestrator, Workflow
    from agents import (
        ResearchAgent, CEOAgent, ProductAgent,
        EngineerAgent, MarketingAgent, CriticAgent,
    )
    from tools.file_manager import FileManager

    memory = MemoryManager()
    if args.load_memory:
        loaded = memory.load_vector()
        console.print(f"[dim]Vector memory loaded from disk: {loaded}[/dim]")

    bus = MessageBus()
    orchestrator = Orchestrator(memory=memory, bus=bus)
    file_manager = FileManager(artifacts_dir=args.output_dir)

    # ---- Register agents -----------------------------------------------
    agent_classes = [ResearchAgent, CEOAgent, ProductAgent, EngineerAgent, MarketingAgent]
    for AgentClass in agent_classes:
        orchestrator.register(AgentClass())

    if settings.enable_critic:
        orchestrator.register(CriticAgent())

    # ---- Build workflow ------------------------------------------------
    pipeline = [a.name for a in agent_classes]
    if settings.enable_critic:
        workflow = Workflow.with_critic("agentforge", pipeline)
    else:
        workflow = Workflow.linear("agentforge", pipeline)

    # ---- Feature summary -----------------------------------------------
    feature_table = Table.grid(padding=(0, 2))
    feature_table.add_column(style="dim")
    feature_table.add_column()
    feature_table.add_row("Vector memory (RAG)", "✅" if settings.enable_vector_memory else "⏭ disabled")
    feature_table.add_row("Critic agent", "✅" if settings.enable_critic else "⏭ disabled")
    feature_table.add_row("Feedback loop", "✅" if settings.enable_feedback_loop else "⏭ disabled")
    feature_table.add_row("Web search", "✅ Tavily" if settings.tavily_api_key else "🔧 mock")
    feature_table.add_row("Pipeline", " → ".join(workflow.agent_names()))
    console.print(Panel(feature_table, title="[bold]Run Configuration[/bold]", border_style="dim"))
    console.print()

    # ---- Execute -------------------------------------------------------
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running AgentForge pipeline...", total=None)
        record = orchestrator.run(objective=objective, workflow=workflow)
        progress.update(task, description="Pipeline complete.")

    # ---- Display results -----------------------------------------------
    console.print()
    for agent_name, result in record.results.items():
        if agent_name == "critic":
            score = result.metadata.get("confidence_score", "?")
            revise = result.metadata.get("agents_to_revise", [])
            title = (
                f"[bold]CRITIC[/bold]  "
                f"Score: [{'green' if float(score) >= 7 else 'yellow'}]{score}/10[/]"
                + (f"  Flagged: {revise}" if revise else "")
            )
        else:
            title = f"[bold]{agent_name.upper()}[/bold]"
        border = "green" if result.success else "red"
        console.print(Panel(Markdown(result.content), title=title, border_style=border))
        file_manager.save_artifact(agent_name, f"{agent_name}.md", result.content)

    # ---- Run summary ---------------------------------------------------
    from core.orchestrator import RunStatus
    status_colour = {
        RunStatus.COMPLETED: "green",
        RunStatus.PARTIAL: "yellow",
        RunStatus.FAILED: "red",
    }.get(record.status, "white")

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("Status", f"[bold {status_colour}]{record.status.value.upper()}[/]")
    summary.add_row("Duration", f"{record.duration_s:.1f}s")
    summary.add_row("Steps", f"{len(record.succeeded_steps)}/{len(record.steps)} succeeded")
    summary.add_row("Feedback rounds", str(record.feedback_rounds))
    if memory.vector:
        summary.add_row("Vector chunks indexed", str(memory.vector.size))
    summary.add_row("Run ID", record.run_id[:16])

    console.print(Panel(summary, title="[bold]Run Summary[/bold]", border_style=status_colour))

    # ---- Export artefacts ----------------------------------------------
    raw = {name: r.content for name, r in record.results.items()}
    report_path = file_manager.export_report(raw, objective=objective)
    file_manager.save_json("run_record.json", {
        "run_id": record.run_id,
        "objective": objective,
        "status": record.status.value,
        "duration_s": record.duration_s,
        "feedback_rounds": record.feedback_rounds,
        "succeeded_steps": len(record.succeeded_steps),
        "failed_steps": len(record.failed_steps),
        "results": raw,
    })

    console.print(f"\n📄 Report: [cyan]{report_path}[/cyan]")
    console.print(f"📁 Artifacts: [cyan]{file_manager.run_dir}[/cyan]\n")


if __name__ == "__main__":
    main()
