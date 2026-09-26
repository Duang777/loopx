# Basic usage statistics

[中文](usage-ping.zh-CN.md)

Basic usage statistics are **on by default after visible first-use disclosure**.
They help prioritize supported platforms, understand continued use and find slow
or failing CLI entry points. They are not a measurement of accepted Goal
outcomes. No content collection is implemented.

```bash
loopx usage-ping status      # current policy, recipient and outgoing payload previews
loopx usage-ping disable     # stop all channels; delete local ID and pending counts
loopx usage-ping enable      # explicitly allow all channels after reading the disclosure
```

Settings → Capability Center exposes the same machine-wide switch and previews.
Opening settings or running these commands never sends a measurement. Settings
are owned by the TypeScript usage-statistics module, independently of a Goal's
File/SQLite/PostgreSQL provider; Python and the browser adapt that same owner.
Lark has no separate switch and cannot override the machine owner's choice.

## Product questions and exact scope

| Question | Evidence | Limit |
|---|---|---|
| Which versions/platforms need support? | Daily version, OS, CPU architecture, Python minor and install channel | Only reporting installations |
| Do installations keep using LoopX? | Random installation ID, deduplicated by UTC day | Installations, not people; reinstall/re-enable may count again |
| Which CLI entry points are used? | Fixed command-family counters | Polling and automation count too; not a measure of user value |
| Which commands fail or take time? | Result, typed error category, coarse elapsed-time bucket | CLI return status is not Goal acceptance; handled domain failures may return 0 |

The first version measures CLI invocations, including those made by agents.
Top-level `--help`/`--version` fast paths, native exec-replaced scheduler
followups, API-only interactions and individual App/Lark actions are not
instrumented. Heartbeats start in the background before dispatch; long-running server command
results are counted only when the CLI returns. There is no claim to complete product activity or task success rates.

## Two separate payloads

**Daily heartbeat** (`POST /v1/ping`), with exactly these fields:

```json
{"schema":"loopx_usage_ping_v1","install_id":"00000000-0000-4000-8000-000000000001","version":"1.2.0","os":"linux","arch":"x64","python":"3.13","channel":"pip"}
```

The ID is random, local to the installation and not derived from hardware or an
account. It enables cross-day association, so this is **not fully anonymous**.
OS is `darwin|linux|windows|other`, CPU is `x64|arm64|x86|other`, and channel is
`pip|local_release|source|unknown`. Version accepts only numeric major.minor.patch;
a custom version containing a private suffix is not sent.

**Closed-day CLI aggregate** (`POST /v1/aggregate`):

```json
{"schema":"loopx_usage_aggregate_v1","counters":[{"feature":"todo","outcome":"ok","duration":"lt_1s","error":"none","count":4}]}
```

No installation ID, version, timestamp, Goal or other join key is included.
The collector adds its reception day, merges counters, and stores no individual
request rows. Both sender and collector use the same strict TS allowlist:

- Feature: `status`, `quota`, `todo`, `turn`, `project`, `connect`, `pr-review`,
  `version`, `chat`, `other`. Unlisted commands become `other`, never raw names.
- Result: `ok`, `failed`, `cancelled`.
- Duration: `<100ms`, `100ms–<1s`, `1s–<10s`, `10s–<60s`, `≥60s`, encoded as
  `lt_100ms|lt_1s|lt_10s|lt_60s|gte_60s`. This measures command dispatch, not full
  interpreter startup or Goal duration.
- Error: `none`, `command_failed`, `timeout`, `connection`, `interrupted`.
  Typed exceptions supply categories; error messages are never parsed or sent.

No prompts, source code, paths, repositories, arguments, tool outputs, raw
errors, stack traces, Goal/Todo IDs or custom Agent/MCP names are collected.
Additional payload fields and invalid enum combinations are rejected.

## Disclosure and precedence

The first interactive CLI command prints the recipient, fields, purpose and
both disable mechanisms to stderr, records the disclosure, and sends nothing.
Later commands may measure/send. A fresh unattended installation does not
silently opt itself in: use the visible App setting or explicit CLI enable.
JSON stdout is unaffected. Previously enabled v0 clients keep their random ID
but must see the expanded-scope disclosure; previously disabled clients stay off.

An explicit stored disable blocks all channels. The following environment
settings also block all channels, even after explicit enable:

- `LOOPX_USAGE_PING=0|false|no|off`
- `DO_NOT_TRACK` set to a nonempty value other than `0`
- `CI` set to a nonempty value other than `0|false`

`LOOPX_USAGE_POLICY=consent_required` requires explicit enable; merely displaying
the notice is insufficient. Default policy is `opt_out`; unknown policies fail
closed. Distribution owners must choose the applicable policy before shipping;
this switch does not itself determine legal compliance, infer region from IP,
or replace any applicable consent requirement.

The project endpoint is
`https://loopx-usage-collector.huangrt01.workers.dev/v1/ping`.
`LOOPX_USAGE_PING_ENDPOINT` may override it with an HTTPS `/v1/ping` URL (HTTP is
allowed only on loopback for testing). Credentials, queries and fragments are
rejected. The aggregate destination is the same origin's sibling `/v1/aggregate`.
Recipient/policy changes invalidate the prior disclosure; explicit enable
confirms the new selection. Switching recipients clears buffered counts and
rotates the ID. Redirects are never followed.

