# LoopX for DeepSeek Harness

`dsh-loopx-plugin` adds a same-session `/loopx` command, eleven bounded model
tools, and a quota-gated continuation driver to the DeepSeek Harness `web`
profile. LoopX remains the only authority for Goal, Todo, quota, status,
evidence, and terminal state; DSH persists only a Host binding sidecar.

This package targets DSH `0.1.0-rc.7`, Node.js `^22.19.0 || >=24`, and a
locally installed `loopx` command. The plugin invokes that executable with
Node `execFile` and argv arrays. It does not invoke Python directly, start a
nested DSH process, or call `loopx turn run-once`.

## Prerequisites

Confirm both CLIs before installing the bundle:

```bash
dsh --version
command -v loopx
loopx --version
```

The LoopX binary resolution order is:

1. `loopxBin` in the `loopx-service` row config;
2. `LOOPX_BIN` in the DSH Host environment;
3. `loopx` on `PATH` (the normal default).

## Install from a local checkout

Build the package, then add its directory to the `web` profile:

```bash
cd packages/dsh-loopx-plugin
corepack pnpm install --frozen-lockfile --ignore-scripts
pnpm build
dsh plugin --profile web add "$PWD"
```

For a reviewable prebuilt artifact:

```bash
pnpm pack --pack-destination <artifact-directory>
dsh plugin --profile web add <artifact-directory>/dsh-loopx-plugin-0.1.0.tgz
```

Read back the composed profile before starting DSH:

```bash
dsh --profile web --dump-config
```

The dump must contain `loopx-service`, `loopx-command`, `loopx-tools`, and
`loopx-driver`, in that order, plus the `web` profile's `storage-domain` row
with `backend: json`. If the storage-domain service is unavailable, the LoopX
service stays pending; it never falls back to process memory.

To select an explicit executable without changing the profile, launch DSH
with `LOOPX_BIN=/path/to/loopx`. A profile-local override can instead replace
the bundle row in `$DSH_HOME/profiles/web/cordis.patch.yml`:

```yaml
- insert:
    - id: loopx-service
      name: dsh-loopx-plugin/service
      config:
        loopxBin: /path/to/loopx
```

Optional service config also includes `project`, `runtimeRoot`, and an
explicit child-only `environment` mapping. Do not place credentials in that
mapping. Defaults are 15 seconds for reads, 30 seconds for writes, 1 MiB for
stdout, and 256 KiB for stderr.

## Use

Send any task-bearing request through the current visible DSH Session:

```text
/loopx implement the requested change
/loopx attach Goal goal-123 and continue it here
/loopx status
```

Every non-empty suffix except exact `/loopx version` follows the same path,
including words such as `start`, `attach`, `status`, `pause`, `resume`, and
`detach`. The plugin queues one plugin-owned follow-up in the same Session. It
preserves the original suffix as quoted user text plus compact routing guidance,
then the current main DSH model handles one ordinary turn and may compose the
registered `loopx_*` typed tools. The command does not mutate LoopX before that
turn, run a keyword classifier, create another Agent, or invoke a second model.

For an unbound Session, the model may attach only when the request contains an
explicit Goal id and explicit binding intent; otherwise it starts a new Goal
from the original request. For an already-bound Session, it keeps the current
Goal. Switching requires a different exact Goal id plus explicit switching
intent; detaching the current binding requires explicit detach intent but no
Goal id. It never guesses or fuzzy-matches a Goal id. When no safe operation
can be determined, it asks for clarification without changing state.

The routing text is prompt guidance, not a machine-enforced hard allowlist.
Other DSH tools may remain visible; LoopX mutations remain bounded by the
registered typed schemas and authoritative service readback. Ordinary language
without `/loopx` continues through DSH's normal model/tool-selection path.

Starting a new Goal is deliberately two-phase. After the semantic turn selects
`loopx_goal_start`, that tool returns the structured
`dsh_loopx_planning_checkpoint_v0` directly to the model. The model writes the
minimum sufficient public-safe plan through
`loopx_todo_add`, then calls `loopx_goal_activate`. Activation performs a
suppressed-sink refresh plus authoritative readback before arming the local
driver. The plugin keeps no parallel Todo receipt ledger; LoopX remains the
authority for the resulting Todo and refreshed task state.

When start runs in a stable DSH Session with no prior binding, LoopX defaults
to a distinct public-safe peer identity for that Session. A verified binding
is reused on later starts; taking over an existing peer remains an explicit
exact-identity action, and a host without a stable Session id still fails
closed.

