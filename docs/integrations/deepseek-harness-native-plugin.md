# DeepSeek Harness Native LoopX Plugin

Status: public-safe v1 integration for running a LoopX-governed continuation
inside the current visible DeepSeek Harness Session.

The native provider is an optional DSH bundle in
`packages/dsh-loopx-plugin/`. Its canonical LoopX agent type is
`deepseek-harness-native`; `dsh-native` is only an input alias. It is separate
from the existing `deepseek-harness` / `dsh` external adapter and is not a
migration or replacement for that connector.

## Choose the correct surface

| Need | Agent type | Execution shape | Entry point |
| --- | --- | --- | --- |
| Continue inside the current visible DSH Agent and Session | `deepseek-harness-native` (`dsh-native` alias) | Same-process command, tools, follow-up, and Host sidecar | `/loopx <task>` after installing `dsh-loopx-plugin` |
| Run one isolated, independently validated DSH-backed LoopX Turn | `deepseek-harness` (`dsh` alias) | External Python SDK adapter and headless runtime | `loopx turn run-once` with `scripts/dsh_turn_host_adapter.py` |

Both surfaces keep LoopX authoritative for Goal, Todo, gate, quota, evidence,
scheduler, and terminal state. They differ only in Host integration and
execution lifecycle.

## Install and verify

Prerequisites are DSH `0.1.0-rc.7`, Node.js `^22.19.0 || >=24`, and a local
`loopx` executable:

```bash
dsh --version
command -v loopx
loopx --version
```

Build and add the local bundle to the supported `web` profile:

```bash
cd packages/dsh-loopx-plugin
corepack pnpm install --frozen-lockfile --ignore-scripts
pnpm typecheck
pnpm test
pnpm build
dsh plugin --profile web add "$PWD"
```

The canonical artifact path is a prebuilt tarball:

```bash
pnpm pack --pack-destination <artifact-directory>
dsh plugin --profile web add <artifact-directory>/dsh-loopx-plugin-0.1.0.tgz
```

Profile readback is boot-free and must show four Host rows plus durable JSON
storage-domain routing:

```bash
dsh --profile web --dump-config
```

Expected rows are `loopx-service`, `loopx-command`, `loopx-tools`, and
`loopx-driver`. The `storage-domain` row must resolve `backend: json`. The
service declares `storageDomain` as a required injection and therefore stays
pending when that backend is absent; no memory-only fallback exists.

## Local LoopX executable

The plugin uses Node `execFile` with argv arrays. It never evaluates packet
command strings and does not invoke Python directly. Resolution is explicit
`loopxBin` config, then `LOOPX_BIN`, then the locally installed `loopx` on
`PATH`. The normal setup is therefore simply:

```bash
command -v loopx
dsh --profile web
```

Use `LOOPX_BIN=/path/to/loopx dsh --profile web` when the binary is not on the
Host `PATH`. Optional config can pin `project`, `runtimeRoot`, timeouts and
byte caps, or a minimal child-only environment. The defaults are read timeout
15 seconds, write timeout 30 seconds, stdout 1 MiB, and stderr 256 KiB.

## Same-Session lifecycle

Send any task-bearing request through the visible DSH command surface:

```text
/loopx implement the bounded change
/loopx attach Goal goal-123 and continue it here
/loopx status
```

Every non-empty suffix except exact `/loopx version` uses the same semantic
entry, including words such as `start`, `attach`, `status`, `pause`, `resume`,
and `detach`. The plugin queues one plugin-owned follow-up in the same Session,
preserving the original suffix as quoted user text plus compact routing
guidance. The current main DSH model handles one ordinary turn and may compose
the registered `loopx_*` typed tools. The command does not mutate LoopX before
that turn, run a classifier, create another Agent, or invoke a second model.

If the Session is unbound, attachment requires both an explicit Goal id and
explicit binding intent; otherwise the model starts a new Goal from the
original request. If the Session is already bound, the current Goal remains
selected. Switching requires a different exact Goal id plus explicit switching
intent; detaching the current binding requires explicit detach intent but no
Goal id. The model never guesses or fuzzy-matches a Goal id. If it cannot
choose a safe operation, it asks for clarification without changing state.

The routing text is prompt guidance rather than a machine-enforced hard
allowlist. Other DSH tools may remain visible; LoopX mutations are still bounded
by the registered typed schemas and authoritative service readback. Ordinary
language without `/loopx` retains DSH's normal model/tool-selection behavior.

When the semantic turn selects `loopx_goal_start`, LoopX returns the exact
thread/Goal/agent identity and the structured `loopx_goal_start_command_v0`
planning contract. The tool projects it to
`dsh_loopx_planning_checkpoint_v0` and returns it directly to the model. The
model writes the bounded plan only through `loopx_todo_add`; then
`loopx_goal_activate` performs a suppressed-sink refresh and authoritative
reread, fetches the heartbeat task body into memory, and arms the driver. The
plugin keeps no parallel Todo receipt ledger; LoopX remains authoritative for
the Todo and refreshed task state.

A stable DSH Session with no prior binding defaults to a distinct public-safe
LoopX peer identity, so both `/loopx <task>` and semantic start can enter the
planning checkpoint without choosing an existing lane. Verified same-Session
bindings are reused; takeover of an existing peer remains explicit, while a
host without a stable Session id fails closed.

For a fresh project, the plugin validates the structured
`loopx_start_goal_connect_v0` packet, constructs a locally owned and allowlisted
`loopx bootstrap` argv, validates `loopx_bootstrap_result_v0`, and rereads the
authoritative guided projection. It never executes packet command text, accepts
model-supplied argv, or edits a registry directly. Unknown versions and
malformed legacy connection states fail closed with actionable upgrade or
repair guidance.