## Delivery, local state and withdrawal

State remains in `~/.codex/loopx/usage-ping.json`, mode `0600`. It is not copied
into Goal state, backups of authority providers, or public projections. Normal
CLI invocation reads only a small local hint; a detached Node process owns
measurement, locks and network I/O. A first-use/settings operation may wait for
local Node execution, never for a collector connection.

Each installation attempts at most one heartbeat per UTC day. Counts are capped
at 128 distinct rows and 10,000 per row, then flushed on the first eligible
command after the UTC day closes. Unsent counts older than seven days are
discarded. An installation that never runs again will not flush its final day.
Lock contention, crashes and failed requests can lose counts. There are no
immediate retries and no durable network queue. Clock rollback does not reopen
a daily attempt. These are **lossy diagnostics**, not billing or audit records.

Requests have a three-second deadline, do not block command completion, and
cannot change its output or exit code. They use the supported Node runtime's
`HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` settings; proxy addresses and credentials
never enter telemetry payloads. Disable deletes the local ID and buffered
counts; an old worker cannot restore them or send the next channel. A request
already handed to the network cannot be recalled. Re-enable uses a new ID.
Corrupt or unsupported state fails closed; explicit disable is the repair path.

## Collector and interpretation

[Collector source and upgrade instructions](../../apps/usage-collector/README.md).
Heartbeat history is retained for 400 days; aggregated counters for 30 days.
The existing `/v0/stats` endpoint continues to report deduplicated installations
from old and new heartbeat clients. `/v1/aggregate-stats` publishes independent
feature/result/duration/error totals, omitting cells below five. It does not
publish cross-dimensional combinations or per-install behavior histories.

Application code stores no client IP, user agent or Cloudflare request metadata;
Worker observability is disabled in the deployment template. Network providers
still handle connection metadata: separating bodies does not guarantee that
requests can never be correlated. Public unauthenticated counters can be
inflated, and suppression/loss makes these estimates unsuitable for billing.
The service may be unreachable on some networks; the owner can supply a reachable
collector, and LoopX continues to work without telemetry.

## Observed Goal duration

The Goal channel adds two duration histograms to basic statistics. It helps
answer whether observed work continues for hours or days, and how much Host
execution those spans contain. It does not identify a person or a Goal.

- **Span:** first to most recent observed Host execution, including intervening
  pauses. It stops growing while no execution is observed.
- **Execution:** union of observed Host-call intervals for one Goal on one
  machine. Concurrent or nested calls overlap only once; retry execution counts,
  settlement-only replay does not. Network/tool/approval waits inside a Host call
  are included; this is neither CPU time nor billing time.
- **Sampling:** one cumulative snapshot per locally observed Goal-day, flushed
  after that UTC day closes when another observation or normal usage occurs.
  Unfinished Goals are included. A continuously executing Host checkpoints every
  minute and can flush without another CLI command. Quiet Goals are not counted
  again every day. These counts are **Goal-day observations, not unique Goals**;
  the collector cannot join a Goal across days or machines.

Coverage is managed `turn run-once` Host execution and regular owner Goal chat.
Native `/goal`, externally attached agent sessions, manager and external-audience
conversations are excluded because they do not share these timing boundaries.
File, SQLite and PostgreSQL use the same observer; no provider state is queried
or changed. Measurement starts when first observed after notice acknowledgment,
not at historical Goal creation. Disabling, changing recipient, or clearing local
state restarts measurement. There is no historical backfill or completion claim.

All durations are lower bounds on observed work: confirmed prefixes survive a
crash; missing final checkpoints, lock contention, network failure, suspended
hosts and collection limits can lose observations. Never extrapolate a crashed
Host as still executing. Local storage holds at most 64 Goals and 512 disjoint
recent intervals per Goal; old intervals compact into totals, and 90-day inactive
Goals expire. Delayed observations older than one day are discarded; pending
snapshots older than seven days are discarded. Do not use this channel for
liveness detection, quotas, acceptance, or accounting.

The only outgoing Goal payload is:

```json
{"schema":"loopx_goal_usage_aggregate_v1","counters":[{"span":"lt_7d","execution":"lt_6h","count":1}]}
```

Both durations use `lt_1m`, `lt_10m`, `lt_1h`, `lt_6h`, `lt_1d`, `lt_7d`,
`lt_30d`, `gte_30d`. No Goal ID, installation ID, source path, name, event time
or free text is sent. `/v1/goals` accepts the strict payload; `/v1/goal-stats`
returns independent marginal histograms for the last 30 receipt days and omits
cells below five. The existing usage settings switch, environment opt-outs and
consent policy control all three channels. Settings and `loopx usage-ping status`
show `goal_preview`; this is a current local snapshot, not a delivery receipt.
The expanded scope requires notice version 2; previous explicit disable persists.

Deploy collector migration `0002-goal-usage.sql` and its Worker before shipping
the client. This additive table leaves existing heartbeats and CLI counts intact.
