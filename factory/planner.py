import argparse
import json
import re
import subprocess
from pathlib import Path

from factory.issue_providers import GitHubCliProvider, IssueProvider, LocalJsonProvider
from factory.models import Issue
from factory.orchestrator import LABEL_READY

PROMPTS_DIR = Path(__file__).parent / "prompts"


def build_planner_prompt(spec_content: str) -> str:
    template = (PROMPTS_DIR / "planner.md").read_text(encoding="utf-8")
    return template.replace("{{SPEC_CONTENT}}", spec_content)


def parse_planned_issues_json(raw_output: str) -> list[dict[str, str]]:
    match = re.search(r"\[[\s\S]*\]", raw_output)
    if not match:
        raise ValueError("Agente planejador não retornou um array JSON válido.")
    items = json.loads(match.group(0))
    return [
        {"title": str(item["title"]).strip(), "body": str(item.get("body", "")).strip()}
        for item in items
        if item.get("title")
    ]


def parse_spec_tasks_deterministic(spec_content: str) -> list[dict[str, str]]:
    """Parser determinístico (modo mock) que extrai seções `### Task: ...` de uma Spec."""
    tasks: list[dict[str, str]] = []
    sections = re.split(r"(?m)^###\s+Task:\s*", spec_content)
    for section in sections[1:]:
        lines = section.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        tasks.append({"title": title, "body": body})
    return tasks


class SpecPlanner:
    """Converte uma Spec/PRD em issues atômicas com a label `agent:ready`."""

    def __init__(
        self,
        provider: IssueProvider,
        agent_name: str = "antigravity",
        agy_binary: str = "agy",
    ) -> None:
        self.provider = provider
        self.agent_name = agent_name.lower()
        self.agy_binary = agy_binary

    def _plan_tasks(self, spec_content: str) -> list[dict[str, str]]:
        if self.agent_name == "mock":
            return parse_spec_tasks_deterministic(spec_content)
        if self.agent_name in ("antigravity", "agy"):
            prompt = build_planner_prompt(spec_content)
            proc = subprocess.run(
                [
                    self.agy_binary,
                    "--print",
                    prompt,
                    "--mode",
                    "plan",
                    "--sandbox",
                    "--output-format",
                    "text",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return parse_planned_issues_json(proc.stdout)
        raise ValueError(
            f"Agente planejador '{self.agent_name}' não suportado. Use 'antigravity' ou 'mock'."
        )

    def create_issues_from_spec(self, spec_path: Path) -> list[Issue]:
        spec_content = spec_path.read_text(encoding="utf-8")
        planned = self._plan_tasks(spec_content)
        created: list[Issue] = []
        for task in planned:
            body_with_ref = f"{task['body']}\n\nOrigem: `{spec_path.as_posix()}`"
            issue = self.provider.create_issue(
                title=task["title"],
                body=body_with_ref.strip(),
                labels=[LABEL_READY],
            )
            created.append(issue)
        return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agente Planejador: gera issues a partir de uma Spec/PRD"
    )
    parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Caminho para o arquivo de Spec/PRD em Markdown",
    )
    parser.add_argument(
        "--provider",
        choices=["local", "github"],
        default="local",
        help="Destino das issues geradas (default: local)",
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
        help="Agente planejador (antigravity, agy, mock)",
    )
    args = parser.parse_args()

    provider: IssueProvider = (
        LocalJsonProvider(args.issues_file)
        if args.provider == "local"
        else GitHubCliProvider(repo=args.repo)
    )
    planner = SpecPlanner(provider=provider, agent_name=args.agent)
    issues = planner.create_issues_from_spec(args.spec)
    for issue in issues:
        print(f"[Criada Issue #{issue.number}] {issue.title} ({issue.url})")


if __name__ == "__main__":
    main()
