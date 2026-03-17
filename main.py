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
from core import Orchestrator, SharedMemory, MessageBus
from tools import FileManager

console = Console()
logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Logging setup                                                                #
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Startup Engine — autonomous multi-agent startup simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--objective",
        type=str,
        default="",
        help="High-level startup objective (leave blank to be prompted interactively)",
    )
    parser.add_argument(
        "--no-critic",
        action="store_true",
        help="Skip the critic agent",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Override MAX_ITERATIONS from settings",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override artifacts output directory",
    )
    return parser.parse_args()


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main() -> None:
    from config import settings

    args = _parse_args()
    _configure_logging(settings.log_level, settings.log_format)

    # Apply CLI overrides
    if args.iterations:
        settings.max_iterations = args.iterations
    if args.no_critic:
        settings.enable_critic = False

    # Banner
    console.print(
        Panel.fit(
            "[bold cyan]🚀 AI Startup Engine[/bold cyan]\n"
            "[dim]Multi-agent autonomous startup simulator[/dim]",
            border_style="cyan",
        )
    )

    # Objective
    objective = args.objective.strip()
    if not objective:
        objective = console.input(
            "\n[bold yellow]Enter your startup objective:[/bold yellow] "
        ).strip()

    if not objective:
        console.print("[red]Error:[/red] No objective provided. Exiting.")
        sys.exit(1)

    console.print(f"\n[bold]Objective:[/bold] {objective}\n")

    # Wire up components
    memory = SharedMemory()
    bus = MessageBus()
    orchestrator = Orchestrator(memory=memory, bus=bus)
    file_manager = FileManager(artifacts_dir=args.output_dir)

    # Register agents
    for AgentClass in [ResearchAgent, CEOAgent, ProductAgent, EngineerAgent, MarketingAgent, CriticAgent]:
        orchestrator.register(AgentClass())

    # Run with progress indicator
    results: dict[str, str] = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running agents...", total=None)
        results = orchestrator.run(objective=objective)
        progress.update(task, description="Done.")

    # Display results
    console.print("\n")
    for agent_name, output in results.items():
        console.print(Panel(Markdown(output), title=f"[bold]{agent_name.upper()}[/bold]", border_style="green"))
        file_manager.save_artifact(agent_name, f"{agent_name}.md", output)

    # Export consolidated report
    report_path = file_manager.export_report(results, objective=objective)
    file_manager.save_json("results.json", {"objective": objective, "results": results})

    console.print(
        f"\n[bold green]✓ Complete![/bold green] "
        f"Report saved to [cyan]{report_path}[/cyan]\n"
    )


if __name__ == "__main__":
    main()
