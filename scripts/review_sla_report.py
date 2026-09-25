#!/usr/bin/env python3
"""Measure pull-request review latency and cross-author review activity.

Reproduces the "Observed" column of the Review Service Levels section and the
cross-author review counts used for code-owner eligibility in
.github/GOVERNANCE.md. Reads public pull-request metadata through `gh api
graphql`; nothing is written.

Business time counts wall-clock hours on Monday to Friday in UTC+8. Public
holidays are not modelled, so the figures are slightly pessimistic around them.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BOT_PATTERN = re.compile(r"(\[bot\]$|^dependabot|^copilot|^github-actions|^sonarqubecloud$)", re.I)
UTC8 = timezone(timedelta(hours=8))
BUSINESS_DAY_HOURS = 24.0

QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 40, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number state createdAt mergedAt isDraft
        author { login }
        mergedBy { login }
        files(first: 100) { nodes { path } }
        reviews(first: 30) { nodes { author { login } submittedAt } }
        comments(first: 30) { nodes { author { login } createdAt } }
      }
    }
  }
}
"""


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _login(node: dict[str, Any] | None) -> str | None:
    return (node or {}).get("login")


def is_human(login: str | None) -> bool:
    return bool(login) and not BOT_PATTERN.search(login or "")


def business_hours(start: datetime, end: datetime) -> float:
    """Wall-clock hours between two instants that fall on UTC+8 weekdays."""
    cur, stop = start.astimezone(UTC8), end.astimezone(UTC8)
    hours = 0.0
    while cur < stop:
        midnight = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        nxt = min(stop, midnight)
        if cur.weekday() < 5:
            hours += (nxt - cur).total_seconds() / 3600
        cur = nxt
    return hours


def first_response(pr: dict[str, Any]) -> datetime | None:
    """Earliest review, comment or merge by a human other than the author."""
    author = _login(pr.get("author"))
    events = [
        _ts(node["submittedAt"])
        for node in pr["reviews"]["nodes"]
        if node.get("submittedAt") and is_human(_login(node.get("author")))
        and _login(node.get("author")) != author
    ]
    events += [
        _ts(node["createdAt"])
        for node in pr["comments"]["nodes"]
        if is_human(_login(node.get("author"))) and _login(node.get("author")) != author
    ]
    merger = _login(pr.get("mergedBy"))
    if pr.get("mergedAt") and is_human(merger) and merger != author:
        events.append(_ts(pr["mergedAt"]))
    return min(events) if events else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def latency_summary(prs: Iterable[dict[str, Any]], *, exclude_authors: set[str]) -> dict[str, Any]:
    rows = [
        pr for pr in prs
        if not pr.get("isDraft")
        and is_human(_login(pr.get("author")))
        and _login(pr.get("author")) not in exclude_authors
    ]
    response, merge = [], []
    for pr in rows:
        opened = _ts(pr["createdAt"])
        responded = first_response(pr)
        if responded:
            response.append(business_hours(opened, responded))
        if pr.get("mergedAt"):
            merge.append(business_hours(opened, _ts(pr["mergedAt"])))
    two_days = 2 * BUSINESS_DAY_HOURS
    return {
        "pull_requests": len(rows),
        "without_response": len(rows) - len(response),
        "first_response_within_2_business_days": (
            sum(1 for h in response if h <= two_days) / len(rows) if rows else None
        ),
        "first_response_hours": {f"p{int(q * 100)}": percentile(response, q) for q in (0.5, 0.75, 0.9)},
        "merge_hours": {f"p{int(q * 100)}": percentile(merge, q) for q in (0.5, 0.9)},
    }


def cross_author_reviews(prs: Iterable[dict[str, Any]], *, path_prefixes: tuple[str, ...] = ()) -> Counter[str]:
    """Distinct pull requests each human reviewed or commented on as a non-author."""
    counts: Counter[str] = Counter()
    for pr in prs:
        if path_prefixes and not any(
            node["path"].startswith(path_prefixes) for node in pr["files"]["nodes"]
        ):
            continue
        author = _login(pr.get("author"))
        reviewers = {
            _login(node.get("author"))
            for node in pr["reviews"]["nodes"] + pr["comments"]["nodes"]
        }
        counts.update(r for r in reviewers if is_human(r) and r != author)
    return counts


def fetch(repo: str, since: str) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    cursor, out = None, []
    while True:
        args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"name={name}"]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        page = json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)
        data = page["data"]["repository"]["pullRequests"]
        for pr in data["nodes"]:
            if pr["createdAt"][:10] < since:
                return out
            out.append(pr)
        if not data["pageInfo"]["hasNextPage"]:
            return out
        cursor = data["pageInfo"]["endCursor"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="loopx-project/loopx")
    parser.add_argument("--since", required=True, help="Count pull requests opened on or after this date (YYYY-MM-DD).")
    parser.add_argument("--exclude-author", action="append", default=["huangruiteng"],
                        help="Author whose own pull requests are not contributor PRs (repeatable).")
    parser.add_argument("--path", action="append", default=[],
                        help="Limit cross-author review counts to PRs touching this path prefix (repeatable).")
    parser.add_argument("--input", help="Read pull requests from a JSON Lines file instead of the API.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    if not REPO_PATTERN.match(args.repo):
        parser.error("--repo must look like owner/name")

    if args.input:
        with open(args.input, encoding="utf-8") as handle:
            prs = [json.loads(line) for line in handle if line.strip()]
        prs = [pr for pr in prs if pr["createdAt"][:10] >= args.since]
    else:
        prs = fetch(args.repo, args.since)
    report = {
        "repo": args.repo,
        "since": args.since,
        "contributor_latency": latency_summary(prs, exclude_authors=set(args.exclude_author)),
        "cross_author_reviews": dict(cross_author_reviews(prs, path_prefixes=tuple(args.path)).most_common(20)),
    }
    if args.format == "json":
        json.dump(report, sys.stdout, indent=2)
        print()
        return 0
    lat = report["contributor_latency"]
    share = lat["first_response_within_2_business_days"]
    print(f"{args.repo} pull requests opened since {args.since}")
    print(f"contributor PRs: {lat['pull_requests']} (no non-author response: {lat['without_response']})")
    print(f"first response within 2 business days: {share:.0%}" if share is not None else "no contributor PRs")
    fmt = lambda d: ", ".join(f"{k}={v:.1f}h" for k, v in d.items() if v is not None)
    print(f"first response (business hours): {fmt(lat['first_response_hours'])}")
    print(f"merge from opening (business hours): {fmt(lat['merge_hours'])}")
    scope = f" touching {', '.join(args.path)}" if args.path else ""
    print(f"cross-author reviews or comments, distinct PRs{scope}:")
    for login, count in report["cross_author_reviews"].items():
        print(f"  {login}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
