"""Review SLA report: business-time arithmetic and response attribution."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "review_sla_report.py"
spec = importlib.util.spec_from_file_location("loopx_review_sla_report", SCRIPT_PATH)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def _pr(number, author, created, *, reviews=(), comments=(), merged=None, merged_by=None, files=("loopx/x.py",), draft=False):
    return {
        "number": number,
        "state": "MERGED" if merged else "OPEN",
        "createdAt": created,
        "mergedAt": merged,
        "isDraft": draft,
        "author": {"login": author},
        "mergedBy": {"login": merged_by} if merged_by else None,
        "files": {"nodes": [{"path": path} for path in files]},
        "reviews": {"nodes": [{"author": {"login": who}, "submittedAt": at} for who, at in reviews]},
        "comments": {"nodes": [{"author": {"login": who}, "createdAt": at} for who, at in comments]},
    }


def test_business_hours_skip_the_utc8_weekend():
    # Friday 2026-09-25 22:00 UTC+8 to Monday 2026-09-28 02:00 UTC+8.
    start = report._ts("2026-09-25T14:00:00Z")
    end = report._ts("2026-09-27T18:00:00Z")
    assert report.business_hours(start, end) == 4.0


def test_first_response_ignores_author_and_bots_but_counts_foreign_merge():
    pr = _pr(
        1,
        "alice",
        "2026-09-21T01:00:00Z",
        comments=[("alice", "2026-09-21T01:10:00Z"), ("sonarqubecloud", "2026-09-21T01:20:00Z")],
        merged="2026-09-21T05:00:00Z",
        merged_by="lead",
    )
    assert report.first_response(pr) == report._ts("2026-09-21T05:00:00Z")
    self_merged = _pr(2, "alice", "2026-09-21T01:00:00Z", merged="2026-09-21T02:00:00Z", merged_by="alice")
    assert report.first_response(self_merged) is None


def test_latency_summary_excludes_maintainer_and_draft_prs():
    prs = [
        _pr(1, "alice", "2026-09-21T01:00:00Z", reviews=[("lead", "2026-09-21T03:00:00Z")]),
        _pr(2, "bob", "2026-09-21T01:00:00Z", reviews=[("lead", "2026-09-24T01:00:00Z")]),
        _pr(3, "lead", "2026-09-21T01:00:00Z"),
        _pr(4, "carol", "2026-09-21T01:00:00Z", draft=True),
    ]
    summary = report.latency_summary(prs, exclude_authors={"lead"})
    assert summary["pull_requests"] == 2
    assert summary["without_response"] == 0
    assert summary["first_response_within_2_business_days"] == 0.5
    assert summary["first_response_hours"]["p50"] == 72.0


def test_cross_author_reviews_count_distinct_prs_and_honour_path_scope():
    prs = [
        _pr(1, "alice", "2026-09-21T01:00:00Z", reviews=[("bob", "2026-09-21T02:00:00Z")],
            comments=[("bob", "2026-09-21T03:00:00Z")], files=("loopx/capabilities/periodic_report/a.py",)),
        _pr(2, "bob", "2026-09-21T01:00:00Z", comments=[("bob", "2026-09-21T02:00:00Z")]),
        _pr(3, "alice", "2026-09-21T01:00:00Z", comments=[("bob", "2026-09-21T02:00:00Z")], files=("docs/a.md",)),
    ]
    assert report.cross_author_reviews(prs) == {"bob": 2}
    scoped = report.cross_author_reviews(prs, path_prefixes=("loopx/capabilities/periodic_report/",))
    assert scoped == {"bob": 1}


def test_cli_reads_json_lines_input(tmp_path, capsys):
    source = tmp_path / "prs.jsonl"
    rows = [_pr(1, "alice", "2026-09-21T01:00:00Z", reviews=[("lead", "2026-09-21T02:00:00Z")])]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert report.main(["--since", "2026-09-01", "--input", str(source), "--exclude-author", "lead", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contributor_latency"]["pull_requests"] == 1
    assert payload["cross_author_reviews"] == {"lead": 1}
