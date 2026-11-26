import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from factory.models import Issue, PullRequest


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
    def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> Issue:
        raise NotImplementedError

    @abstractmethod
    def create_pull_request(
        self, issue: Issue, branch: str, title: str, body: str
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def find_open_pr_for_issue(self, issue_number: int) -> PullRequest | None:
        raise NotImplementedError

    @abstractmethod
    def get_pr_diff(self, pr: PullRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def comment_on_pr(self, pr: PullRequest, body: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def merge_pr(self, pr: PullRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def close_pr(self, pr: PullRequest, reason: str) -> None:
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

    def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> Issue:
        data = self._load()
        issues = data.setdefault("issues", [])
        next_number = max((item["number"] for item in issues), default=0) + 1
        issue_labels = list(labels) if labels is not None else ["agent:ready"]
        issues.append(
            {
                "number": next_number,
                "title": title,
                "body": body,
                "labels": issue_labels,
                "comments": [],
            }
        )
        self._save(data)
        return Issue(
            number=next_number,
            title=title,
            body=body,
            labels=issue_labels,
            url=f"local://issues/{next_number}",
        )

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
                "state": "open",
                "comments": [],
            }
        )
        self._save(data)
        return pr_url

    def find_open_pr_for_issue(self, issue_number: int) -> PullRequest | None:
        data = self._load()
        for item in data.get("pull_requests", []):
            if item.get("issue_number") == issue_number and item.get("state", "open") == "open":
                return PullRequest(
                    number=item["number"],
                    issue_number=issue_number,
                    branch=item["branch"],
                    title=item["title"],
                    url=item.get("url", ""),
                    state=item.get("state", "open"),
                )
        return None

    def get_pr_diff(self, pr: PullRequest) -> str:
        proc = subprocess.run(
            ["git", "diff", f"main...{pr.branch}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout.strip()

    def comment_on_pr(self, pr: PullRequest, body: str) -> None:
        data = self._load()
        for item in data.get("pull_requests", []):
            if item["number"] == pr.number:
                item.setdefault("comments", []).append(body)
                break
        self._save(data)

    def merge_pr(self, pr: PullRequest) -> None:
        data = self._load()
        for item in data.get("pull_requests", []):
            if item["number"] == pr.number:
                item["state"] = "merged"
                break
        self._save(data)

    def close_pr(self, pr: PullRequest, reason: str) -> None:
        self.comment_on_pr(pr, reason)
        data = self._load()
        for item in data.get("pull_requests", []):
            if item["number"] == pr.number:
                item["state"] = "closed"
                break
        self._save(data)


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

    def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> Issue:
        issue_labels = list(labels) if labels is not None else ["agent:ready"]
        args = ["issue", "create", "--title", title, "--body", body]
        for lb in issue_labels:
            args.extend(["--label", lb])
        url = self._gh(args)
        tail = url.rstrip("/").split("/")[-1]
        number = int(tail) if tail.isdigit() else 0
        return Issue(number=number, title=title, body=body, labels=issue_labels, url=url)

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

    def find_open_pr_for_issue(self, issue_number: int) -> PullRequest | None:
        branch = f"agent/issue-{issue_number}"
        raw = self._gh(
            [
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number,title,url,headRefName,state",
            ]
        )
        items = json.loads(raw or "[]")
        if not items:
            return None
        pr = items[0]
        return PullRequest(
            number=pr["number"],
            issue_number=issue_number,
            branch=pr["headRefName"],
            title=pr["title"],
            url=pr.get("url", ""),
            state="open",
        )

    def get_pr_diff(self, pr: PullRequest) -> str:
        return self._gh(["pr", "diff", str(pr.number)])

    def comment_on_pr(self, pr: PullRequest, body: str) -> None:
        self._gh(["pr", "comment", str(pr.number), "--body", body])

    def merge_pr(self, pr: PullRequest) -> None:
        self._gh(["pr", "merge", str(pr.number), "--squash", "--delete-branch"])

    def close_pr(self, pr: PullRequest, reason: str) -> None:
        self._gh(["pr", "close", str(pr.number), "--comment", reason])
