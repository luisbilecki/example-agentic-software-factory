import json
from pathlib import Path

from factory.agents import AgentRunner
from factory.issue_providers import LocalJsonProvider
from factory.models import Issue, PRReviewDecision, ReviewResult, ValidationResult
from factory.orchestrator import LABEL_DONE
from factory.pr_reviewer import (
    LABEL_MERGED,
    LABEL_READY_FOR_HUMAN,
    LABEL_REJECTED,
    MockPRReviewerAgent,
    PRReviewOrchestrator,
)


class FakePRWorktreeManager:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.commits: list[str] = []

    def checkout_existing(self, issue_number: int, branch: str) -> Path:
        return self.tmp_path

    def commit_all(self, worktree_path: Path, message: str) -> bool:
        self.commits.append(message)
        return True

    def push_branch(self, worktree_path: Path, branch: str) -> None:
        pass

    def cleanup(self, worktree_path: Path) -> None:
        pass


class FakeValidator:
    def run(self, worktree_path: Path) -> ValidationResult:
        return ValidationResult(passed=True, output="ok")


class StubFixerAgent(AgentRunner):
    def __init__(self) -> None:
        self.feedbacks: list[str | None] = []

    def implement(
        self, worktree_path: Path, issue: Issue, feedback: str | None = None
    ) -> str:
        self.feedbacks.append(feedback)
        return "fixed"

    def review(self, worktree_path: Path, issue: Issue, diff: str) -> ReviewResult:
        return ReviewResult(approved=True, summary="ok")


def _seed_done_issue_with_pr(tmp_path: Path) -> Path:
    issues_file = tmp_path / "issues.json"
    issues_file.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "number": 1,
                        "title": "Adicionar filtro por email",
                        "body": "Filtrar por email.",
                        "labels": [LABEL_DONE],
                        "comments": [],
                    }
                ],
                "pull_requests": [
                    {
                        "number": 10,
                        "issue_number": 1,
                        "branch": "agent/issue-1",
                        "title": "feat(customers): adicionar filtro por email",
                        "body": "Closes #1",
                        "url": "local://pull/10",
                        "state": "open",
                        "comments": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return issues_file


def test_pr_reviewer_approve_and_merge(tmp_path: Path) -> None:
    issues_file = _seed_done_issue_with_pr(tmp_path)
    provider = LocalJsonProvider(issues_file)
    orch = PRReviewOrchestrator(
        provider=provider,
        reviewer=MockPRReviewerAgent(
            [PRReviewDecision(decision="approve_and_merge", summary="Tudo certo.")]
        ),
        fixer=StubFixerAgent(),
        workspace=FakePRWorktreeManager(tmp_path),  # type: ignore[arg-type]
        validator=FakeValidator(),  # type: ignore[arg-type]
    )

    results = orch.run_once()
    assert len(results) == 1
    assert results[0].status == "merged"
    saved = json.loads(issues_file.read_text(encoding="utf-8"))
    assert LABEL_MERGED in saved["issues"][0]["labels"]
    assert saved["pull_requests"][0]["state"] == "merged"


def test_pr_reviewer_approve_needs_human(tmp_path: Path) -> None:
    issues_file = _seed_done_issue_with_pr(tmp_path)
    provider = LocalJsonProvider(issues_file)
    orch = PRReviewOrchestrator(
        provider=provider,
        reviewer=MockPRReviewerAgent(
            [
                PRReviewDecision(
                    decision="approve_needs_human",
                    summary="Aprovado, mas altera contrato público.",
                )
            ]
        ),
        fixer=StubFixerAgent(),
        workspace=FakePRWorktreeManager(tmp_path),  # type: ignore[arg-type]
        validator=FakeValidator(),  # type: ignore[arg-type]
    )

    results = orch.run_once()
    assert results[0].status == "awaiting-human"
    saved = json.loads(issues_file.read_text(encoding="utf-8"))
    assert LABEL_READY_FOR_HUMAN in saved["issues"][0]["labels"]
    assert saved["pull_requests"][0]["state"] == "open"


def test_pr_reviewer_request_changes_then_fix_and_merge(tmp_path: Path) -> None:
    issues_file = _seed_done_issue_with_pr(tmp_path)
    provider = LocalJsonProvider(issues_file)
    fixer = StubFixerAgent()
    workspace = FakePRWorktreeManager(tmp_path)
    orch = PRReviewOrchestrator(
        provider=provider,
        reviewer=MockPRReviewerAgent(
            [
                PRReviewDecision(
                    decision="request_changes",
                    summary="Falta teste de case-insensitive.",
                    findings=["Adicionar teste com email em maiúsculas."],
                ),
                PRReviewDecision(
                    decision="approve_and_merge",
                    summary="Correção validada. Pronto para merge.",
                ),
            ]
        ),
        fixer=fixer,
        workspace=workspace,  # type: ignore[arg-type]
        validator=FakeValidator(),  # type: ignore[arg-type]
        max_rounds=3,
    )

    results = orch.run_once()
    assert results[0].status == "merged"
    assert results[0].rounds == 2
    assert len(fixer.feedbacks) == 1
    assert "maiúsculas" in (fixer.feedbacks[0] or "")
    assert len(workspace.commits) == 1


def test_pr_reviewer_reject_closes_pr(tmp_path: Path) -> None:
    issues_file = _seed_done_issue_with_pr(tmp_path)
    provider = LocalJsonProvider(issues_file)
    orch = PRReviewOrchestrator(
        provider=provider,
        reviewer=MockPRReviewerAgent(
            [
                PRReviewDecision(
                    decision="reject",
                    summary="Implementação fora do escopo da issue.",
                    findings=["Alterou rotas não relacionadas."],
                )
            ]
        ),
        fixer=StubFixerAgent(),
        workspace=FakePRWorktreeManager(tmp_path),  # type: ignore[arg-type]
        validator=FakeValidator(),  # type: ignore[arg-type]
    )

    results = orch.run_once()
    assert results[0].status == "rejected"
    saved = json.loads(issues_file.read_text(encoding="utf-8"))
    assert LABEL_REJECTED in saved["issues"][0]["labels"]
    assert saved["pull_requests"][0]["state"] == "closed"
