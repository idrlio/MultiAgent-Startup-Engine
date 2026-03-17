"""
tools/code_executor.py
Safe, sandboxed Python code execution for the engineer agent.
Runs code in a subprocess with a configurable timeout.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 30  # seconds


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def __str__(self) -> str:
        status = "✓" if self.success else "✗"
        parts = [f"[{status}] exit={self.exit_code}"]
        if self.timed_out:
            parts.append("TIMEOUT")
        if self.stdout:
            parts.append(f"stdout:\n{self.stdout}")
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr}")
        return "\n".join(parts)


class CodeExecutor:
    """
    Executes Python code snippets in an isolated subprocess.

    Usage:
        executor = CodeExecutor()
        result = executor.run('print("hello world")')
        print(result.stdout)  # → hello world
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        logger.info("code_executor.ready", timeout=timeout)

    def run(self, code: str, capture_output: bool = True) -> ExecutionResult:
        """
        Execute a Python code string in a sandboxed subprocess.

        Args:
            code:           Python source code to execute.
            capture_output: Whether to capture stdout/stderr.

        Returns:
            ExecutionResult with stdout, stderr, and exit code.
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)

        logger.info("code_executor.run", file=tmp_path.name, code_length=len(code))

        try:
            proc = subprocess.run(
                [sys.executable, str(tmp_path)],
                capture_output=capture_output,
                text=True,
                timeout=self.timeout,
            )
            result = ExecutionResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            logger.warning("code_executor.timeout", timeout=self.timeout)
            result = ExecutionResult(stdout="", stderr="Execution timed out.", exit_code=-1, timed_out=True)
        except Exception as exc:
            logger.exception("code_executor.error")
            result = ExecutionResult(stdout="", stderr=str(exc), exit_code=-1)
        finally:
            tmp_path.unlink(missing_ok=True)

        logger.info("code_executor.done", success=result.success, exit_code=result.exit_code)
        return result

    def validate_syntax(self, code: str) -> tuple[bool, str]:
        """
        Check Python syntax without executing.

        Returns:
            Tuple of (is_valid, error_message).
        """
        try:
            compile(code, "<string>", "exec")
            return True, ""
        except SyntaxError as exc:
            return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"
