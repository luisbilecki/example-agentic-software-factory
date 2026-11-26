import json
from pathlib import Path

from factory.issue_providers import LocalJsonProvider
from factory.orchestrator import LABEL_READY
from factory.planner import SpecPlanner, parse_planned_issues_json


def test_parse_planned_issues_json() -> None:
    raw = 'Aqui estão as issues:\n```json\n[{"title": "Add filter", "body": "Details"}]\n```'
    parsed = parse_planned_issues_json(raw)
    assert parsed == [{"title": "Add filter", "body": "Details"}]


def test_spec_planner_mock_creates_issues_from_spec(tmp_path: Path) -> None:
    issues_file = tmp_path / "issues.json"
    issues_file.write_text(json.dumps({"issues": [], "pull_requests": []}), encoding="utf-8")

    spec_path = Path("specs/001-customers-enhancements.md")
    provider = LocalJsonProvider(issues_file)
    planner = SpecPlanner(provider=provider, agent_name="mock")

    created = planner.create_issues_from_spec(spec_path)
    assert len(created) == 4
    assert all(LABEL_READY in issue.labels for issue in created)
    assert created[0].title == "Adicionar filtro opcional por email no GET /customers"

    saved = json.loads(issues_file.read_text(encoding="utf-8"))
    assert len(saved["issues"]) == 4
