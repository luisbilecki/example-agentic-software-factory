import argparse
import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from factory.agents import AgentRunner, create_agent_runner
from factory.issue_providers import GitHubCliProvider, IssueProvider, LocalJsonProvider
from factory.models import Issue, PRReviewDecision, PRReviewRunResult, PullRequest
from factory.orchestrator import LABEL_DONE, LABEL_NEEDS_HUMAN
from factory.validator import DeterministicValidator
from factory.workspace import WorktreeManager

logger = logging.getLogger("factory.pr_reviewer")

LABEL_MERGED = "agent:merged"
LABEL_READY_FOR_HUMAN = "agent:ready-for-human"
LABEL_REJECTED = "agent:rejected"

PROMPTS_DIR = Path(__file__).parent / "prompts"
VALID_DECISIONS = {
    "approve_and_merge",
    "approve_needs_human",
    "request_changes",
    "reject",
}


def build_pr_reviewer_prompt(issue: Issue, pr: PullRequest, diff: str) -> str:
    template = (PROMPTS_DIR / "pr_reviewer.md").read_text(encoding="utf-8")
    return (
        template.replace("{{ISSUE_NUMBER}}", str(issue.number))
        .replace("{{ISSUE_TITLE}}", issue.title)
        .replace("{{ISSUE_BODY}}", issue.body)
        .replace("{{PR_NUMBER}}", str(pr.number))
        .replace("{{PR_TITLE}}", pr.title)
        .replace("{{PR_DIFF}}", diff or "(nenhuma alteração detectada)")
    )


def parse_pr_review_decision(raw_output: str) -> PRReviewDecision:
    match = re.search(r"\{[\s\S]*\}", raw_output)
    if not match:
        return PRReviewDecision(
            decision="request_changes",
            summary="Revisor de PR não retornou JSON válido.",
            findings=["Resposta fora do formato JSON esperado."],
            raw_output=raw_output,
        )
    try:
        payload = json.loads(match.group(0))
        decision = str(payload.get("decision", "request_changes")).strip()
        if decision not in VALID_DECISIONS:
            decision = "approve_needs_human"
        return PRReviewDecision(
            decision=decision,
            summary=str(payload.get("summary", "")),
            findings=[str(f) for f in payload.get("findings", [])],
            raw_output=raw_output,
        )
    except json.JSONDecodeError:
        return PRReviewDecision(
            decision="request_changes",
            summary="Falha ao fazer parse do JSON do Revisor de PR.",
            findings=["JSON inválido na resposta do revisor de PR."],
            raw_output=raw_output,
        )


class PRReviewerAgent(ABC):
    """Interface do Agente Especializado em Revisão de PRs."""

    @abstractmethod
    def review_pr(self, issue: Issue, pr: PullRequest, diff: str) -> PRReviewDecision:
        raise NotImplementedError


