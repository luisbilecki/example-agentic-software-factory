import json
from pathlib import Path

from factory.agents import AgentRunner, MockAgentRunner
from factory.issue_providers import LocalJsonProvider
from factory.models import Issue, ReviewResult, ValidationResult
from factory.orchestrator import (
    LABEL_DONE,
    LABEL_NEEDS_HUMAN,
    SoftwareFactoryOrchestrator,
    format_conventional_commit,
)


class FakeWorktreeManager:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.committed_messages: list[str] = []
        self.cleaned: bool = False

    def create(self, issue_number: int, base_ref: str = "HEAD") -> tuple[Path, str]:
        return self.tmp_path, f"agent/issue-{issue_number}"

    def get_diff(self, worktree_path: Path) -> str:
        return "diff --git a/app/main.py b/app/main.py\n+email filter"

    def commit_all(self, worktree_path: Path, message: str) -> bool:
        self.committed_messages.append(message)
        return True

    def push_branch(self, worktree_path: Path, branch: str) -> None:
        pass

    def cleanup(self, worktree_path: Path) -> None:
        self.cleaned = True


class FakeValidator:
    def __init__(self, results: list[bool]) -> None:
        self._results = list(results)

    def run(self, worktree_path: Path) -> ValidationResult:
        passed = self._results.pop(0) if self._results else True
        return ValidationResult(passed=passed, output="ok" if passed else "pytest failed")


class AlwaysRejectAgent(AgentRunner):
    def implement(
        self, worktree_path: Path, issue: Issue, feedback: str | None = None
    ) -> str:
        return "attempted"

    def review(self, worktree_path: Path, issue: Issue, diff: str) -> ReviewResult:
        return ReviewResult(
            approved=False,
            summary="Ainda faltam validações.",
            findings=["Falta teste de edge case."],
        )


class StubSuccessAgent(AgentRunner):
    def __init__(self, fail_first_review: bool = False) -> None:
        self.fail_first_review = fail_first_review
        self.review_calls = 0
        self.received_feedback: list[str | None] = []

    def implement(
        self, worktree_path: Path, issue: Issue, feedback: str | None = None
    ) -> str:
        self.received_feedback.append(feedback)
        return "implemented"

    def review(self, worktree_path: Path, issue: Issue, diff: str) -> ReviewResult:
        self.review_calls += 1
        if self.fail_first_review and self.review_calls == 1:
            return ReviewResult(
                approved=False,
                summary="Ajustar filtro.",
                findings=["Usar busca case-insensitive."],
            )
        return ReviewResult(approved=True, summary="LGTM", findings=[])


def _seed_issues_file(tmp_path: Path) -> Path:
    issues_file = tmp_path / "issues.json"
    issues_file.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "number": 7,
                        "title": "Adicionar filtro por email",
                        "body": "Filtrar clientes por email.",
                        "labels": ["agent:ready"],
                        "comments": [],
                    }
                ],
                "pull_requests": [],
            }
        ),
        encoding="utf-8",
    )
    return issues_file


def test_format_conventional_commit() -> None:
    issue = Issue(number=42, title="Corrigir erro de email duplicado", body="")
    msg = format_conventional_commit(issue)
    assert msg.startswith("fix(customers): corrigir erro de email duplicado")
    assert "Closes #42" in msg


def test_orchestrator_happy_path(tmp_path: Path) -> None:
    issues_file = _seed_issues_file(tmp_path)
    provider = LocalJsonProvider(issues_file)
    workspace = FakeWorktreeManager(tmp_path)
    agent = StubSuccessAgent(fail_first_review=False)

    orch = SoftwareFactoryOrchestrator(
        provider=provider,
        agent=agent,
        workspace=workspace,  # type: ignore[arg-type]
        validator=FakeValidator([True]),  # type: ignore[arg-type]
        max_turns=3,
    )

    results = orch.run_once()
    assert len(results) == 1
    assert results[0].status == "done"
    assert results[0].turns == 1
    assert workspace.cleaned is True
    assert workspace.committed_messages[0].startswith("feat(customers):")

    saved = json.loads(issues_file.read_text(encoding="utf-8"))
    assert LABEL_DONE in saved["issues"][0]["labels"]
    assert len(saved["pull_requests"]) == 1


def test_orchestrator_rework_loop_on_review_rejection(tmp_path: Path) -> None:
    issues_file = _seed_issues_file(tmp_path)
    provider = LocalJsonProvider(issues_file)
    workspace = FakeWorktreeManager(tmp_path)
    agent = StubSuccessAgent(fail_first_review=True)

    orch = SoftwareFactoryOrchestrator(
        provider=provider,
        agent=agent,
        workspace=workspace,  # type: ignore[arg-type]
        validator=FakeValidator([True, True]),  # type: ignore[arg-type]
        max_turns=3,
    )

    results = orch.run_once()
    assert results[0].status == "done"
    assert results[0].turns == 2
    assert agent.received_feedback[0] is None
    assert "case-insensitive" in (agent.received_feedback[1] or "")


def test_orchestrator_escalates_to_human_after_max_turns(tmp_path: Path) -> None:
    issues_file = _seed_issues_file(tmp_path)
    provider = LocalJsonProvider(issues_file)
    workspace = FakeWorktreeManager(tmp_path)

    orch = SoftwareFactoryOrchestrator(
        provider=provider,
        agent=AlwaysRejectAgent(),
        workspace=workspace,  # type: ignore[arg-type]
        validator=FakeValidator([True, True]),  # type: ignore[arg-type]
        max_turns=2,
    )

    results = orch.run_once()
    assert results[0].status == "needs-human"
    assert results[0].turns == 2

    saved = json.loads(issues_file.read_text(encoding="utf-8"))
    assert LABEL_NEEDS_HUMAN in saved["issues"][0]["labels"]
    assert "Escalonando para revisão humana" in saved["issues"][0]["comments"][0]


def test_mock_agent_runner_is_registered() -> None:
    assert isinstance(MockAgentRunner(), AgentRunner)
