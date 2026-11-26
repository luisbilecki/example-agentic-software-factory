import subprocess
from pathlib import Path

from factory.models import ValidationResult


class DeterministicValidator:
    """Gate determinístico de backpressure (linter + testes) executado no worktree."""

    def __init__(self, commands: list[list[str]] | None = None) -> None:
        self.commands = commands or [
            ["uv", "run", "ruff", "check", "."],
            ["uv", "run", "pytest", "-q"],
        ]

    def run(self, worktree_path: Path) -> ValidationResult:
        outputs: list[str] = []
        for cmd in self.commands:
            proc = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            cmd_str = " ".join(cmd)
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            outputs.append(f"$ {cmd_str}\n{combined}")
            if proc.returncode != 0:
                return ValidationResult(passed=False, output="\n\n".join(outputs))
        return ValidationResult(passed=True, output="\n\n".join(outputs))
