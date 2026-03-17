"""
tools/file_manager.py
File I/O and artifact management for agent outputs.
Handles reading, writing, and organising files produced during a run.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class FileManager:
    """
    Manages reading and writing of agent artifacts.

    All outputs are stored under a single run directory:
        <artifacts_dir>/<run_id>/

    Usage:
        fm = FileManager()
        fm.save_artifact("ceo", "strategy.md", ceo_output)
        fm.save_artifact("engineer", "architecture.md", eng_output)
        fm.export_report(results)
    """

    def __init__(self, artifacts_dir: str | None = None, run_id: str | None = None) -> None:
        from config import settings

        base = Path(artifacts_dir or settings.artifacts_dir)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._run_id = run_id or ts
        self._run_dir = base / self._run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        logger.info("file_manager.ready", run_dir=str(self._run_dir))

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def run_id(self) -> str:
        return self._run_id

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    def save_artifact(self, agent: str, filename: str, content: str) -> Path:
        """
        Save a text artifact for a given agent.

        Args:
            agent:    Agent name (used as sub-directory).
            filename: Output filename (e.g. "strategy.md").
            content:  Text content to write.

        Returns:
            Path to the saved file.
        """
        agent_dir = self._run_dir / agent
        agent_dir.mkdir(exist_ok=True)
        path = agent_dir / filename
        path.write_text(content, encoding="utf-8")
        logger.info("file_manager.saved", path=str(path))
        return path

    def save_json(self, filename: str, data: Any) -> Path:
        """Save a JSON-serialisable object to the run directory root."""
        path = self._run_dir / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("file_manager.saved_json", path=str(path))
        return path

    def export_report(self, results: dict[str, str], objective: str = "") -> Path:
        """
        Write a consolidated Markdown report of all agent outputs.

        Args:
            results:   Dict mapping agent name → output string.
            objective: The original startup objective.

        Returns:
            Path to the generated report file.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines: list[str] = [
            "# AI Startup Engine — Run Report\n",
            f"**Generated:** {ts}  ",
            f"**Run ID:** `{self._run_id}`  ",
        ]
        if objective:
            lines.append(f"**Objective:** {objective}\n")
        lines.append("\n---\n")

        agent_order = ["research", "ceo", "product", "engineer", "marketing", "critic"]
        ordered = {k: results[k] for k in agent_order if k in results}
        ordered.update({k: v for k, v in results.items() if k not in ordered})

        for agent, output in ordered.items():
            lines.append(f"\n## {agent.upper()}\n")
            lines.append(output)
            lines.append("\n---\n")

        report_path = self._run_dir / "report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("file_manager.report_exported", path=str(report_path))
        return report_path

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    def read(self, path: str | Path) -> str:
        """Read any text file by absolute or relative-to-run-dir path."""
        p = Path(path) if Path(path).is_absolute() else self._run_dir / path
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")
        return p.read_text(encoding="utf-8")

    def list_artifacts(self) -> list[Path]:
        """Return all files produced in this run."""
        return sorted(self._run_dir.rglob("*.*"))

    # ------------------------------------------------------------------ #
    # Cleanup                                                              #
    # ------------------------------------------------------------------ #

    def cleanup(self) -> None:
        """Remove the entire run directory."""
        shutil.rmtree(self._run_dir, ignore_errors=True)
        logger.info("file_manager.cleanup", run_dir=str(self._run_dir))
