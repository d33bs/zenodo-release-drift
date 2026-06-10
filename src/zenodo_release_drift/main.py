"""
Core logic for zenodo-release-drift.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from github import Auth, Github, GithubException
from packaging.version import InvalidVersion, Version

_TIMEOUT = httpx.Timeout(10.0)


def _github_client() -> Github:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return Github(auth=Auth.Token(token))
    return Github()


def _normalize(version: str) -> str:
    """Strip a leading 'v' from a version string."""
    return version.lstrip("v")


def _parse(version: str) -> Version | None:
    try:
        return Version(_normalize(version))
    except InvalidVersion:
        return None


class GitHubCollector:
    """Collects GitHub releases."""

    def __init__(
        self,
        owner: str,
        repo: str,
        client: Github | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self._client = client

    def get_releases(self) -> list[str]:
        """Return release tag names from GitHub."""
        gh = self._client or _github_client()
        try:
            gh_repo = gh.get_repo(f"{self.owner}/{self.repo}")
            return [r.tag_name for r in gh_repo.get_releases()]
        except GithubException:
            return []


class ZenodoCollector:
    """Collects Zenodo records for a GitHub repository."""

    BASE_URL = "https://zenodo.org/api"

    def __init__(
        self, owner: str, repo: str, client: httpx.Client | None = None
    ) -> None:
        self.owner = owner
        self.repo = repo
        self._client = client
        self._cache: list[str] | None = None

    def _repo_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    def _hit_belongs_to_repo(self, hit: dict[str, Any]) -> bool:
        """Return True if the Zenodo record is linked to this GitHub repo."""
        meta = hit.get("metadata", {})
        repo_url = self._repo_url()
        if (meta.get("custom") or {}).get("code:codeRepository") == repo_url:
            return True
        for ri in meta.get("related_identifiers", []):
            if repo_url in ri.get("identifier", ""):
                return True
        return False

    def get_versions(self) -> list[str]:
        """Return version strings from Zenodo records (cached)."""
        if self._cache is not None:
            return self._cache
        url = f"{self.BASE_URL}/records"
        # Omit https:// — the full URL causes Zenodo 500s on some repo names.
        params = {
            "q": f"related.identifier:github.com/{self.owner}/{self.repo}",
            "all_versions": "true",
        }
        client = self._client or httpx.Client()
        try:
            resp = client.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
            self._cache = [
                v
                for hit in hits
                if self._hit_belongs_to_repo(hit)
                and (v := hit.get("metadata", {}).get("version"))
            ]
            return self._cache
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            self._cache = []
            return self._cache
        finally:
            if self._client is None:
                client.close()


class VersionMatcher:
    """Matches GitHub releases with Zenodo versions."""

    def match(
        self,
        github_releases: list[str],
        zenodo_versions: list[str],
    ) -> dict[str, Any]:
        """Return matching results between two version lists."""
        norm_github = [_normalize(v) for v in github_releases]
        norm_zenodo = {_normalize(v) for v in zenodo_versions}

        missing = [v for v in norm_github if v not in norm_zenodo]

        parsed_github = [p for v in norm_github if (p := _parse(v)) is not None]
        parsed_zenodo = [p for v in norm_zenodo if (p := _parse(v)) is not None]

        latest_github = max(parsed_github) if parsed_github else None
        latest_zenodo = max(parsed_zenodo) if parsed_zenodo else None

        is_behind = bool(
            latest_github and latest_zenodo and latest_github > latest_zenodo
        )

        return {
            "missing_versions": missing,
            "latest_github": str(latest_github) if latest_github else None,
            "latest_zenodo": str(latest_zenodo) if latest_zenodo else None,
            "is_behind": is_behind,
        }


class DriftEngine:
    """Detects release drift between GitHub and Zenodo."""

    def __init__(
        self,
        github_collector: GitHubCollector | None = None,
        zenodo_collector: ZenodoCollector | None = None,
    ) -> None:
        self._github = github_collector
        self._zenodo = zenodo_collector
        self._matcher = VersionMatcher()

    def detect(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Return findings for the given repository."""
        github = self._github or GitHubCollector(owner, repo)
        zenodo = self._zenodo or ZenodoCollector(owner, repo)

        results = self._matcher.match(github.get_releases(), zenodo.get_versions())

        findings: list[dict[str, Any]] = []

        for version in results["missing_versions"]:
            findings.append(
                {
                    "code": "ZRD001",
                    "severity": "high",
                    "message": (
                        f"GitHub release {version} has no matching Zenodo archive."
                    ),
                    "version": version,
                }
            )

        if results["is_behind"]:
            findings.append(
                {
                    "code": "ZRD002",
                    "severity": "high",
                    "message": (
                        f"Latest Zenodo version is {results['latest_zenodo']}"
                        f" while latest GitHub release is"
                        f" {results['latest_github']}."
                    ),
                    "latest_github": results["latest_github"],
                    "latest_zenodo": results["latest_zenodo"],
                }
            )

        return findings


