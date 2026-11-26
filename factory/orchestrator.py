import argparse
import re
from pathlib import Path

from factory.agents import AgentRunner, create_agent_runner
from factory.issue_providers import GitHubCliProvider, IssueProvider, LocalJsonProvider
from factory.models import Issue, RunResult
from factory.validator import DeterministicValidator
from factory.workspace import WorktreeManager

LABEL_READY = "agent:ready"
LABEL_IN_PROGRESS = "agent:in-progress"
LABEL_DONE = "agent:done"
LABEL_NEEDS_HUMAN = "agent:needs-human"


def format_conventional_commit(issue: Issue) -> str:
    """Gera uma mensagem de commit no padrão Conventional Commits."""
    title = issue.title.strip()
    lower = title.lower()
    if any(k in lower for k in ("fix", "bug", "corrig", "erro")):
        commit_type = "fix"
    elif any(k in lower for k in ("refactor", "refator")):
        commit_type = "refactor"
    elif any(k in lower for k in ("test", "teste")):
        commit_type = "test"
    elif any(k in lower for k in ("doc", "readme")):
        commit_type = "docs"
    else:
        commit_type = "feat"

    clean_title = re.sub(
        r"^(feat|fix|refactor|test|docs|chore)(\([^)]+\))?:\s*",
        "",
        title,
        flags=re.I,
    )
    if clean_title:
        clean_title = clean_title[0].lower() + clean_title[1:]
    else:
        clean_title = f"resolve issue {issue.number}"
    return f"{commit_type}(customers): {clean_title}\n\nCloses #{issue.number}"


class SoftwareFactoryOrchestrator:
    """Máquina de estados da Fábrica de Software Agêntica v2."""

    def __init__(
        self,
        provider: IssueProvider,
        agent: AgentRunner,
        workspace: WorktreeManager,
        validator: DeterministicValidator,
        max_turns: int = 3,
        push_to_remote: bool = False,
        cleanup_worktree: bool = True,
    ) -> None:
        self.provider = provider
        self.agent = agent
        self.workspace = workspace
        self.validator = validator
        self.max_turns = max_turns
        self.push_to_remote = push_to_remote
        self.cleanup_worktree = cleanup_worktree

    def process_issue(self, issue: Issue) -> RunResult:
        self.provider.swap_labels(
            issue.number, remove=[LABEL_READY], add=[LABEL_IN_PROGRESS]
        )
        worktree_path, branch = self.workspace.create(issue.number)
        feedback: str | None = None

        try:
            for turn in range(1, self.max_turns + 1):
                # 1. Implementação
                self.agent.implement(worktree_path, issue, feedback=feedback)

                # 2. Validação determinística (backpressure: ruff + pytest)
                validation = self.validator.run(worktree_path)
                if not validation.passed:
                    feedback = f"Validação falhou (tentativa {turn}):\n{validation.output}"
                    continue

                # 3. Revisão independente (contexto limpo sobre o git diff)
                diff = self.workspace.get_diff(worktree_path)
                review = self.agent.review(worktree_path, issue, diff)
                if not review.approved:
                    findings_text = "\n".join(f"- {f}" for f in review.findings)
                    feedback = (
                        f"Revisão reprovada (tentativa {turn}): {review.summary}\n"
                        f"{findings_text}"
                    )
                    continue

                # 4. Finalização: Conventional Commit + Push (se remoto) + PR + Label Done
                commit_msg = format_conventional_commit(issue)
                self.workspace.commit_all(worktree_path, commit_msg)
                if self.push_to_remote:
                    self.workspace.push_branch(worktree_path, branch)

                pr_title = commit_msg.splitlines()[0]
                pr_body = (
                    f"Implementação automática pela Fábrica Agêntica v2.\n\n"
                    f"Closes #{issue.number}\n\n"
                    f"### Resumo da Revisão\n{review.summary}"
                )
                pr_url = self.provider.create_pull_request(
                    issue=issue, branch=branch, title=pr_title, body=pr_body
                )
                self.provider.swap_labels(
                    issue.number, remove=[LABEL_IN_PROGRESS], add=[LABEL_DONE]
                )
                self.provider.add_comment(
                    issue.number,
                    f"Concluído em {turn} tentativa(s). PR: {pr_url}\n\nRevisão: {review.summary}",
                )
                return RunResult(
                    issue_number=issue.number,
                    status="done",
                    turns=turn,
                    branch=branch,
                    summary=review.summary,
                    pr_url=pr_url,
                )

            # Limite de tentativas atingido -> escalonar para humano
            self.provider.swap_labels(
                issue.number, remove=[LABEL_IN_PROGRESS], add=[LABEL_NEEDS_HUMAN]
            )
            self.provider.add_comment(
                issue.number,
                (
                    f"Limite de {self.max_turns} tentativas atingido. "
                    "Escalonando para revisão humana.\n\n"
                    f"Último diagnóstico:\n```\n{feedback or 'Sem detalhes'}\n```"
                ),
            )
            return RunResult(
                issue_number=issue.number,
                status="needs-human",
                turns=self.max_turns,
                branch=branch,
                summary=feedback or "Limite de tentativas atingido.",
            )
        finally:
            if self.cleanup_worktree:
                self.workspace.cleanup(worktree_path)

    def run_once(self) -> list[RunResult]:
        issues = self.provider.list_ready_issues(LABEL_READY)
        return [self.process_issue(issue) for issue in issues]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orquestrador da Fábrica de Software Agêntica v2"
    )
    parser.add_argument(
        "--provider",
        choices=["local", "github"],
        default="local",
        help="Origem das issues (default: local)",
    )
    parser.add_argument(
        "--issues-file",
        type=Path,
        default=Path("examples/local_issues.json"),
        help="Arquivo JSON de issues para o provider local",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repositório GitHub (owner/repo) opcional para o provider github",
    )
    parser.add_argument(
        "--agent",
        default="antigravity",
        help="Adaptador de agente (antigravity, agy, mock)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=3,
        help="Máximo de tentativas no loop implementação -> validação -> revisão",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    provider: IssueProvider = (
        LocalJsonProvider(args.issues_file)
        if args.provider == "local"
        else GitHubCliProvider(repo=args.repo)
    )
    agent = create_agent_runner(args.agent)
    workspace = WorktreeManager(repo_root=repo_root)
    validator = DeterministicValidator()

    orchestrator = SoftwareFactoryOrchestrator(
        provider=provider,
        agent=agent,
        workspace=workspace,
        validator=validator,
        max_turns=args.max_turns,
        push_to_remote=(args.provider == "github"),
    )

    results = orchestrator.run_once()
    if not results:
        print(f"Nenhuma issue encontrada com a label '{LABEL_READY}'.")
        return
    for res in results:
        print(
            f"[Issue #{res.issue_number}] status={res.status} turns={res.turns} "
            f"branch={res.branch} pr={res.pr_url or '-'}"
        )


if __name__ == "__main__":
    main()