class AntigravityPRReviewerAgent(PRReviewerAgent):
    """Revisor de PRs usando Antigravity CLI (`agy`)."""

    def __init__(self, binary: str = "agy", model: str | None = None) -> None:
        self.binary = binary
        self.model = model

    def review_pr(self, issue: Issue, pr: PullRequest, diff: str) -> PRReviewDecision:
        prompt = build_pr_reviewer_prompt(issue, pr, diff)
        cmd = [
            self.binary,
            "--print",
            prompt,
            "--mode",
            "plan",
            "--sandbox",
            "--output-format",
            "text",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return parse_pr_review_decision(proc.stdout.strip())


class MockPRReviewerAgent(PRReviewerAgent):
    """Revisor de PRs simulado para testes locais."""

    def __init__(self, decisions: list[PRReviewDecision] | None = None) -> None:
        self._decisions = list(decisions) if decisions is not None else []

    def review_pr(self, issue: Issue, pr: PullRequest, diff: str) -> PRReviewDecision:
        if self._decisions:
            return self._decisions.pop(0)
        return PRReviewDecision(
            decision="approve_and_merge",
            summary="PR revisado, testes verdes e seguro para merge automático.",
            findings=[],
        )


class PRReviewOrchestrator:
    """Pega issues com `agent:done`, revisa o PR e coordena correções até a decisão final."""

    def __init__(
        self,
        provider: IssueProvider,
        reviewer: PRReviewerAgent,
        fixer: AgentRunner,
        workspace: WorktreeManager,
        validator: DeterministicValidator,
        max_rounds: int = 3,
        push_to_remote: bool = False,
        cleanup_worktree: bool = True,
    ) -> None:
        self.provider = provider
        self.reviewer = reviewer
        self.fixer = fixer
        self.workspace = workspace
        self.validator = validator
        self.max_rounds = max_rounds
        self.push_to_remote = push_to_remote
        self.cleanup_worktree = cleanup_worktree

    def process_done_issue(self, issue: Issue) -> PRReviewRunResult | None:
        pr = self.provider.find_open_pr_for_issue(issue.number)
        if pr is None:
            logger.warning(
                "[Issue #%s] Nenhum PR aberto encontrado. Pulando.",
                issue.number,
            )
            return None

        logger.info(
            "[Issue #%s | PR #%s] Iniciando revisão especializada: %s",
            issue.number,
            pr.number,
            pr.title,
        )

        last_summary = ""
        for round_num in range(1, self.max_rounds + 1):
            logger.info(
                "[Issue #%s | PR #%s] Rodada %d/%d — Executando Agente Revisor de PR...",
                issue.number,
                pr.number,
                round_num,
                self.max_rounds,
            )
            diff = self.provider.get_pr_diff(pr)
            decision = self.reviewer.review_pr(issue, pr, diff)
            last_summary = decision.summary

            if decision.decision == "approve_and_merge":
                logger.info(
                    "[Issue #%s | PR #%s] APROVADO para merge automático: %s",
                    issue.number,
                    pr.number,
                    decision.summary,
                )
                try:
                    self.provider.merge_pr(pr)
                except subprocess.CalledProcessError as exc:
                    err_detail = (exc.stderr or exc.stdout or str(exc)).strip()
                    logger.warning(
                        "[Issue #%s | PR #%s] Falha no merge (possível conflito com main): %s",
                        issue.number,
                        pr.number,
                        err_detail,
                    )
                    self.provider.comment_on_pr(
                        pr,
                        "PR aprovado tecnicamente, mas o merge automático falhou "
                        "(possível conflito com `main`). Acionando Agente Corretor para "
                        f"sincronizar com `main` e resolver conflitos.\n\n```\n{err_detail}\n```",
                    )
                    worktree_path = self.workspace.checkout_existing(issue.number, pr.branch)
                    try:
                        clean, merge_output = self.workspace.sync_with_main(worktree_path)
                        if not clean:
                            conflict_feedback = (
                                f"Resolva os conflitos com `origin/main` no PR #{pr.number}, "
                                "mantenha todas as funcionalidades e garanta `ruff` e `pytest` "
                                f"passando 100%.\n\nSaída do git merge:\n{merge_output}"
                            )
                            self.fixer.implement(worktree_path, issue, feedback=conflict_feedback)
                        validation = self.validator.run(worktree_path)
                        if not validation.passed:
                            self.fixer.implement(
                                worktree_path,
                                issue,
                                feedback=f"Corrija falhas pós-merge:\n{validation.output}",
                            )
                        self.workspace.commit_all(
                            worktree_path,
                            f"fix(customers): resolve merge conflicts for PR #{pr.number}",
                        )
                        if self.push_to_remote:
                            self.workspace.push_branch(worktree_path, pr.branch)
                    finally:
                        if self.cleanup_worktree:
                            self.workspace.cleanup(worktree_path)
                    continue

                self.provider.comment_on_pr(
                    pr, f"Aprovado pelo Revisor de PR (auto-merge).\n\n{decision.summary}"
                )
                self.provider.swap_labels(
                    issue.number, remove=[LABEL_DONE], add=[LABEL_MERGED]
                )
                return PRReviewRunResult(
                    issue_number=issue.number,
                    pr_number=pr.number,
                    status="merged",
                    rounds=round_num,
                    summary=decision.summary,
                )

            if decision.decision == "approve_needs_human":
                logger.info(
                    "[Issue #%s | PR #%s] APROVADO aguardando decisão humana: %s",
                    issue.number,
                    pr.number,
                    decision.summary,
                )
                self.provider.comment_on_pr(
                    pr,
                    "Aprovado tecnicamente pelo Revisor de PR — "
                    f"aguardando revisão e decisão final humana.\n\n{decision.summary}",
                )
                self.provider.swap_labels(
                    issue.number, remove=[LABEL_DONE], add=[LABEL_READY_FOR_HUMAN]
                )
                return PRReviewRunResult(
                    issue_number=issue.number,
                    pr_number=pr.number,
                    status="awaiting-human",
                    rounds=round_num,
                    summary=decision.summary,
                )

            if decision.decision == "reject":
                logger.warning(
                    "[Issue #%s | PR #%s] REJEITADO: %s",
                    issue.number,
                    pr.number,
                    decision.summary,
                )
                findings_md = "\n".join(f"- {f}" for f in decision.findings)
                reason = f"PR rejeitado pelo Revisor Especializado.\n\n{decision.summary}"
                if findings_md:
                    reason += f"\n\n### Motivos\n{findings_md}"
                self.provider.close_pr(pr, reason)
                self.provider.swap_labels(
                    issue.number, remove=[LABEL_DONE], add=[LABEL_REJECTED]
                )
                return PRReviewRunResult(
                    issue_number=issue.number,
                    pr_number=pr.number,
                    status="rejected",
                    rounds=round_num,
                    summary=decision.summary,
                )

            # decision == "request_changes" -> Aciona o Agente Corretor e pede nova revisão
            logger.warning(
                "[Issue #%s | PR #%s] Correções solicitadas (%d finding(s)). "
                "Acionando Agente Corretor...",
                issue.number,
                pr.number,
                len(decision.findings),
            )
            findings_md = "\n".join(f"- {f}" for f in decision.findings)
            feedback = (
                f"Correções solicitadas na revisão do PR #{pr.number} "
                f"(rodada {round_num}):\n{decision.summary}\n{findings_md}"
            )
            self.provider.comment_on_pr(pr, feedback)

            worktree_path = self.workspace.checkout_existing(issue.number, pr.branch)
            try:
                self.fixer.implement(worktree_path, issue, feedback=feedback)
                validation = self.validator.run(worktree_path)
                if not validation.passed:
                    logger.warning(
                        "[Issue #%s | PR #%s] Validação falhou após correção; "
                        "tentando ajuste adicional...",
                        issue.number,
                        pr.number,
                    )
                    self.fixer.implement(
                        worktree_path,
                        issue,
                        feedback=f"{feedback}\n\nErro de validação:\n{validation.output}",
                    )
                commit_msg = (
                    f"fix(customers): address PR #{pr.number} review findings (round {round_num})"
                )
                self.workspace.commit_all(worktree_path, commit_msg)
                if self.push_to_remote:
                    self.workspace.push_branch(worktree_path, pr.branch)
                logger.info(
                    "[Issue #%s | PR #%s] Correções aplicadas. Solicitando nova revisão...",
                    issue.number,
                    pr.number,
                )
            finally:
                if self.cleanup_worktree:
                    self.workspace.cleanup(worktree_path)

        # Limite de rodadas atingido -> escalonar para humano
        logger.error(
            "[Issue #%s | PR #%s] Limite de %d rodadas atingido. Escalonando para humano.",
            issue.number,
            pr.number,
            self.max_rounds,
        )
        self.provider.comment_on_pr(
            pr,
            f"Limite de {self.max_rounds} rodadas de revisão/correção atingido. "
            f"Escalonando para humano.\n\nÚltimo resumo: {last_summary}",
        )
        self.provider.swap_labels(
            issue.number, remove=[LABEL_DONE], add=[LABEL_NEEDS_HUMAN]
        )
        return PRReviewRunResult(
            issue_number=issue.number,
            pr_number=pr.number,
            status="needs-human",
            rounds=self.max_rounds,
            summary=last_summary,
        )

    def run_once(self) -> list[PRReviewRunResult]:
        logger.info("Buscando issues com a label '%s' para revisão de PR...", LABEL_DONE)
        issues = self.provider.list_ready_issues(LABEL_DONE)
        logger.info("Encontradas %d issue(s) com '%s'.", len(issues), LABEL_DONE)
        results: list[PRReviewRunResult] = []
        for issue in issues:
            res = self.process_done_issue(issue)
            if res is not None:
                results.append(res)
        return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Agente Especializado Revisor de PRs para issues com agent:done"
    )
    parser.add_argument(
        "--provider",
        choices=["local", "github"],
        default="local",
        help="Origem das issues/PRs (default: local)",
    )
    parser.add_argument(
        "--issues-file",
        type=Path,
        default=Path("examples/local_issues.json"),
        help="Arquivo JSON para o provider local",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repositório GitHub (owner/repo) opcional",
    )
    parser.add_argument(
        "--agent",
        default="antigravity",
        help="Agente para revisão e correção (antigravity, agy, mock)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Máximo de rodadas de revisão -> correção -> nova revisão",
    )
    args = parser.parse_args()

    provider: IssueProvider = (
        LocalJsonProvider(args.issues_file)
        if args.provider == "local"
        else GitHubCliProvider(repo=args.repo)
    )
    reviewer: PRReviewerAgent = (
        MockPRReviewerAgent()
        if args.agent.lower() == "mock"
        else AntigravityPRReviewerAgent()
    )
    fixer = create_agent_runner(args.agent)
    workspace = WorktreeManager(repo_root=Path.cwd())
    validator = DeterministicValidator()

    orch = PRReviewOrchestrator(
        provider=provider,
        reviewer=reviewer,
        fixer=fixer,
        workspace=workspace,
        validator=validator,
        max_rounds=args.max_rounds,
        push_to_remote=(args.provider == "github"),
    )
    results = orch.run_once()
    if not results:
        print(f"Nenhum PR aberto encontrado para issues com '{LABEL_DONE}'.")
        return
    for res in results:
        print(
            f"[Issue #{res.issue_number} | PR #{res.pr_number}] "
            f"status={res.status} rounds={res.rounds}"
        )


if __name__ == "__main__":
    main()
