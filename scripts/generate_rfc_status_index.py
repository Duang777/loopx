#!/usr/bin/env python3
"""Generate the RFC status index from each RFC's own status header.

The index is derived, never hand-edited: an RFC changes state by editing its
header, and ``--check`` fails when ``STATUS.md`` / ``STATUS.zh-CN.md`` no
longer match. Lifecycle buckets are Accepted, Active (Draft or Under review),
Superseded and Retired (Retired or Rejected). The script also reports RFCs whose
header is unparseable, whose index entry disagrees with the header, or whose
body still carries checkpoint headings that belong in the execution ledger.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RFC_DIR = REPO_ROOT / "docs" / "architecture" / "rfcs"
LEDGER_DIR = RFC_DIR / "ledger"
INDEX_EN = RFC_DIR / "STATUS.md"
INDEX_ZH = RFC_DIR / "STATUS.zh-CN.md"
NON_RFC_FILES = {"README.md", "TEMPLATE.md", "STATUS.md"}
HEADER_SCAN_LINES = 40

LIFECYCLE_STATES = ("Draft", "Under review", "Accepted", "Superseded", "Retired", "Rejected")
BUCKETS = (
    ("Accepted", ("Accepted",)),
    ("Active", ("Draft", "Under review")),
    ("Superseded", ("Superseded",)),
    ("Retired", ("Retired", "Rejected")),
)
BUCKET_LABEL_ZH = {
    "Accepted": "已接受",
    "Active": "进行中（Draft 或 Under review）",
    "Superseded": "已被替代",
    "Retired": "已退役（Retired 或 Rejected）",
}
STATE_LABEL_ZH = {
    "Draft": "草案",
    "Under review": "评审中",
    "Accepted": "已接受",
    "Superseded": "已被替代",
    "Retired": "已退役",
    "Rejected": "已拒绝",
}

_STATUS_LINE_PATTERNS = (
    re.compile(r"\*\*RFC status:?\*\*[:：]?\s*(?P<value>.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*-\s*Status[:：]\s*(?P<value>.+?)\s*$"),
    re.compile(r"^\|\s*Status\s*\|\s*(?P<value>[^|]+?)\s*\|", re.IGNORECASE),
)
_STATE_PREFIXES = (
    ("under review", "Under review"),
    ("accepted", "Accepted"),
    ("superseded", "Superseded"),
    ("retired", "Retired"),
    ("rejected", "Rejected"),
    ("draft", "Draft"),
)
# Accepted forms: `- **Supersedes / closes:** none`, `- Supersedes / closes: none`,
# `| Supersedes / closes | none |` (and the zh mirrors with `替代 / 关闭`).
SUPERSEDES_RE = re.compile(
    r"(?:\*\*Supersedes / closes:\*\*|^\s*-\s*Supersedes / closes:|^\|\s*Supersedes / closes\s*\|)"
    r"\s*(?P<value>[^|]+?)\s*\|?\s*$"
)
SUPERSEDES_ZH_RE = re.compile(
    r"(?:\*\*替代 / 关闭[:：]\*\*|^\s*-\s*替代 / 关闭[:：]|^\|\s*替代 / 关闭\s*\|)"
    r"\s*(?P<value>[^|]+?)\s*\|?\s*$"
)
SUPERSEDED_BY_RE = re.compile(
    r"(?:\*\*Superseded by:\*\*|^\s*-\s*Superseded by:|^\|\s*Superseded by\s*\|)"
    r"\s*(?P<value>[^|]+?)\s*\|?\s*$"
)
# Dated progress belongs in ledger/<rfc>/YYYY-MM-DD-slug.md, not in an RFC body.
CHECKPOINT_HEADING_RE = re.compile(r"^#{1,6}\s.*(checkpoint|检查点)", re.IGNORECASE | re.MULTILINE)
INDEX_ENTRY_RE = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<file>[a-z0-9-]+\.md)\)", re.MULTILINE)
INDEX_STATUS_RE = re.compile(r"\*\*RFC status:\*\*\s*(?P<value>.+?)\s*$")


@dataclass
class RfcRecord:
    path: Path
    title: str
    title_zh: str | None
    status_raw: str | None
    state: str | None
    supersedes: str | None
    supersedes_zh: str | None
    superseded_by: str | None
    ledger_entries: int
    checkpoint_headings: list[str] = field(default_factory=list)
    checkpoint_headings_zh: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.path.stem


def normalize_state(raw: str) -> str | None:
    lowered = raw.strip().lower().lstrip("*_` ")
    for prefix, state in _STATE_PREFIXES:
        if lowered.startswith(prefix):
            return state
    return None


def parse_header(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (status_raw, supersedes, superseded_by) from the header block."""
    status_raw = supersedes = superseded_by = None
    for line in text.splitlines()[:HEADER_SCAN_LINES]:
        if status_raw is None:
            for pattern in _STATUS_LINE_PATTERNS:
                match = pattern.search(line)
                if match:
                    status_raw = match.group("value").rstrip(".")
                    break
        if supersedes is None:
            match = SUPERSEDES_RE.search(line)
            if match:
                supersedes = match.group("value")
        if superseded_by is None:
            match = SUPERSEDED_BY_RE.search(line)
            if match:
                superseded_by = match.group("value")
    return status_raw, supersedes, superseded_by


