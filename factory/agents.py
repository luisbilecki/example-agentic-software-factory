import json
import re
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from factory.models import Issue, ReviewResult

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def build_implementer_prompt(issue: Issue, feedback: str | None = None) -> str:
    template = _load_prompt("implementer.md")
    feedback_section = (
        f"\n## Feedback da Tentativa Anterior (Corrija estes pontos)\n\n{feedback}\n"
        if feedback
        else ""
    )
    return (
        template.replace("{{ISSUE_NUMBER}}", str(issue.number))
        .replace("{{ISSUE_TITLE}}", issue.title)
        .replace("{{ISSUE_BODY}}", issue.body)
        .replace("{{FEEDBACK_SECTION}}", feedback_section)
    )


def build_reviewer_prompt(issue: Issue, diff: str) -> str:
    template = _load_prompt("reviewer.md")
    return (
        template.replace("{{ISSUE_NUMBER}}", str(issue.number))
        .replace("{{ISSUE_TITLE}}", issue.title)
        .replace("{{ISSUE_BODY}}", issue.body)
        .replace("{{GIT_DIFF}}", diff or "(nenhuma alteração detectada)")
    )


def parse_review_json(raw_output: str) -> ReviewResult:
    """Extrai o JSON estruturado da resposta do Agente Revisor."""
    match = re.search(r"\{[\s\S]*\}", raw_output)
    if not match:
        return ReviewResult(
            approved=False,
            summary="Revisor não retornou JSON válido.",
            findings=["Resposta do revisor fora do formato JSON esperado."],
            raw_output=raw_output,
        )
    try:
        payload = json.loads(match.group(0))
        return ReviewResult(
            approved=bool(payload.get("approved", False)),
            summary=str(payload.get("summary", "")),
            findings=[str(f) for f in payload.get("findings", [])],
            raw_output=raw_output,
        )
    except json.JSONDecodeError:
        return ReviewResult(
            approved=False,
            summary="Falha ao fazer parse do JSON retornado pelo revisor.",
            findings=["JSON inválido na resposta do revisor."],
            raw_output=raw_output,
        )


class AgentRunner(ABC):
    """Interface base extensível para qualquer IDE/CLI agêntica (Antigravity, Codex, Claude...)."""

    @abstractmethod
    def implement(
        self, worktree_path: Path, issue: Issue, feedback: str | None = None
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def review(self, worktree_path: Path, issue: Issue, diff: str) -> ReviewResult:
        raise NotImplementedError


class AntigravityAgentRunner(AgentRunner):
    """Adaptador nativo para o Antigravity CLI (`agy`)."""

    def __init__(self, binary: str = "agy", model: str | None = None) -> None:
        self.binary = binary
        self.model = model

    def _run_agy(self, worktree_path: Path, prompt: str, mode: str) -> str:
        cmd = [
            self.binary,
            "--print",
            prompt,
            "--mode",
            mode,
            "--sandbox",
            "--output-format",
            "text",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        proc = subprocess.run(
            cmd,
            cwd=worktree_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def implement(
        self, worktree_path: Path, issue: Issue, feedback: str | None = None
    ) -> str:
        prompt = build_implementer_prompt(issue, feedback)
        return self._run_agy(worktree_path, prompt, mode="accept-edits")

    def review(self, worktree_path: Path, issue: Issue, diff: str) -> ReviewResult:
        prompt = build_reviewer_prompt(issue, diff)
        raw = self._run_agy(worktree_path, prompt, mode="plan")
        return parse_review_json(raw)


class MockAgentRunner(AgentRunner):
    """Agente determinístico para testar a fábrica localmente sem custo de API."""

    def __init__(self, fail_first_review: bool = False) -> None:
        self.fail_first_review = fail_first_review
        self._review_calls = 0

    def implement(
        self, worktree_path: Path, issue: Issue, feedback: str | None = None
    ) -> str:
        # Implementa de forma real o filtro opcional por email em GET /customers
        repo_file = worktree_path / "app" / "repository.py"
        main_file = worktree_path / "app" / "main.py"
        test_file = worktree_path / "tests" / "test_customers_api.py"

        repo_src = repo_file.read_text(encoding="utf-8")
        if "email: str | None = None" not in repo_src:
            repo_src = repo_src.replace(
                "    def list(self) -> list[Customer]:\n        return list(self._items.values())",
                (
                    "    def list(self, email: str | None = None) -> list[Customer]:\n"
                    "        items = list(self._items.values())\n"
                    "        if email is not None:\n"
                    "            needle = email.lower()\n"
                    "            return [c for c in items if needle in c.email.lower()]\n"
                    "        return items"
                ),
            )
            repo_file.write_text(repo_src, encoding="utf-8")

        main_src = main_file.read_text(encoding="utf-8")
        if "email: str | None = None" not in main_src:
            main_src = main_src.replace(
                "def list_customers() -> list[Customer]:\n    return repository.list()",
                (
                    "def list_customers(email: str | None = None) -> list[Customer]:\n"
                    "    return repository.list(email=email)"
                ),
            )
            main_file.write_text(main_src, encoding="utf-8")

        test_src = test_file.read_text(encoding="utf-8")
        if "def test_filter_customers_by_email" not in test_src:
            test_src += (
                "\n\ndef test_filter_customers_by_email(client: TestClient) -> None:\n"
                '    client.post("/customers", json={"name": "Ada", "email": "ada@example.com"})\n'
                '    client.post("/customers", json={"name": "Grace", "email": "grace@navy.mil"})\n'
                '    filtered = client.get("/customers", params={"email": "ada"})\n'
                "    assert filtered.status_code == 200\n"
                "    data = filtered.json()\n"
                "    assert len(data) == 1\n"
                '    assert data[0]["email"] == "ada@example.com"\n'
            )
            test_file.write_text(test_src, encoding="utf-8")

        return f"Mock implementer aplicou filtro de email para issue #{issue.number}."

    def review(self, worktree_path: Path, issue: Issue, diff: str) -> ReviewResult:
        self._review_calls += 1
        if self.fail_first_review and self._review_calls == 1:
            return ReviewResult(
                approved=False,
                summary="Ajuste solicitado na primeira revisão simulada.",
                findings=["Garantir que o filtro por email seja case-insensitive."],
            )
        return ReviewResult(
            approved=True,
            summary="Código limpo, aderente ao AGENTS.md e com testes cobrindo o filtro.",
            findings=[],
        )


# Registro extensível de agentes.
# Para suportar Codex, Claude Code, etc. no futuro, basta registrar uma nova fábrica aqui.
AGENT_REGISTRY: dict[str, Callable[[], AgentRunner]] = {
    "antigravity": AntigravityAgentRunner,
    "agy": AntigravityAgentRunner,
    "mock": MockAgentRunner,
}


def create_agent_runner(name: str) -> AgentRunner:
    factory = AGENT_REGISTRY.get(name.lower())
    if factory is None:
        supported = ", ".join(sorted(AGENT_REGISTRY))
        raise ValueError(
            f"Agente '{name}' não suportado ainda. Disponíveis: {supported}. "
            "Para adicionar novos agentes (ex: codex, claude), registre em AGENT_REGISTRY."
        )
    return factory()
