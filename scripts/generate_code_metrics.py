#!/usr/bin/env python3
"""Generate a GitHub profile code velocity SVG.

The script intentionally uses only the Python standard library so it can be
copied into a profile README repository and run from GitHub Actions without
installing dependencies.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.sax.saxutils import escape


GITHUB_API = "https://api.github.com"
CARD_WIDTH = 920
CARD_HEIGHT = 640

SKIP_DIRS = {
    ".git",
    ".github",
    ".idea",
    ".next",
    ".terraform",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "out",
    "target",
    "vendor",
}

LANG_BY_SUFFIX = {
    ".astro": "Astro",
    ".bash": "Shell",
    ".c": "C/C++",
    ".cc": "C/C++",
    ".cpp": "C/C++",
    ".cs": "C#",
    ".css": "CSS",
    ".dockerfile": "Dockerfile",
    ".go": "Go",
    ".h": "C/C++",
    ".hpp": "C/C++",
    ".html": "HTML",
    ".htm": "HTML",
    ".ipynb": "Jupyter Notebook",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".mdx": "MDX",
    ".php": "PHP",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".r": "R",
    ".rs": "Rust",
    ".sass": "Sass",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".tf": "HCL",
    ".tfvars": "HCL",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}

LINE_COMMENT = {
    "Astro": ["//"],
    "C/C++": ["//"],
    "C#": ["//"],
    "Dockerfile": ["#"],
    "Go": ["//"],
    "HCL": ["#", "//"],
    "Java": ["//"],
    "JavaScript": ["//"],
    "Jupyter Notebook": ["#"],
    "PHP": ["//", "#"],
    "PowerShell": ["#"],
    "Python": ["#"],
    "R": ["#"],
    "Rust": ["//"],
    "Sass": ["//"],
    "SCSS": ["//"],
    "Shell": ["#"],
    "SQL": ["--"],
    "TypeScript": ["//"],
    "Vue": ["//"],
}

BLOCK_COMMENT = {
    "Astro": [("/*", "*/"), ("<!--", "-->")],
    "C/C++": [("/*", "*/")],
    "C#": [("/*", "*/")],
    "CSS": [("/*", "*/")],
    "Go": [("/*", "*/")],
    "HTML": [("<!--", "-->")],
    "Java": [("/*", "*/")],
    "JavaScript": [("/*", "*/")],
    "PHP": [("/*", "*/")],
    "Rust": [("/*", "*/")],
    "SCSS": [("/*", "*/")],
    "TypeScript": [("/*", "*/")],
    "Vue": [("/*", "*/"), ("<!--", "-->")],
}

LANG_COLORS = {
    "Astro": "#ff5d01",
    "CSS": "#663399",
    "Dockerfile": "#384d54",
    "HCL": "#844fba",
    "HTML": "#e34c26",
    "Java": "#b07219",
    "JavaScript": "#f1e05a",
    "Jupyter Notebook": "#da5b0b",
    "Other": "#94a3b8",
    "PowerShell": "#012456",
    "Python": "#3572a5",
    "SCSS": "#c6538c",
    "Shell": "#89e051",
    "SQL": "#336790",
    "TypeScript": "#3178c6",
}


@dataclass(frozen=True)
class Repository:
    name: str
    private: bool
    default_branch: str


@dataclass(frozen=True)
class CommitStat:
    repo: str
    private: bool
    sha: str
    date: datetime
    additions: int
    deletions: int
    files: int

    @property
    def total(self) -> int:
        return self.additions + self.deletions


@dataclass(frozen=True)
class MonthMetric:
    label: str
    month: str
    days: int
    commits: int
    additions: int
    deletions: int

    @property
    def changed(self) -> int:
        return self.additions + self.deletions

    @property
    def commits_per_day(self) -> float:
        return round(self.commits / self.days, 2) if self.days else 0.0

    @property
    def lines_per_day(self) -> int:
        return round(self.changed / self.days) if self.days else 0


@dataclass(frozen=True)
class LanguageMetric:
    name: str
    loc: int
    percent: float
    files: int


@dataclass(frozen=True)
class LocMetrics:
    repos_scanned: int
    total_loc: int
    languages: list[LanguageMetric]


@dataclass(frozen=True)
class MetricsCard:
    owner: str
    period_label: str
    updated_label: str
    repo_count: int
    public_repos: int
    private_repos: int
    total_commits: int
    active_days: int
    avg_commits_per_day: float
    avg_lines_per_day: int
    total_additions: int
    total_deletions: int
    total_changed: int
    source_loc: int
    monthly: list[MonthMetric]
    languages: list[LanguageMetric]


class GitHubClient:
    def __init__(self, token: str, api_url: str = GITHUB_API) -> None:
        if not token:
            raise ValueError("A GitHub token is required. Set METRICS_TOKEN or GITHUB_TOKEN.")
        self.api_url = api_url.rstrip("/")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "code-metrics-svg-generator",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def request_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers=self.headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def request_bytes(self, path: str) -> bytes:
        req = urllib.request.Request(self._url(path), headers=self.headers)
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.read()

    def paginated_json(self, path: str) -> Iterable[Any]:
        url = self._url(path)
        while url:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                items = json.loads(response.read().decode("utf-8"))
                yield from items
                url = parse_next_link(response.headers.get("Link", ""))

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.api_url}/{path.lstrip('/')}"


def parse_next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">")
        if start != -1 and end != -1 and end > start:
            return section[start + 1 : end]
    return None


def first_day_months_ago(today: date, months: int) -> date:
    month_index = today.year * 12 + today.month - (months - 1)
    year = (month_index - 1) // 12
    month = ((month_index - 1) % 12) + 1
    return date(year, month, 1)


def month_starts(start: date, end: date) -> list[date]:
    months = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def add_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def days_in_period_month(month_start: date, start: date, end: date) -> int:
    next_month = add_month(month_start)
    month_end = next_month - timedelta(days=1)
    window_start = max(month_start, start)
    window_end = min(month_end, end)
    if window_end < window_start:
        return 0
    return (window_end - window_start).days + 1


def build_monthly_series(commits: list[CommitStat], start: date, end: date) -> list[MonthMetric]:
    metrics = []
    for month_start in month_starts(start, end):
        month_end = add_month(month_start)
        month_commits = [
            commit
            for commit in commits
            if month_start <= commit.date.date() < month_end
        ]
        metrics.append(
            MonthMetric(
                label=month_start.strftime("%b"),
                month=month_start.strftime("%Y-%m"),
                days=days_in_period_month(month_start, start, end),
                commits=len(month_commits),
                additions=sum(commit.additions for commit in month_commits),
                deletions=sum(commit.deletions for commit in month_commits),
            )
        )
    return metrics


def format_compact(value: float | int) -> str:
    numeric = float(value)
    sign = "-" if numeric < 0 else ""
    numeric = abs(numeric)
    if numeric >= 1_000_000:
        return f"{sign}{numeric / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if numeric >= 1_000:
        return f"{sign}{numeric / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    if numeric.is_integer():
        return f"{sign}{int(numeric)}"
    return f"{sign}{numeric:.1f}".rstrip("0").rstrip(".")


def fetch_repositories(client: GitHubClient, owner: str) -> list[Repository]:
    query = """
    query($login:String!, $cursor:String) {
      user(login:$login) {
        repositories(first:100, after:$cursor, ownerAffiliations:OWNER, orderBy:{field:UPDATED_AT, direction:DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            name
            isFork
            isPrivate
            defaultBranchRef { name }
          }
        }
      }
    }
    """
    repositories: list[Repository] = []
    cursor = None
    while True:
        payload = {"query": query, "variables": {"login": owner, "cursor": cursor}}
        result = client.request_json("POST", "/graphql", payload)
        page = result["data"]["user"]["repositories"]
        for node in page["nodes"]:
            branch = node.get("defaultBranchRef")
            if node["isFork"] or not branch:
                continue
            repositories.append(
                Repository(
                    name=node["name"],
                    private=bool(node["isPrivate"]),
                    default_branch=branch["name"],
                )
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return repositories


def fetch_commit_stats(
    client: GitHubClient,
    owner: str,
    repositories: list[Repository],
    since: datetime,
) -> list[CommitStat]:
    stats: list[CommitStat] = []
    since_text = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    user_query = "query($login:String!) { user(login:$login) { id } }"
    user_result = client.request_json("POST", "/graphql", {"query": user_query, "variables": {"login": owner}})
    user_data = user_result.get("data", {}).get("user")
    if not user_data:
        return []
    author_id = user_data["id"]

    query = """
    query($owner:String!, $repo:String!, $since:GitTimestamp!, $authorId:ID!, $cursor:String) {
      repository(owner:$owner, name:$repo) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(since:$since, author:{id:$authorId}, first:100, after:$cursor) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  oid
                  authoredDate
                  additions
                  deletions
                  changedFilesIfAvailable
                }
              }
            }
          }
        }
      }
    }
    """

    for repo in repositories:
        cursor = None
        while True:
            payload = {
                "query": query,
                "variables": {
                    "owner": owner,
                    "repo": repo.name,
                    "since": since_text,
                    "authorId": author_id,
                    "cursor": cursor
                }
            }
            result = client.request_json("POST", "/graphql", payload)
            repo_node = result.get("data", {}).get("repository")
            if not repo_node or not repo_node.get("defaultBranchRef"):
                break

            history = repo_node["defaultBranchRef"]["target"].get("history")
            if not history:
                break

            for node in history.get("nodes") or []:
                commit_date = datetime.fromisoformat(node["authoredDate"].replace("Z", "+00:00"))
                stats.append(
                    CommitStat(
                        repo=repo.name,
                        private=repo.private,
                        sha=node["oid"],
                        date=commit_date,
                        additions=node.get("additions") or 0,
                        deletions=node.get("deletions") or 0,
                        files=node.get("changedFilesIfAvailable") or 0,
                    )
                )

            if not history.get("pageInfo", {}).get("hasNextPage"):
                break
            cursor = history["pageInfo"]["endCursor"]

    return stats


def language_for(path: PurePosixPath | Path) -> str | None:
    name = path.name.lower()
    if name == "dockerfile":
        return "Dockerfile"
    return LANG_BY_SUFFIX.get(path.suffix.lower())


def strip_block_comments(line: str, state: dict[str, str | None], lang: str) -> str:
    pairs = BLOCK_COMMENT.get(lang, [])
    if not pairs:
        return line
    text = line
    output = ""
    while text:
        if state.get("end"):
            end = text.find(state["end"] or "")
            if end == -1:
                return output
            text = text[end + len(state["end"] or "") :]
            state["end"] = None
            continue
        starts = [(text.find(start), start, end) for start, end in pairs if text.find(start) != -1]
        if not starts:
            output += text
            break
        pos, start_token, end_token = min(starts, key=lambda item: item[0])
        output += text[:pos]
        rest = text[pos + len(start_token) :]
        end_pos = rest.find(end_token)
        if end_pos == -1:
            state["end"] = end_token
            break
        text = rest[end_pos + len(end_token) :]
    return output


def is_code_line(line: str, state: dict[str, str | None], lang: str) -> bool:
    stripped = strip_block_comments(line, state, lang).strip()
    if not stripped:
        return False
    return not any(stripped.startswith(token) for token in LINE_COMMENT.get(lang, []))


def count_text_lines(text: str, lang: str) -> int:
    state: dict[str, str | None] = {"end": None}
    return sum(1 for line in text.splitlines() if is_code_line(line, state, lang))


def count_notebook_source(source: Any) -> int:
    if isinstance(source, str):
        lines = source.splitlines()
    else:
        lines = [str(line).rstrip("\n") for line in source or []]
    state: dict[str, str | None] = {"end": None}
    return sum(1 for line in lines if is_code_line(line, state, "Jupyter Notebook"))


def count_notebook_lines(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    return count_notebook_data(data)


def count_notebook_data(data: dict[str, Any]) -> int:
    count = 0
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        count += count_notebook_source(cell.get("source", []))
    return count


def should_skip(path: PurePosixPath | Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def count_source_loc(paths: Iterable[Path]) -> LocMetrics:
    totals: dict[str, int] = {}
    files: dict[str, int] = {}
    repos_scanned = 0
    for root in paths:
        if not root.exists():
            continue
        repos_scanned += 1
        for path in root.rglob("*"):
            if not path.is_file() or should_skip(path):
                continue
            lang = language_for(path)
            if not lang:
                continue
            if lang == "Jupyter Notebook":
                loc = count_notebook_lines(path)
            else:
                loc = count_text_lines(path.read_text(encoding="utf-8", errors="ignore"), lang)
            if loc <= 0:
                continue
            totals[lang] = totals.get(lang, 0) + loc
            files[lang] = files.get(lang, 0) + 1
    return loc_metrics_from_totals(totals, files, repos_scanned)


def count_source_loc_from_archives(
    client: GitHubClient,
    owner: str,
    repositories: list[Repository],
) -> LocMetrics:
    totals: dict[str, int] = {}
    files: dict[str, int] = {}
    repos_scanned = 0
    for repo in repositories:
        archive = client.request_bytes(f"/repos/{owner}/{repo.name}/zipball/{repo.default_branch}")
        repos_scanned += 1
        with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
            for member in zip_file.infolist():
                if member.is_dir():
                    continue
                path = PurePosixPath(member.filename)
                relative_parts = path.parts[1:] if len(path.parts) > 1 else path.parts
                relative = PurePosixPath(*relative_parts)
                if should_skip(relative):
                    continue
                lang = language_for(relative)
                if not lang:
                    continue
                raw = zip_file.read(member)
                if lang == "Jupyter Notebook":
                    try:
                        data = json.loads(raw.decode("utf-8", errors="ignore"))
                    except json.JSONDecodeError:
                        continue
                    loc = count_notebook_data(data)
                else:
                    loc = count_text_lines(raw.decode("utf-8", errors="ignore"), lang)
                if loc <= 0:
                    continue
                totals[lang] = totals.get(lang, 0) + loc
                files[lang] = files.get(lang, 0) + 1
    return loc_metrics_from_totals(totals, files, repos_scanned)


def loc_metrics_from_totals(totals: dict[str, int], files: dict[str, int], repos_scanned: int) -> LocMetrics:
    total_loc = sum(totals.values())
    languages = [
        LanguageMetric(
            name=name,
            loc=loc,
            percent=round((loc / total_loc) * 100, 1) if total_loc else 0.0,
            files=files.get(name, 0),
        )
        for name, loc in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]
    return LocMetrics(repos_scanned=repos_scanned, total_loc=total_loc, languages=languages)


def grouped_languages(loc: LocMetrics, count: int = 5) -> list[LanguageMetric]:
    top = loc.languages[:count]
    other_loc = loc.total_loc - sum(lang.loc for lang in top)
    other_files = sum(lang.files for lang in loc.languages[count:])
    result = list(top)
    if other_loc > 0:
        result.append(
            LanguageMetric(
                name="Other",
                loc=other_loc,
                percent=round((other_loc / loc.total_loc) * 100, 1) if loc.total_loc else 0.0,
                files=other_files,
            )
        )
    return result


def build_card(
    owner: str,
    repositories: list[Repository],
    commit_stats: list[CommitStat],
    loc_metrics: LocMetrics,
    today: date,
    months: int,
) -> MetricsCard:
    start = first_day_months_ago(today, months)
    monthly = build_monthly_series(commit_stats, start=start, end=today)
    total_days = (today - start).days + 1
    total_additions = sum(commit.additions for commit in commit_stats)
    total_deletions = sum(commit.deletions for commit in commit_stats)
    total_changed = total_additions + total_deletions
    active_days = len({commit.date.date().isoformat() for commit in commit_stats})
    return MetricsCard(
        owner=owner,
        period_label=f"{start.strftime('%b %Y')}-{today.strftime('%b %Y')}",
        updated_label=today.strftime("%b %-d, %Y") if os.name != "nt" else today.strftime("%b %#d, %Y"),
        repo_count=len(repositories),
        public_repos=sum(1 for repo in repositories if not repo.private),
        private_repos=sum(1 for repo in repositories if repo.private),
        total_commits=len(commit_stats),
        active_days=active_days,
        avg_commits_per_day=round(len(commit_stats) / total_days, 2) if total_days else 0.0,
        avg_lines_per_day=round(total_changed / total_days) if total_days else 0,
        total_additions=total_additions,
        total_deletions=total_deletions,
        total_changed=total_changed,
        source_loc=loc_metrics.total_loc,
        monthly=monthly,
        languages=grouped_languages(loc_metrics),
    )


def line_path(values: list[float], x: float, y: float, width: float, height: float) -> tuple[str, str, float]:
    max_value = max(values) if values else 1
    max_value = max(max_value, 1)
    points = []
    for index, value in enumerate(values):
        px = x + (width / max(1, len(values) - 1)) * index
        py = y + height - (value / max_value) * height
        points.append((round(px, 1), round(py, 1)))
    line = " ".join(("M" if index == 0 else "L") + f" {px} {py}" for index, (px, py) in enumerate(points))
    first_x, _ = points[0]
    last_x, last_y = points[-1]
    area = f"{line} L {last_x} {y + height} L {first_x} {y + height} Z"
    return line, area, max_value


def render_svg(card: MetricsCard) -> str:
    commit_values = [month.commits_per_day for month in card.monthly]
    line_values = [month.lines_per_day for month in card.monthly]
    commit_line, commit_area, commit_max = line_path(commit_values, 74, 298, 340, 86)
    changed_line, changed_area, changed_max = line_path(line_values, 506, 298, 340, 86)
    best_commit = max(card.monthly, key=lambda month: month.commits_per_day) if card.monthly else None
    best_changed = max(card.monthly, key=lambda month: month.lines_per_day) if card.monthly else None
    latest = card.monthly[-1] if card.monthly else MonthMetric("", "", 1, 0, 0, 0)

    commit_ticks = chart_ticks(card.monthly, 74)
    changed_ticks = chart_ticks(card.monthly, 506)
    language_bar, language_legend = render_language_mix(card.languages)
    net_lines = card.total_additions - card.total_deletions
    net_sign = "+" if net_lines >= 0 else "-"
    best_text = ""
    if best_commit and best_changed:
        best_text = f"Best months: {escape(best_commit.month)} commits, {escape(best_changed.month)} line changes"

    return f"""<svg width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Private-inclusive GitHub code velocity metrics for {escape(card.owner)}</title>
  <desc id="desc">{card.total_commits} authored commits, {format_compact(card.total_changed)} lines changed, {card.avg_commits_per_day} commits per day, {format_compact(card.avg_lines_per_day)} lines changed per day, and language percentages by source lines of code.</desc>
  <defs>
    <linearGradient id="card" x1="0" y1="0" x2="920" y2="640" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#08111f"/><stop offset="0.55" stop-color="#101827"/><stop offset="1" stop-color="#16111f"/>
    </linearGradient>
    <linearGradient id="accent" x1="44" y1="40" x2="876" y2="40" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2dd4bf"/><stop offset="0.5" stop-color="#58a6ff"/><stop offset="1" stop-color="#f97316"/>
    </linearGradient>
    <linearGradient id="commitFill" x1="0" y1="290" x2="0" y2="392" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#58a6ff" stop-opacity="0.38"/><stop offset="1" stop-color="#58a6ff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="lineFill" x1="0" y1="290" x2="0" y2="392" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#f97316" stop-opacity="0.42"/><stop offset="1" stop-color="#f97316" stop-opacity="0"/>
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="0" dy="16" stdDeviation="20" flood-color="#020617" flood-opacity="0.48"/></filter>
    <clipPath id="langClip"><rect x="54" y="504" width="812" height="14" rx="7"/></clipPath>
    <style>
      .title {{ font: 800 28px Segoe UI, Inter, Arial, sans-serif; fill: #f8fafc; }}
      .sub {{ font: 500 13px Segoe UI, Inter, Arial, sans-serif; fill: #9fb0c3; }}
      .stat {{ font: 800 28px Segoe UI, Inter, Arial, sans-serif; fill: #f8fafc; }}
      .label {{ font: 700 11px Segoe UI, Inter, Arial, sans-serif; fill: #9fb0c3; letter-spacing: .04em; }}
      .panelTitle {{ font: 800 15px Segoe UI, Inter, Arial, sans-serif; fill: #e5edf7; }}
      .axis {{ font: 600 10px Segoe UI, Inter, Arial, sans-serif; fill: #64748b; }}
      .legend {{ font: 650 12px Segoe UI, Inter, Arial, sans-serif; fill: #d6e2ef; }}
      .legendPct {{ font: 800 12px Segoe UI, Inter, Arial, sans-serif; fill: #f8fafc; text-anchor: end; }}
      .note {{ font: 700 12px Segoe UI, Inter, Arial, sans-serif; fill: #7dd3fc; }}
      .muted {{ font: 650 12px Segoe UI, Inter, Arial, sans-serif; fill: #94a3b8; }}
    </style>
  </defs>
  <rect x="16" y="16" width="888" height="608" rx="22" fill="url(#card)" stroke="#303c4d" filter="url(#shadow)"/>
  <rect x="44" y="40" width="832" height="4" rx="2" fill="url(#accent)"/>
  <text x="54" y="80" class="title">Code velocity</text>
  <text x="54" y="103" class="sub">Private-inclusive GitHub API snapshot - {escape(card.period_label)} - language mix by source LOC</text>
  <text x="852" y="80" class="note" text-anchor="end">Updated {escape(card.updated_label)}</text>

  {stat_box(54, card.total_commits, "COMMITS")}
  {stat_box(260, card.avg_commits_per_day, "COMMITS / DAY")}
  {stat_box(466, format_compact(card.avg_lines_per_day), "LINES CHANGED / DAY")}
  {stat_box(672, card.active_days, "ACTIVE DAYS", width=194)}

  <text x="54" y="232" class="muted">Repos: {card.repo_count} original ({card.public_repos} public / {card.private_repos} private)</text>
  <text x="314" y="232" class="muted">Source LOC: {format_compact(card.source_loc)}</text>
  <text x="484" y="232" class="muted">Added: +{format_compact(card.total_additions)}</text>
  <text x="640" y="232" class="muted">Deleted: -{format_compact(card.total_deletions)}</text>
  <text x="790" y="232" class="muted">Net: {net_sign}{format_compact(abs(net_lines))}</text>

  <g>
    <rect x="54" y="256" width="390" height="172" rx="16" fill="#0f1724" stroke="#253246"/>
    <text x="74" y="282" class="panelTitle">Commits/day monthly average</text>
    <text x="414" y="282" class="note" text-anchor="end">now {latest.commits_per_day:g}</text>
    {chart_grid(74, 414)}
    <path d="{commit_area}" fill="url(#commitFill)"/>
    <path d="{commit_line}" stroke="#58a6ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <text x="74" y="397" class="axis">0</text><text x="414" y="397" class="axis" text-anchor="end">peak {commit_max:g}</text>
    {commit_ticks}
  </g>

  <g>
    <rect x="486" y="256" width="390" height="172" rx="16" fill="#0f1724" stroke="#253246"/>
    <text x="506" y="282" class="panelTitle">Lines changed/day monthly average</text>
    <text x="846" y="282" class="note" text-anchor="end">now {format_compact(latest.lines_per_day)}</text>
    {chart_grid(506, 846)}
    <path d="{changed_area}" fill="url(#lineFill)"/>
    <path d="{changed_line}" stroke="#f97316" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <text x="506" y="397" class="axis">0</text><text x="846" y="397" class="axis" text-anchor="end">peak {format_compact(changed_max)}</text>
    {changed_ticks}
  </g>

  <text x="54" y="472" class="label">SOURCE LOC MIX</text>
  <text x="866" y="472" class="muted" text-anchor="end">{best_text}</text>
  <g clip-path="url(#langClip)"><rect x="54" y="504" width="812" height="14" fill="#212b3a"/>{language_bar}</g>
  <rect x="54" y="504" width="812" height="14" rx="7" stroke="#303c4d"/>
  {language_legend}
</svg>
"""


def stat_box(x: int, value: Any, label: str, width: int = 190) -> str:
    return f"""<g>
    <rect x="{x}" y="128" width="{width}" height="74" rx="14" fill="#151c28" stroke="#2a3544"/>
    <text x="{x + 20}" y="161" class="stat">{escape(str(value))}</text><text x="{x + 20}" y="184" class="label">{escape(label)}</text>
  </g>"""


def chart_grid(start_x: int, end_x: int) -> str:
    return (
        f'<line x1="{start_x}" y1="298" x2="{end_x}" y2="298" stroke="#263244"/>'
        f'<line x1="{start_x}" y1="341" x2="{end_x}" y2="341" stroke="#263244"/>'
        f'<line x1="{start_x}" y1="384" x2="{end_x}" y2="384" stroke="#263244"/>'
    )


def chart_ticks(monthly: list[MonthMetric], start_x: int) -> str:
    ticks = []
    for index, month in enumerate(monthly):
        if index % 2 != 0 and index != len(monthly) - 1:
            continue
        x = round(start_x + (340 / max(1, len(monthly) - 1)) * index, 1)
        ticks.append(f'<text x="{x}" y="410" class="axis" text-anchor="middle">{escape(month.label)}</text>')
    return "\n    ".join(ticks)


def render_language_mix(languages: list[LanguageMetric]) -> tuple[str, str]:
    bar_x = 54
    bar_y = 504
    bar_width = 812
    cursor = bar_x
    segments = []
    legend = []
    fallback = ["#58a6ff", "#ff7b72", "#a5d6ff", "#d2a8ff", "#7ee787", "#f2cc60"]
    for index, language in enumerate(languages):
        color = LANG_COLORS.get(language.name, fallback[index % len(fallback)])
        if index == len(languages) - 1:
            width = (bar_x + bar_width) - cursor
        else:
            width = max(3, round(bar_width * language.percent / 100, 1))
        segments.append(f'<rect x="{cursor}" y="{bar_y}" width="{width}" height="14" fill="{color}"/>')
        cursor += width
        x = 62 + (index % 3) * 270
        y = 548 + math.floor(index / 3) * 24
        legend.append(
            f'<circle cx="{x}" cy="{y - 5}" r="5.5" fill="{color}"/>'
            f'<text x="{x + 14}" y="{y}" class="legend">{escape(language.name)}</text>'
            f'<text x="{x + 190}" y="{y}" class="legendPct">{language.percent:g}%</text>'
        )
    return "\n    ".join(segments), "\n  ".join(legend)


def write_svg(path: Path, svg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def load_fixture(path: Path) -> tuple[list[Repository], list[CommitStat], LocMetrics]:
    data = json.loads(path.read_text(encoding="utf-8"))
    repositories = [
        Repository(
            name=item["name"],
            private=bool(item.get("private")),
            default_branch=item.get("default_branch", "main"),
        )
        for item in data.get("repositories", [])
    ]
    commits = [
        CommitStat(
            repo=item.get("repo", "fixture"),
            private=bool(item.get("private")),
            sha=item.get("sha", ""),
            date=datetime.fromisoformat(item["date"].replace("Z", "+00:00")),
            additions=int(item.get("additions", 0)),
            deletions=int(item.get("deletions", 0)),
            files=int(item.get("files", 0)),
        )
        for item in data.get("commits", [])
    ]
    totals = {item["language"]: int(item["loc"]) for item in data.get("languages", [])}
    files = {item["language"]: int(item.get("files", 0)) for item in data.get("languages", [])}
    return repositories, commits, loc_metrics_from_totals(totals, files, len(repositories))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a GitHub code velocity SVG.")
    parser.add_argument("--user", default=os.getenv("GITHUB_REPOSITORY_OWNER"), help="GitHub username or org.")
    parser.add_argument("--output", default="assets/code-metrics.svg", help="SVG output path.")
    parser.add_argument("--months", type=int, default=12, help="Number of months to include.")
    parser.add_argument("--token-env", default="METRICS_TOKEN", help="Primary token environment variable.")
    parser.add_argument("--fixture", type=Path, help="Use fixture JSON instead of calling GitHub.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    owner = args.user
    if not owner:
        print("error: --user is required when GITHUB_REPOSITORY_OWNER is not set", file=sys.stderr)
        return 2
    today = datetime.now(UTC).date()
    since = datetime.combine(first_day_months_ago(today, args.months), datetime.min.time(), tzinfo=UTC)

    if args.fixture:
        repositories, commits, loc = load_fixture(args.fixture)
    else:
        token = os.getenv(args.token_env) or os.getenv("GITHUB_TOKEN")
        client = GitHubClient(token or "")
        repositories = fetch_repositories(client, owner)
        commits = fetch_commit_stats(client, owner, repositories, since)
        loc = count_source_loc_from_archives(client, owner, repositories)

    card = build_card(owner, repositories, commits, loc, today=today, months=args.months)
    write_svg(Path(args.output), render_svg(card))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