def parse_zh_header(text: str) -> tuple[str | None, str | None]:
    title = None
    supersedes = None
    for line in text.splitlines()[:HEADER_SCAN_LINES]:
        if title is None and line.startswith("# "):
            title = line[2:].strip()
        match = SUPERSEDES_ZH_RE.search(line)
        if match and supersedes is None:
            supersedes = match.group("value")
    return title, supersedes


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "<untitled>"


def checkpoint_headings(text: str) -> list[str]:
    return [match.group(0).strip() for match in CHECKPOINT_HEADING_RE.finditer(text)]


def rfc_files() -> list[Path]:
    return sorted(
        path
        for path in RFC_DIR.glob("*.md")
        if path.name not in NON_RFC_FILES and not path.name.endswith(".zh-CN.md")
    )


def collect() -> list[RfcRecord]:
    records = []
    for path in rfc_files():
        text = path.read_text(encoding="utf-8")
        status_raw, supersedes, superseded_by = parse_header(text)
        zh_path = path.with_name(f"{path.stem}.zh-CN.md")
        title_zh = supersedes_zh = None
        headings_zh: list[str] = []
        if zh_path.exists():
            zh_text = zh_path.read_text(encoding="utf-8")
            title_zh, supersedes_zh = parse_zh_header(zh_text)
            headings_zh = checkpoint_headings(zh_text)
        ledger_scope = LEDGER_DIR / path.stem
        ledger_entries = (
            len([entry for entry in ledger_scope.glob("*.md") if not entry.name.endswith(".zh-CN.md")])
            if ledger_scope.is_dir()
            else 0
        )
        records.append(
            RfcRecord(
                path=path,
                title=first_heading(text),
                title_zh=title_zh,
                status_raw=status_raw,
                state=normalize_state(status_raw) if status_raw else None,
                supersedes=supersedes,
                supersedes_zh=supersedes_zh,
                superseded_by=superseded_by,
                ledger_entries=ledger_entries,
                checkpoint_headings=checkpoint_headings(text),
                checkpoint_headings_zh=headings_zh,
            )
        )
    return records


def index_entry_states(readme_text: str) -> dict[str, str | None]:
    """Map each RFC file listed in README.md to the lifecycle state it states."""
    states: dict[str, str | None] = {}
    lines = readme_text.splitlines()
    for number, line in enumerate(lines):
        match = INDEX_ENTRY_RE.match(line)
        if not match:
            continue
        stated = None
        for follow in lines[number + 1 : number + 8]:
            status = INDEX_STATUS_RE.search(follow)
            if status:
                stated = normalize_state(status.group("value"))
                break
            if INDEX_ENTRY_RE.match(follow):
                break
        states[match.group("file")] = stated
    return states


