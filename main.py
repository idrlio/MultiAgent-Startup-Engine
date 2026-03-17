"""
main.py
Entry point for the AI Startup Engine.

Usage:
    python main.py
    python main.py --objective "Build a SaaS tool for indie hackers"
    python main.py --objective "..." --no-critic --iterations 5
"""

from __future__ import annotations

import argparse
import sys

import structlog
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from agents import (
    CEOAgent,
    CriticAgent,
    EngineerAgent,
    MarketingAgent,
    ProductAgent,
    ResearchAgent,
)
from core import Orchestrator, SharedMemory, MessageBus, Workflow, RunStatus
from tools import FileManager

console = Console()
logger = structlog.get_logger(__name__)


def _configure_logging(log_level: str, log_format: str) -> None:
    import logging
    import structlog

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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Startup Engine — autonomous multi-agent startup simulator",
    )
    parser.add_argument("--objective", type=str, default="")
    parser.add_argument("--no-critic", action="store_true")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    return parser.parse_args()


def main() -> None:
    from config import settings

    args = _parse_args()
    _configure_logging(settings.log_level, settings.log_format)

    if args.iterations:
        settings.max_iterations = args.iterations
    if args.no_critic:
        settings.enable_critic = False

    console.print(
        Panel.fit(
            "[bold cyan]🚀 AI Startup Engine[/bold cyan]\n"
            "[dim]Multi-agent autonomous startup simulator[/dim]",
            border_style="cyan",
        )
    )

    objective = args.objective.strip()
    if not objective:
        objective = console.input("\n[bold yellow]Enter your startup objective:[/bold yellow] ").strip()

    if not objective:
        console.print("[red]Error:[/red] No objective provided. Exiting.")
        sys.exit(1)

    console.print(f"\n[bold]Objective:[/bold] {objective}\n")

    # Wire up infrastructure
    memory = SharedMemory()
    bus = MessageBus()
    orchestrator = Orchestrator(memory=memory, bus=bus)
    file_manager = FileManager(artifacts_dir=args.output_dir)

    # Register agents
    agent_classes = [ResearchAgent, CEOAgent, ProductAgent, EngineerAgent, MarketingAgent]
    if settings.enable_critic:
        agent_classes.append(CriticAgent)

    for AgentClass in agent_classes:
        orchestrator.register(AgentClass())

    # Build workflow
    pipeline = [a().name for a in agent_classes]
    # Re-register is avoided: get names via class attribute
    pipeline = [AgentClass.name for AgentClass in agent_classes]
    workflow = Workflow.linear("startup-engine", pipeline)

    # Execute
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        task = progress.add_task("Running agents...", total=None)
        record = orchestrator.run(objective=objective, workflow=workflow)
        progress.update(task, description="Done.")

    # Display results
    console.print()
    for agent_name, result in record.results.items():
        border = "green" if result.success else "red"
        console.print(Panel(
            Markdown(result.content),
            title=f"[bold]{agent_name.upper()}[/bold]",
            border_style=border,
        ))
        file_manager.save_artifact(agent_name, f"{agent_name}.md", result.content)

    # Summary
    status_color = "green" if record.status == RunStatus.COMPLETED else "yellow"
    console.print(
        f"\n[bold {status_color}]Run {record.status.value.upper()}[/bold {status_color}] "
        f"— {len(record.succeeded_steps)}/{len(record.steps)} steps succeeded "
        f"in {record.duration_s:.1f}s"
    )

    # Export artefacts
    raw_results = {name: r.content for name, r in record.results.items()}
    report_path = file_manager.export_report(raw_results, objective=objective)
    file_manager.save_json("results.json", {
        "run_id": record.run_id,
        "objective": objective,
        "status": record.status.value,
        "duration_s": record.duration_s,
        "results": raw_results,
    })

    console.print(f"Report saved to [cyan]{report_path}[/cyan]\n")


if __name__ == "__main__":
    main()
