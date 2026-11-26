from dataclasses import dataclass, field


@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class ValidationResult:
    passed: bool
    output: str


@dataclass
class ReviewResult:
    approved: bool
    summary: str
    findings: list[str] = field(default_factory=list)
    raw_output: str = ""


@dataclass
class RunResult:
    issue_number: int
    status: str  # "done" | "needs-human" | "failed"
    turns: int
    branch: str
    summary: str
    pr_url: str | None = None


@dataclass
class PullRequest:
    number: int
    issue_number: int
    branch: str
    title: str
    url: str = ""
    state: str = "open"


@dataclass
class PRReviewDecision:
    decision: str  # "approve_and_merge" | "approve_needs_human" | "request_changes" | "reject"
    summary: str
    findings: list[str] = field(default_factory=list)
    raw_output: str = ""


@dataclass
class PRReviewRunResult:
    issue_number: int
    pr_number: int
    status: str  # "merged" | "awaiting-human" | "rejected" | "needs-human"
    rounds: int
    summary: str