def validate(records: list[RfcRecord]) -> list[str]:
    problems: list[str] = []
    readme_states = index_entry_states((RFC_DIR / "README.md").read_text(encoding="utf-8"))
    for record in records:
        name = record.path.name
        if record.status_raw is None:
            problems.append(f"{name}: no status header found in the first {HEADER_SCAN_LINES} lines")
        elif record.state is None:
            problems.append(
                f"{name}: status {record.status_raw!r} does not start with one of {LIFECYCLE_STATES}"
            )
        if name not in readme_states:
            problems.append(f"{name}: not listed in README.md index")
        elif record.state and readme_states[name] and readme_states[name] != record.state:
            problems.append(
                f"{name}: README.md says {readme_states[name]} but the RFC header says {record.state}"
            )
        if record.supersedes is None:
            problems.append(f"{name}: missing `**Supersedes / closes:**` declaration (none | <RFC links>)")
        if record.supersedes is not None and record.title_zh is not None and record.supersedes_zh is None:
            problems.append(f"{record.slug}.zh-CN.md: missing `**替代 / 关闭：**` mirror of the supersession line")
        if record.state == "Superseded" and record.superseded_by is None:
            problems.append(f"{name}: Superseded RFCs must name `**Superseded by:**`")
        for heading in record.checkpoint_headings:
            problems.append(f"{name}: checkpoint heading belongs in ledger/{record.slug}/: {heading}")
        for heading in record.checkpoint_headings_zh:
            problems.append(f"{record.slug}.zh-CN.md: checkpoint heading belongs in ledger/{record.slug}/: {heading}")
    for listed in readme_states:
        if not (RFC_DIR / listed).exists():
            problems.append(f"README.md lists {listed}, which does not exist")
    return problems


def _ledger_cell(record: RfcRecord, *, zh: bool) -> str:
    if record.ledger_entries == 0:
        return "—"
    noun = "条" if zh else ("entry" if record.ledger_entries == 1 else "entries")
    return f"[{record.ledger_entries} {noun}](ledger/{record.slug}/)"