class GitHubUserCollector:
    """Lists repos owned by a GitHub user or org."""

    def __init__(self, username: str, client: Github | None = None) -> None:
        self.username = username
        self._client = client

    def get_repos(self) -> list[str]:
        """Return repo names owned by the user."""
        gh = self._client or _github_client()
        try:
            return [r.name for r in gh.get_user(self.username).get_repos(type="owner")]
        except GithubException as exc:
            status = exc.status if hasattr(exc, "status") else 0
            if status == 401:  # noqa: PLR2004
                raise RuntimeError(
                    f"GitHub API 401 for '{self.username}'. Check your GITHUB_TOKEN."
                ) from exc
            if status == 403:  # noqa: PLR2004
                raise RuntimeError(
                    f"GitHub API 403 for '{self.username}'."
                    " Set GITHUB_TOKEN to avoid rate limits."
                ) from exc
            raise RuntimeError(
                f"GitHub API error for '{self.username}': {exc}"
            ) from exc


class CheckUserResult:
    """Result of check_user, including counts for meaningful CLI output."""

    def __init__(
        self,
        findings: dict[str, list[dict[str, Any]]],
        repos_total: int,
        repos_with_zenodo: int,
    ) -> None:
        self.findings = findings
        self.repos_total = repos_total
        self.repos_with_zenodo = repos_with_zenodo


def check_user(
    username: str,
    github_user_collector: GitHubUserCollector | None = None,
) -> CheckUserResult:
    """Return drift findings for Zenodo-integrated repos owned by a GitHub user."""
    collector = github_user_collector or GitHubUserCollector(username)
    repos = collector.get_repos()
    findings: dict[str, list[dict[str, Any]]] = {}
    repos_with_zenodo = 0
    for repo_name in repos:
        zenodo = ZenodoCollector(username, repo_name)
        if not zenodo.get_versions():
            continue
        repos_with_zenodo += 1
        repo_findings = lint_repo(username, repo_name, zenodo_collector=zenodo)
        if repo_findings:
            findings[f"{username}/{repo_name}"] = repo_findings
    return CheckUserResult(findings, len(repos), repos_with_zenodo)


def explain_finding(finding: dict[str, Any]) -> str:
    """Return a human-readable explanation for a finding."""
    if finding["code"] == "ZRD001":
        return (
            f"GitHub release {finding['version']} exists but no matching"
            " Zenodo archive was found. This may indicate that the"
            " GitHub-Zenodo integration was disabled or failed during"
            " release processing."
        )
    if finding["code"] == "ZRD002":
        return (
            f"The latest Zenodo version ({finding['latest_zenodo']}) is"
            f" behind the latest GitHub release ({finding['latest_github']})."
            " This indicates that the repository has been updated on GitHub"
            " but not yet archived on Zenodo."
        )
    return "Unknown finding type."


def lint_repo(
    owner: str,
    repo: str,
    github_collector: GitHubCollector | None = None,
    zenodo_collector: ZenodoCollector | None = None,
) -> list[dict[str, Any]]:
    """Lint a repository for Zenodo release drift."""
    engine = DriftEngine(github_collector, zenodo_collector)
    return engine.detect(owner, repo)


def lint_repo_explain(
    owner: str,
    repo: str,
    github_collector: GitHubCollector | None = None,
    zenodo_collector: ZenodoCollector | None = None,
) -> str:
    """Lint a repository and return a Markdown explanation report."""
    findings = lint_repo(owner, repo, github_collector, zenodo_collector)

    if not findings:
        return f"# Repository: {owner}/{repo}\n\nNo drift detected."

    lines = [f"# Repository: {owner}/{repo}\n"]
    for finding in findings:
        lines.append(f"## {finding['code']} {finding['severity'].upper()}")
        lines.append(finding["message"])
        lines.append("")
        lines.append(f"> {explain_finding(finding)}")
        lines.append("")

    return "\n".join(lines)
