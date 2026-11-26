import subprocess
from pathlib import Path


class WorktreeManager:
    """Gerencia workspaces isolados por issue usando `git worktree`."""

    def __init__(self, repo_root: Path, base_dir: Path | None = None) -> None:
        self.repo_root = repo_root
        self.base_dir = base_dir or (repo_root / ".worktrees")

    def _git(self, args: list[str], cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def create(self, issue_number: int, base_ref: str = "HEAD") -> tuple[Path, str]:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        branch = f"agent/issue-{issue_number}"
        worktree_path = self.base_dir / f"issue-{issue_number}"

        if worktree_path.exists():
            self.cleanup(worktree_path)

        # Remove branch anterior se existir (útil em re-execuções locais)
        existing = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0:
            self._git(["branch", "-D", branch])

        self._git(["worktree", "add", str(worktree_path), "-b", branch, base_ref])
        return worktree_path, branch

    def checkout_existing(self, issue_number: int, branch: str) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = self.base_dir / f"pr-issue-{issue_number}"
        if worktree_path.exists():
            self.cleanup(worktree_path)
        self._git(["worktree", "add", str(worktree_path), branch])
        return worktree_path

    def sync_with_main(self, worktree_path: Path) -> tuple[bool, str]:
        """Faz fetch e merge de origin/main no worktree. Retorna (clean, output)."""
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=worktree_path,
            check=False,
            capture_output=True,
            text=True,
        )
        proc = subprocess.run(
            ["git", "merge", "origin/main", "--no-edit"],
            cwd=worktree_path,
            check=False,
            capture_output=True,
            text=True,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return proc.returncode == 0, output

    def get_diff(self, worktree_path: Path) -> str:
        self._git(["add", "-A"], cwd=worktree_path)
        diff = self._git(["diff", "--cached"], cwd=worktree_path)
        return diff

    def has_changes(self, worktree_path: Path) -> bool:
        status = self._git(["status", "--porcelain"], cwd=worktree_path)
        return bool(status.strip())

    def commit_all(self, worktree_path: Path, message: str) -> bool:
        if not self.has_changes(worktree_path):
            return False
        self._git(["add", "-A"], cwd=worktree_path)
        self._git(["commit", "-m", message], cwd=worktree_path)
        return True

    def push_branch(self, worktree_path: Path, branch: str) -> None:
        self._git(["push", "-u", "origin", branch], cwd=worktree_path)

    def cleanup(self, worktree_path: Path) -> None:
        if worktree_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=self.repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
