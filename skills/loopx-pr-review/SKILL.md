---
name: loopx-pr-review
description: Use when the visible request starts with `/loopx-pr-review` or asks LoopX to review a repository PR queue by time window or state. Run `loopx pr-review` first, preserve its full packet, execute per-PR evidence commands, and follow the packet-owned response contract. Publish validated review findings for open PRs by default; use `loopx-pr-merge` for approval or merge actions.
---

# LoopX PR Review

## Routing And Publication

Use this skill for PR queue review, including open, merged, closed, current-day,
or explicit time-window requests. The `/loopx-pr-review` prefix means review,
not a table-only inventory, unless the user explicitly asks for stats or a list
only.

For open PRs, publish the evidence-backed result unless the user explicitly asks
for `local-only`, `dry-run`, `不要评论`, `不要提交 review`, or equivalent:

- submit a formal `REQUEST_CHANGES` review when validated merge-blocking
  findings remain;
- otherwise publish the findings or no-blocker result as a normal review or
  comment unless approval was explicitly requested;
- route approval, merge, self-merge, and admin-bypass to `loopx-pr-merge`.

Do not leave actionable blockers only in chat or replace a blocking formal
review with a plain comment.

## Start From The Capability Packet

Run the LoopX CLI before manual GitHub calls:

```bash
loopx --format json pr-review --state all
```

Translate user filters only into supported options:

- `--repo owner/repo` for an explicit repository;
- `--since ISO` for an explicit time window;
- `--state open`, `--state merged`, or `--state all` for state filters;
- `--limit N` when the user explicitly requests a bounded batch.

Default to the current `gh` repository, `--state all`, and the CLI's normal
group limit. Words such as `today`, `open`, `closed`, and `merged` are filters,
not permission to stop after listing metadata.

## Preserve The Packet

Keep these fields from the first CLI result in model context:

- `agent_response_contract`;
- `result_completeness`;
- `review_groups`;
- `pull_requests[].review_template`;
- `pull_requests[].evidence_commands`.

Do not pipe the first packet through `jq` or another projection that keeps only
`.summary`, `.review_sequence`, or a table. If a compact view is useful, save
the full JSON first and print a derivative view from that saved packet.

When the user asks for `all`, `every`, `全部`, `每个`, or an exhaustive window,
require `result_completeness.complete=true` before review. Otherwise rerun with
`--limit <result_completeness.recommended_limit>` until complete and treat the
latest full packet as the queue source of truth.

## Autonomous Queue Routing

For a recurring monitor, use the capability's observation route:

```bash
loopx --format json pr-review --repo owner/repo --state open \
  --autonomous-observation \
  [--previous-observation-json previous.json] \
  [--handled-exact-head NUMBER@HEAD_OID]
```

Follow `autonomous_review` literally. Incomplete observation is not unchanged;
a selected candidate is not mutation authority; and a head is handled only
after the formal review was published and read back for that exact head. Let
normal Todo authority materialize any candidate.

## Execute Evidence Per PR

Review `review_groups.unmerged` first, then `review_groups.merged`. A queue table
may be a short preface, but is not the review result.

For every selected PR:

1. Run its `evidence_commands`, or equivalent targeted PR body, checks,
   changed-file, and patch reads.
2. For code changes, inspect the behavior-bearing definitions and active call
   sites, not only changed hunks.
3. Keep evidence and conclusions specific to that PR. Do not reuse another
   PR's architecture, validation, or risk prose.
4. Record the remote `headRefOid` before deep review and query it again before
   the verdict. Restart on a changed head.
5. Use a clean read-only exact-head worktree when execution or line-level
   evidence is needed, and name the reviewed short SHA.

Do not fill a review from title, labels, changed-file counts, or
`metadata_risk_hint`; that hint only orders the queue. If the queue is too large,
review the highest-priority subset and name what remains rather than compressing
individual cards into shallow summaries.

## Capability-Owned Output Contract

Treat `agent_response_contract`, especially `explanation_depth_contract`, and
each `review_template.sections[].agent_instruction` as authoritative. They own
the required sections, explanation depth, key-code walkthroughs, implementation
scale judgment, related-PR mapping, validation, and risk coverage. The skill
must not maintain a second checklist or repeat packet rules in host prose.

Use the packet's blank template as structure, never as evidence or example
content. Distinguish the author's intended behavior from what the exact diff,
active call sites, checks, and focused reproductions prove. For older packets
without the depth contract, explain context, architecture, implementation,
validation, necessity, and risk for a reader unfamiliar with the subsystem.

## Publish Fresh, Public-Safe Results

Immediately before publication, query `headRefOid` again. Build the review from
the exact reviewed head; remove local paths, private context, raw logs,
credentials, and internal-only links; and submit with literal-safe text
handling. The GitHub review state must match the verdict.

Read the published review back and verify its state and rendered body. Avoid an
equivalent duplicate review from the same reviewer on the same head. Include
the resulting GitHub review or comment URL in the user-facing summary. If
GitHub rejects the requested state, report the exact failure and do not imply
that publication succeeded.

## Failure And Fallback

If `loopx pr-review` is unavailable, repair the LoopX install or use the intended
checked-out LoopX CLI. Do not reconstruct the queue manually and call it a
successful `/loopx-pr-review` run.

Finish the evidence-backed review before routing any separately authorized
approval or merge action to `loopx-pr-merge`.