Fresh-agent registration runs the same source-to-global sync as a read-only
preflight before changing the source registry. A
`LOOPX_REGISTRY_INTEGRITY` result is therefore a deterministic pre-write
failure; run `loopx sync-global --goal-id <goal-id> --dry-run` and repair the
reported registry contract before retrying. A `LOOPX_WRITE_UNCERTAIN` result
instead means the source write may exist while global sync or exact readback is
unverified. Do not generate another peer: reconcile the source/global agent
sets before binding the Session.

Existing Goals require an explicit lane decision:

```text
/loopx attach <goal-id> <agent-id>
/loopx attach <goal-id> --new-peer
```

Natural-language attach requests use `loopx_goal_attach` with an exact Goal
selection. If start or attach targets a different Goal from the one historically
bound to this Session, the first call returns `switch_required` without
mutation. Only after explicit user confirmation may the model repeat the same
typed operation with its `switchConfirmation` token. The token is short-lived,
operation-bound, process-memory-only, and revalidated against the exact current
Goal and agent inside the per-Session queue.

The model-facing surface contains exactly eleven tools:

- `loopx_goal_start`
- `loopx_goal_attach`
- `loopx_goal_activate`
- `loopx_status`
- `loopx_goal_detach`
- `loopx_driver_pause`
- `loopx_driver_resume`
- `loopx_todo_add`
- `loopx_todo_claim`
- `loopx_todo_update`
- `loopx_todo_complete`

All derive the current Session identity. Alternate Session ids, registry
paths, task bodies, arbitrary argv, and unsupported fields are rejected and
the active driver fails closed.

At each idle boundary, the driver calls `loopx quota should-run` with runtime
profile `generic_cli`, scheduler detail, and one unique turn identity. A
certain retryable failure gets at most one retry with that same identity.
Generation and lifecycle fences protect every post-await follow-up, scheduler
write, pause, uncertain transition, reload, disposal, and foreign-input path.

## Observe, pause, resume, and detach

```text
/loopx
/loopx version
/loopx status
/loopx pause
/loopx resume
/loopx detach
```

Empty `/loopx` retains the local status/help response. Exact `/loopx version`
returns only the installed `dsh-loopx-plugin` package version; it does not
invoke the LoopX CLI or inspect Goal, Todo, or Host binding state. `version`
with additional text and the other examples above enter the semantic path.
Their corresponding typed operations keep Host state separate from live LoopX
authority. Pause changes only driver state. Resume revalidates LoopX identity
and refetches task text before arming a fresh generation. Detach removes the
current Session binding and performs authoritative unbind readback; it does
not alter the Goal or Todo lifecycle.

An uncertain detach stops a requested switch before the new Goal is started or
attached. If exact detach succeeds but the new operation fails, the Session is
reported honestly as unbound; the plugin does not claim to have restored the
old binding.

Human messages, foreign plugin messages, and command runs preempt automatic
continuation. The driver owns at most one evaluation, AbortController, timer,
and follow-up attempt per Session. It becomes quiet when the LoopX scheduler
unchanged limit is reached and treats only a validated terminal-no-follow-up
receipt as terminal.

## Remove and rollback

```bash
dsh plugin --profile web remove dsh-loopx-plugin
dsh --profile web --dump-config
```

Removal takes away the command, tools, service, and driver rows. It does not
delete LoopX state or purge the DSH storage-domain sidecar. v1 has no implicit
purge command. On reinstall, a stored armed binding cold-restores paused and
requires exact lifecycle readback plus explicit resume.

Existing control words remain usable through the semantic `/loopx` entry, and
the prior five tools remain compatible. Typed start, attach, detach, driver
pause/resume, and Todo add are additive. Older consumers
may ignore the additive Python fields, but this
plugin fails closed when a required guided-connect, planning, refresh-state, or
bootstrap-result schema is unavailable. Roll back by removing the plugin or
installing the preceding package version; neither action migrates or rewrites
LoopX Goal/Todo authority.

## Authority and privacy

`ctx.loopx` and `ctx.goals` are fully isolated. DSH retains only Host binding
identity, locators, lifecycle phase/generation, scheduler bookkeeping, and a
bounded reason. Goal text, task bodies, and normal conversation content are not
copied into that sidecar or published as LoopX evidence; they still follow DSH
Session persistence. Raw command output, environment values, credentials, and
local logs are not projected into model output.

Installing the provider grants only typed LoopX operations against derived
authoritative locators; it grants no arbitrary filesystem path, argv, shell,
network, credential, production, or cross-Session authority. Multi-Host
processes sharing one storage root, cross-machine scheduling, and hostile
local callers are outside the v1 threat model.

## Hermetic acceptance

Maintainers validate both a built package directory and its tarball against a
temporary `DSH_HOME`:

```bash
node smoke/dsh-profile-smoke.mjs \
  --package-path . \
  --tarball <artifact-directory>/dsh-loopx-plugin-0.1.0.tgz
```

The smoke performs real DSH plugin add/dump/remove operations, uses a mock
LoopX executable, and checks all eleven registered tools, the versioned fresh
connect/bootstrap exchange, single-follow-up semantic command entry, typed Todo
writeback plus two-phase activation, one idle continuation,
foreign-input pause, sidecar privacy, and tarball contents. It does not start a
model, access the network, require credentials, or touch the user's existing
DSH Profile.

## Related contracts

- [External DeepSeek Harness connector](deepseek-harness-connector.md)
- [Runtime connector catalog](runtime-connector-catalog.md)
- [Host integration surface v0](../reference/protocols/host-integration-surface-v0.md)
- [LoopX Turn v0](../reference/protocols/loopx-turn-v0.md)
