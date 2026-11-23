#!/usr/bin/env python3
"""Refresh the animated foxtrot console from GitHub's public APIs."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

if __package__:
    from .render_terminal import write_terminal_gif
else:
    from render_terminal import write_terminal_gif


API = "https://api.github.com"
LOGIN = "RedstoneLord"
TERMINAL = Path(__file__).resolve().parents[1] / "assets" / "terminal.gif"
CONTRIBUTIONS_QUERY = """
query FoxtrotCommits($login: String!, $from: DateTime!, $until: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $until) {
      totalCommitContributions
    }
  }
}
"""


class GitHubError(RuntimeError):
    def __init__(self, message, access_denied=False):
        super().__init__(message)
        self.access_denied = access_denied


def request_json(path, *, token=None, params=None, payload=None):
    query = "?" + urlencode(params) if params else ""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "foxtrot-profile-stats"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if path != "/graphql":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(API + path + query, data=body, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        denied = error.code in (401, 403) and error.headers.get("X-RateLimit-Remaining") != "0"
        raise GitHubError(f"{path} returned HTTP {error.code}", denied) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GitHubError(f"{path} did not return a usable response") from error


class GitHub:
    def __init__(self, token, contribution_token):
        self.token = token
        self.contribution_token = contribution_token

    def public_rest(self, path, params=None):
        try:
            return request_json(path, token=self.token, params=params)
        except GitHubError as error:
            if not self.token or not error.access_denied:
                raise
            self.token = None
            return request_json(path, params=params)

    def public_repositories(self, login):
        page = 1
        while True:
            repos = self.public_rest(f"/users/{login}/repos", {
                "type": "owner", "sort": "full_name", "direction": "asc",
                "per_page": 100, "page": page,
            })
            if not isinstance(repos, list):
                raise GitHubError("GitHub returned an invalid repository list")
            for repo in repos:
                if repo["private"] is False:
                    yield repo
            if len(repos) < 100:
                return
            page += 1

    def commits(self, login, now):
        start = now - timedelta(days=365)
        token = self.contribution_token or self.token
        if token:
            try:
                data = request_json("/graphql", token=token, payload={
                    "query": CONTRIBUTIONS_QUERY,
                    "variables": {"login": login, "from": start.isoformat(), "until": now.isoformat()},
                })
                if not isinstance(data, dict):
                    raise GitHubError("GitHub returned an invalid GraphQL response")
                errors = data.get("errors", [])
                if errors:
                    denied = all(error.get("type") in {"FORBIDDEN", "UNAUTHORIZED"}
                                 or "resource not accessible" in error.get("message", "").lower()
                                 for error in errors)
                    raise GitHubError("GitHub GraphQL could not read commit contributions", denied)
                count = data["data"]["user"]["contributionsCollection"]["totalCommitContributions"]
                return natural_number(count), "contribution graph"
            except GitHubError as error:
                if self.contribution_token or not error.access_denied:
                    raise

        # Anonymous search limits this fallback to public, indexed commits.
        match = request_json("/search/commits", params={
            "q": f"author:{login} author-date:{start.isoformat()}..{now.isoformat()}",
            "per_page": 1,
        })
        if match["incomplete_results"] is not False:
            raise GitHubError("GitHub commit search returned an incomplete count")
        return natural_number(match["total_count"]), "public commit search"


def natural_number(value):
    if type(value) is not int or value < 0:
        raise GitHubError("GitHub returned an invalid count")
    return value


def short_label(value, width):
    label = re.sub(r"[^A-Za-z0-9_./+#() -]", " ", value)
    label = " ".join(label.split())
    return label if len(label) <= width else label[:width - 3].rstrip() + "..."


def activity_rows(events, login):
    actions = {
        "PushEvent": "push", "PullRequestEvent": "PR", "IssuesEvent": "issue",
        "IssueCommentEvent": "comment", "PullRequestReviewEvent": "review",
        "PullRequestReviewCommentEvent": "comment", "CreateEvent": "create",
        "DeleteEvent": "delete", "WatchEvent": "star", "ForkEvent": "fork",
        "ReleaseEvent": "release", "PublicEvent": "opened",
    }
    rows = []
    for event in sorted(events, key=lambda item: item["created_at"], reverse=True):
        if (event.get("actor") or {}).get("login", login).casefold() != login.casefold():
            continue
        day = datetime.fromisoformat(event["created_at"]).date().isoformat()
        repo = (event.get("repo") or {}).get("name", "")
        owner, slash, name = repo.partition("/")
        if slash and owner.casefold() == login.casefold():
            repo = name
        action = actions.get(event["type"], "activity")
        rows.append(f"{day}  {action:<8} {short_label(repo, 20)}".rstrip())
        if len(rows) == 3:
            break
    return rows


def collect_console(api, login, now):
    commits, source = api.commits(login, now)
    stars = 0
    languages = Counter()
    for repo in api.public_repositories(login):
        stars += natural_number(repo["stargazers_count"])
        if repo["fork"]:
            continue
        path = "/".join(quote(part, safe="") for part in repo["full_name"].split("/"))
        sizes = api.public_rest(f"/repos/{path}/languages")
        if not isinstance(sizes, dict):
            raise GitHubError("GitHub returned an invalid language response")
        languages.update({name: natural_number(size) for name, size in sizes.items()})
    events = api.public_rest(f"/users/{login}/events/public", {"per_page": 30})
    if not isinstance(events, list):
        raise GitHubError("GitHub returned an invalid public activity response")

    total_bytes = sum(languages.values())
    ranked = sorted(languages.items(), key=lambda item: (-item[1], item[0].casefold()))
    labels = [f"{short_label(name, 15)} {size / total_bytes:.1%}"
              for name, size in ranked[:4] if size and total_bytes]
    language_rows = [f"{labels[index]:<26} {labels[index+1] if index+1 < len(labels) else ''}".rstrip()
                     for index in range(0, len(labels), 2)]
    return [
        ("heading", f"[github] {short_label(login, 32)}  {now.date().isoformat()} UTC"),
        ("reply", f"Commits (365d) {commits:,}   Stars earned {stars:,}"),
        ("muted", f"Source: {source}"),
        ("heading", "Top languages by bytes"),
        *(("reply", row) for row in language_rows or ["No language data"]),
        ("heading", "Recent public activity"),
        *(("reply", row) for row in activity_rows(events, login) or ["No recent public activity"]),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=LOGIN, help="GitHub username")
    parser.add_argument("--output", type=Path, default=TERMINAL, help="Destination terminal GIF")
    parser.add_argument("--dry-run", action="store_true", help="Print the refreshed stats")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", args.user):
        parser.error("--user must be a GitHub username")

    try:
        api = GitHub(os.getenv("GITHUB_TOKEN"), os.getenv("PROFILE_STATS_TOKEN"))
        now = datetime.now(UTC).replace(microsecond=0)
        console = collect_console(api, args.user, now)
        if args.dry_run:
            print("\n".join(line for _, line in console))
        elif write_terminal_gif(args.output, console):
            print("Updated the foxtrot terminal GIF.")
        else:
            print("The foxtrot terminal GIF is up to date.")
    except (GitHubError, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Stats refresh failed. The existing terminal GIF was kept. {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