def render(records: list[RfcRecord], *, zh: bool) -> str:
    by_state: dict[str, list[RfcRecord]] = {state: [] for state in LIFECYCLE_STATES}
    for record in records:
        by_state.setdefault(record.state or "Draft", []).append(record)
    lines: list[str] = []
    if zh:
        lines += [
            "# RFC 状态索引",
            "",
            "<!-- 由 scripts/generate_rfc_status_index.py 生成；不要手工编辑。 -->",
            "",
            "本索引从本目录每个 RFC 自己的状态头生成。改变一个 RFC 的状态只需要改它的头部，",
            "然后运行 `python3 scripts/generate_rfc_status_index.py --write`；"
            "`--check` 在索引过期时失败，`examples/docs-governance-smoke.py` 会调用它。",
            "",
            "生命周期分档：**已接受**（Accepted）、**进行中**（Draft、Under review）、",
            "**已被替代**（Superseded，必须写明 `Superseded by`）、**已退役**（Retired、Rejected）。",
            "RFC 状态和交付成熟度是两件事；后者见 [README 索引](README.md)（仅英文）的 Delivery 行。",
            "新 RFC 必须在头部声明 `**替代 / 关闭：**`（`无` 或所替代 / 关闭的旧 RFC 链接）。",
            "带日期的 checkpoint 记录写进 [ledger/](ledger/README.zh-CN.md)，不写进 RFC 正文。",
            "",
            "[English](STATUS.md) 与本文互为语义镜像。",
        ]
    else:
        lines += [
            "# RFC Status Index",
            "",
            "<!-- generated by scripts/generate_rfc_status_index.py; do not edit by hand -->",
            "",
            "This index is derived from the status header of every RFC in this directory.",
            "Change an RFC's state by editing its header, then run",
            "`python3 scripts/generate_rfc_status_index.py --write`; `--check` fails while the",
            "index is stale and `examples/docs-governance-smoke.py` runs it.",
            "",
            "Lifecycle buckets: **Accepted**; **Active** (Draft, Under review);",
            "**Superseded** (must name `Superseded by`); **Retired** (Retired, Rejected).",
            "RFC status and delivery maturity are separate facts; delivery lives in the",
            "[README index](README.md) `Delivery on main` lines. Every new RFC declares",
            "`**Supersedes / closes:**` in its header (`none` or links to the RFCs it",
            "replaces or closes). Dated checkpoints go to [ledger/](ledger/README.md), never",
            "into an RFC body.",
            "",
            "[中文版](STATUS.zh-CN.md) is the semantic mirror of this file.",
        ]
    for bucket, states in BUCKETS:
        members = sorted(
            (record for state in states for record in by_state.get(state, [])),
            key=lambda record: record.slug,
        )
        label = BUCKET_LABEL_ZH[bucket] if zh else bucket
        lines += ["", f"## {label} ({len(members)})", ""]
        if not members:
            lines.append("_无_" if zh else "_none_")
            continue
        if zh:
            lines += ["| RFC | 头部状态 | 替代 / 关闭 | Ledger |", "| --- | --- | --- | --- |"]
        else:
            lines += ["| RFC | Header status | Supersedes / closes | Ledger |", "| --- | --- | --- | --- |"]
        for record in members:
            if zh:
                target = f"{record.slug}.zh-CN.md" if record.title_zh else record.path.name
                title = record.title_zh or record.title
                status = STATE_LABEL_ZH.get(record.state or "", record.state or "?")
                supersedes = record.supersedes_zh or ("—" if record.supersedes is None else record.supersedes)
            else:
                target = record.path.name
                title = record.title
                status = record.state or "?"
                supersedes = record.supersedes or "—"
            if record.superseded_by:
                supersedes = f"{supersedes}; superseded by {record.superseded_by}"
            title = title.replace("|", "\\|")
            lines.append(f"| [{title}]({target}) | {status} | {supersedes} | {_ledger_cell(record, zh=zh)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Rewrite STATUS.md and STATUS.zh-CN.md.")
    mode.add_argument("--check", action="store_true", help="Fail when the checked-in index is stale.")
    parser.add_argument("--report", action="store_true", help="Print header problems without failing.")
    args = parser.parse_args(argv)

    records = collect()
    problems = validate(records)
    rendered_en = render(records, zh=False)
    rendered_zh = render(records, zh=True)

    if args.report or not (args.write or args.check):
        for problem in problems:
            print(problem)
        print(f"{len(records)} RFCs; {len(problems)} problems")
        if not (args.write or args.check):
            return 0
    if problems and not args.report:
        for problem in problems:
            print(problem, file=sys.stderr)
    if args.write:
        INDEX_EN.write_text(rendered_en, encoding="utf-8")
        INDEX_ZH.write_text(rendered_zh, encoding="utf-8")
        print(f"wrote {INDEX_EN.relative_to(REPO_ROOT)} and {INDEX_ZH.relative_to(REPO_ROOT)}")
        return 1 if problems else 0
    stale = []
    for path, rendered in ((INDEX_EN, rendered_en), (INDEX_ZH, rendered_zh)):
        if not path.exists() or path.read_text(encoding="utf-8") != rendered:
            stale.append(path.relative_to(REPO_ROOT))
    if stale:
        print(
            "stale RFC status index: " + ", ".join(map(str, stale))
            + "; run python3 scripts/generate_rfc_status_index.py --write",
            file=sys.stderr,
        )
    return 1 if (stale or problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