On a fresh project, the plugin accepts only the structured
`loopx_start_goal_connect_v0` contract, maps its allowlisted fields to a fixed
local `loopx bootstrap` argv, validates `loopx_bootstrap_result_v0`, and rereads
the guided state before binding. A producer-supplied command hint is never
executed. Unsupported or malformed producer schemas fail closed with upgrade
or repair guidance; the plugin never falls back to a shell command or direct
registry edit.

Fresh-agent registration preflights the same source-to-global sync before it
changes the source registry. `LOOPX_REGISTRY_INTEGRITY` therefore means no
fresh identity was written; inspect the authoritative error with
`loopx sync-global --goal-id <goal-id> --dry-run`, repair that registry
contract, and retry. `LOOPX_WRITE_UNCERTAIN` means a source write may already
exist but global sync or exact readback was not verified. Do not create another
peer in that case: repair and reconcile the source/global agent sets first.

Attach an existing Goal only with an explicit identity decision:

```text
/loopx attach <goal-id> <agent-id>
/loopx attach <goal-id> --new-peer
```

The tool equivalent is `loopx_goal_attach` with the exact `goalId` and, when
needed, `agentId` or `newPeer`. If a start or attach request would replace a
historical binding, the first call returns `switch_required` and performs no
binding mutation. After the user explicitly confirms, the model repeats the
same typed operation with its short-lived `switchConfirmation` token. Tokens
are operation-bound, memory-only, and invalid after expiry, reload, disposal,
or target change.

The model-facing surface contains exactly eleven bounded tools:

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

The only command-local cases are empty `/loopx` and exact `/loopx version`:

```text
/loopx
/loopx version
```

Empty `/loopx` retains the local status/help response. Exact `/loopx version`
returns only the installed `dsh-loopx-plugin` package version and does not
invoke the LoopX CLI or read Session state. `version` with additional text,
plus `status`, `pause`, `resume`, and `detach`, enters the semantic path above.
The corresponding typed operations keep Host state separate from live LoopX
authority: pause and detach do not complete, pause, delete, or otherwise
rewrite the Goal or its Todos, while resume revalidates the exact binding and
refetches the task body before arming a new generation.

At an idle boundary the driver asks LoopX quota whether the exact lane should
run. It reuses one turn identity for at most one certain, retryable quota
retry. Scheduler hints produce one per-Session timer and become quiet at the
unchanged limit. Only a LoopX-validated terminal closure stops without another
follow-up. Human input or another command preempts the automatic lane and
pauses that binding with a generation fence.

## Remove

```bash
dsh plugin --profile web remove dsh-loopx-plugin
dsh --profile web --dump-config
```

Removal deletes the bundle layer only. It does not delete LoopX state and v1
does not implicitly purge the storage-domain sidecar. Reinstalling still
performs Session lifecycle checks and cold-restores any formerly armed row as
paused, requiring an explicit `/loopx resume`.

## Authority and privacy boundary

- `ctx.loopx` is isolated from DSH `ctx.goals`; installing this bundle neither
  reads nor mutates the DSH Goal service.
- LoopX is authoritative for Goal, Todo, quota, status, evidence, scheduler,
  and terminal facts. DSH stores only Session identity, exact Goal/agent ids,
  Host locators, driver generation, scheduler hint bookkeeping, and lifecycle
  reason in its private sidecar.
- Goal text and task bodies are not copied into the Host sidecar or published
  as LoopX evidence. Routed command/checkpoint content still follows normal DSH
  Session persistence. Raw CLI stdout/stderr, environment values, credentials,
  and tool logs are not projected into model output.
- Installing the bundle grants only the typed LoopX operations against derived
  authoritative locators. It grants no arbitrary filesystem path, argv, shell,
  network, credential, production, or cross-Session authority.

## v1 limits

The supported runbook is the DSH `web` profile on one protected local Host.
There is no Client-plane UI row, automatic sidecar purge, cross-machine
scheduler, shared multi-process storage-root coordination, or migration from
the external `deepseek-harness` / `dsh` LoopX Turn adapter.

Existing control words remain usable through the semantic `/loopx` entry;
connected projects and the prior five tools remain compatible. Six typed
start/attach/detach/driver/Todo-add operations are additive. This
plugin requires the documented guided-connect,
planning, refresh-state, and bootstrap-result schema versions; use a compatible
local LoopX CLI or remove the plugin to roll back. Removing it does not
reinterpret or migrate authoritative LoopX state.

See the canonical
[DeepSeek Harness native plugin integration guide](https://github.com/huangruiteng/loopx/blob/main/docs/integrations/deepseek-harness-native-plugin.md)
and the separate
[external DeepSeek Harness connector](https://github.com/huangruiteng/loopx/blob/main/docs/integrations/deepseek-harness-connector.md).
