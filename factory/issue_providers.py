import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from factory.models import Issue


class IssueProvider(ABC):
    """Abstração para leitura e atualização de issues (GitHub real ou JSON local)."""

    @abstractmethod
    def list_ready_issues(self, ready_label: str = "agent:ready") -> list[Issue]:
        raise NotImplementedError

    @abstractmethod
    def swap_labels(
        self, issue_number: int, remove: list[str], add: list[str]
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_comment(self, issue_number: int, body: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_pull_request(
        self, issue: Issue, branch: str, title: str, body: str
    ) -> str:
        raise NotImplementedError


class LocalJsonProvider(IssueProvider):
    """Provedor local baseado em arquivo JSON para testes e demonstrações offline."""

    def __init__(self, json_path: Path) -> None:
        self.json_path = json_path

    def _load(self) -> dict:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def list_ready_issues(self, ready_label: str = "agent:ready") -> list[Issue]:
        data = self._load()
        issues: list[Issue] = []
        for item in data.get("issues", []):
            if ready_label in item.get("labels", []):
                issues.append(
                    Issue(
                        number=item["number"],
                        title=item["title"],
                        body=item.get("body", ""),
                        labels=list(item.get("labels", [])),
                        url=f"local://issues/{item['number']}",
                    )
                )
        return issues

    def swap_labels(
        self, issue_number: int, remove: list[str], add: list[str]
    ) -> None:
        data = self._load()
        for item in data.get("issues", []):
            if item["number"] == issue_number:
                labels = [lb for lb in item.get("labels", []) if lb not in remove]
                for lb in add:
                    if lb not in labels:
                        labels.append(lb)
                item["labels"] = labels
                break
        self._save(data)

    def add_comment(self, issue_number: int, body: str) -> None:
        data = self._load()
        for item in data.get("issues", []):
            if item["number"] == issue_number:
                item.setdefault("comments", []).append(body)
                break
        self._save(data)

    def create_pull_request(
        self, issue: Issue, branch: str, title: str, body: str
    ) -> str:
        data = self._load()
        pr_number = len(data.get("pull_requests", [])) + 1
        pr_url = f"local://pull/{pr_number}"
        data.setdefault("pull_requests", []).append(
            {
                "number": pr_number,
                "issue_number": issue.number,
                "branch": branch,
                "title": title,
                "body": body,
                "url": pr_url,
            }
        )
        self._save(data)
        return pr_url


class GitHubCliProvider(IssueProvider):
    """Provedor real usando GitHub CLI (`gh`)."""

    def __init__(self, repo: str | None = None) -> None:
        self.repo = repo

    def _gh(self, args: list[str]) -> str:
        cmd = ["gh", *args]
        if self.repo:
            cmd.extend(["--repo", self.repo])
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return proc.stdout.strip()

    def list_ready_issues(self, ready_label: str = "agent:ready") -> list[Issue]:
        raw = self._gh(
            [
                "issue",
                "list",
                "--label",
                ready_label,
                "--state",
                "open",
                "--json",
                "number,title,body,labels,url",
            ]
        )
        items = json.loads(raw or "[]")
        return [
            Issue(
                number=item["number"],
                title=item["title"],
                body=item.get("body", ""),
                labels=[lb["name"] for lb in item.get("labels", [])],
                url=item.get("url", ""),
            )
            for item in items
        ]

    def swap_labels(
        self, issue_number: int, remove: list[str], add: list[str]
    ) -> None:
        args = ["issue", "edit", str(issue_number)]
        for lb in remove:
            args.extend(["--remove-label", lb])
        for lb in add:
            args.extend(["--add-label", lb])
        self._gh(args)

    def add_comment(self, issue_number: int, body: str) -> None:
        self._gh(["issue", "comment", str(issue_number), "--body", body])

    def create_pull_request(
        self, issue: Issue, branch: str, title: str, body: str
    ) -> str:
        return self._gh(
            [
                "pr",
                "create",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
        )
