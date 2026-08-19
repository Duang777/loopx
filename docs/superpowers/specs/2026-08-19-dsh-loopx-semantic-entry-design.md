# DSH LoopX Single-Turn Semantic Entry Design

**Date:** 2026-08-20

**Status:** Confirmed design and implementation plan

**Scope:** `packages/dsh-loopx-plugin` command entry only, plus focused tests and usage documentation

## Summary

Every task-bearing `/loopx <original text>` request enters the current DSH
Session in the same way. The plugin queues one plugin-owned follow-up containing
the user's original text and a compact routing instruction. The existing main
DSH model then reasons once and uses the registered `loopx_*` tools, in any
valid combination, to satisfy the request.

There is no hidden classification turn, second model, plugin-owned semantic
classifier, or plugin-owned Session runtime. DSH continues to own the Session,
Inbox, model turn, delivery, and recovery lifecycle. LoopX remains the sole
authority for Goal, Todo, quota, status, evidence, and terminal state.

The command keeps only two local exceptions:

- exact `/loopx version` returns the installed plugin version;
- empty `/loopx` returns the existing local status/help response.

All other non-empty suffixes, including words such as `start`, `attach`,
`status`, `pause`, `resume`, and `detach`, use the same semantic follow-up path.

## Pre-change Source Facts

- The package already registers eleven bounded tools:
  `loopx_goal_start`, `loopx_goal_attach`, `loopx_goal_activate`,
  `loopx_status`, `loopx_goal_detach`, `loopx_driver_pause`,
  `loopx_driver_resume`, `loopx_todo_add`, `loopx_todo_claim`,
  `loopx_todo_update`, and `loopx_todo_complete`.
- Each tool derives the current DSH Session identity, validates a closed input
  schema, calls the shared LoopX service, and validates authoritative readback.
- Before this semantic-entry change, the command implementation bypassed those
  tools for command-shaped input and treated every other non-control suffix as
  a direct Goal start.
- DSH `agent.followup(...)` queues an ordinary message in the same Session and
  wakes the existing main Agent. It does not create another Agent or model.
- The command event itself is not a model-visible message, so a follow-up is
  required for the original `/loopx` text to reach the main model.

## Goals

1. Give new and already-bound Sessions one predictable semantic `/loopx`
   entry.
2. Preserve the user's original text for the main model instead of reducing it
   to a plugin-side intent guess.
3. Reuse the existing eleven typed tools and their service/readback contracts.
4. Keep new-Session Goal selection simple: attach only to an explicitly named
   Goal id; otherwise start a new Goal.
5. Keep an existing binding unless the user explicitly names a different exact
   Goal id and asks to switch, or explicitly asks to detach the current binding.
6. Keep the implementation localized, reversible, and independent of Python
   core changes.

## Non-goals

- No keyword, regular-expression, substring, embedding, or plugin-owned LLM
  classifier.
- No hidden preliminary model turn and no second semantic-routing model.
- No hard cross-turn tool restriction, tool guard, or catalog-disposer
  lifecycle.
- No plugin-owned Session, Inbox, admission, quarantine, ACK, tombstone,
  replay, wake, or crash-recovery state machine.
- No fuzzy Goal lookup, Goal-title search, or inference of a Goal id from
  prose.
- No direct shell, arbitrary argv, raw LoopX CLI, or registry-edit path for the
  model.
- No change to Python CLI contracts, the external `deepseek-harness`/`dsh`
  adapter, service transitions, driver scheduling, or LoopX authority.
- No access to or synchronization with `ctx.goals`.

## Confirmed Behavior

### One semantic turn

```text
/loopx <original text>
          |
          v
plugin-owned same-Session follow-up
  - verbatim original suffix
  - compact LoopX routing policy
          |
          v
current DSH main model (one ordinary turn)
          |
          v
registered loopx_* tool call(s)
          |
          v
LoopX service -> fixed CLI contract -> authoritative readback
```

The follow-up turn is the semantic analysis turn. The plugin does not first ask
another model to classify the request.

### Runtime instruction

The plugin does not copy eleven tool names or schemas into every message. Tool
registration is the catalog source of truth and already exposes names,
descriptions, and parameter schemas to the model.

The fixed instruction refers to the registered `loopx_*` tool family and
states these rules:

1. Complete the quoted user request through the registered `loopx_*` tools;
   do not invoke a raw LoopX CLI or edit registries.
2. If the Session is unbound, attach only when the user explicitly supplied a
   Goal id and explicitly requested binding; otherwise start a new Goal from
   the original request.
3. If the Session is already bound, keep the current Goal. Switch only when the
   user explicitly supplied a different exact Goal id and requested switching;
   detach only when the user explicitly requested detaching the current binding.
4. Do not guess a Goal id or fuzzy-match an earlier Goal.
5. Tools may be composed in one model turn. If no safe operation can be
   determined, ask the user for clarification without mutating state.

The instruction is semantic guidance, not a machine-enforced exclusive
allowlist. Other DSH tools may remain visible. Mutation safety comes from the
closed LoopX tool schemas, current-Session derivation, generation fences, fixed
CLI arguments, and authoritative readback—not from a cross-turn catalog guard.

This also means the plugin does not mechanically prove that a Goal id passed by
the model appeared explicitly in the user's prose. The existing tools verify
that the id and requested transition are valid in LoopX, while the fixed routing
instruction governs semantic provenance. Enforcing prose-to-argument provenance
would require a separate parser or routing protocol and is intentionally out of
scope.

### Unbound Session

The command layer does not classify start versus attach.

- An explicit request such as “attach Goal `goal-123`” may result in
  `loopx_goal_attach({ goalId: "goal-123" })`.
- Any request without an explicit Goal id and explicit binding intent results
  in a new Goal through `loopx_goal_start`.
- A vague request such as “continue the earlier ER-diagram work” does not
  trigger Goal search or inferred attachment. With no binding, it starts a new
  Goal unless the model must clarify for another safety reason.

The tools and service retain responsibility for identity selection, fresh
agent registration, binding, switch confirmation, and authoritative reread.

### Bound Session

The main model interprets the original request against the current Goal and may
combine status, Todo, activation, pause/resume, detach, or other registered
LoopX operations.

The existing Goal remains selected unless the request explicitly supplies a
different exact Goal id and asks to switch, or explicitly asks to detach the
current binding. Any required switch confirmation continues through the
existing typed tool/service contract.

### Local exceptions

- Exact `version` is answered directly from the installed package manifest and
  queues no follow-up.
- Empty input retains the existing local status/help behavior and queues no
  follow-up.
- `version` with additional text is not the exact local exception; it enters
  the semantic path like every other non-empty request.

## Follow-up Contract

The queued message must:

- use DSH's plugin-owned message attribution;
- remain in the current Session and preserve its lifecycle identity;
- contain the original command suffix without semantic rewriting;
- distinguish the fixed routing instruction from quoted user-controlled text;
- avoid local paths, raw CLI output, credentials, private state, or authority
  claims;
- queue exactly once per accepted command invocation.

If `agent.followup(...)` rejects synchronously, the command returns a bounded
delivery failure. No LoopX mutation has occurred because the command handler
does not call the service before queuing the semantic request.

After a successful queue, normal DSH Session behavior owns admission, model
execution, interruption, persistence, and recovery. The plugin does not add a
parallel delivery ledger.

## Authority and Safety Boundaries

### LoopX authority

LoopX remains the only source of truth for Goal identity and lifecycle, Todo
state, quota decisions, status, evidence, terminal outcomes, agent registration,
and project connection.

### DSH authority

DSH owns the current Session, main model turn, Inbox, tool exposure, message
delivery, interruption, and recovery. The semantic entry uses those existing
facilities instead of recreating them.

### Plugin state

The plugin continues to store only its Host binding/race-control sidecar in
`ctx.loopx`. It does not copy Goal/Todo truth or read/write `ctx.goals`.

### Tool boundary

The semantic instruction is not a security boundary. Every state-changing
operation must still pass through an existing typed tool and the existing
service checks. A model selecting an unrelated tool does not grant that tool
LoopX authority.

## Compatibility and Intentional Change

- Ordinary non-slash user messages retain DSH's normal model/tool-selection
  behavior.
- Exact `/loopx version` and empty `/loopx` retain local handling.
- Task-bearing `/loopx` input intentionally changes from command-side direct
  service calls to same-Session semantic follow-up.
- Existing `start`, `attach`, `status`, `pause`, `resume`, and `detach`
  words remain usable, but the main model now maps them to the corresponding
  typed tools.
- The eleven public tool contracts, service behavior, Python contract, driver,
  package faces, and external adapters remain unchanged.
- No fifth package face or semantic-router module is added.

## Implementation Plan

The command implementation and focused command tests form one coupled behavior
seam and should converge before final validation. Usage documentation may be
updated in parallel against the confirmed routing contract; packaged smoke and
full acceptance follow after those surfaces agree.

### T1 — Replace command-side routing

**Production write set:**

- `packages/dsh-loopx-plugin/src/command.ts`

Work:

1. Keep current Session lifecycle derivation.
2. Keep exact `version` and empty-input status/help handling.
3. Replace all other command parsing/direct service calls with one helper that
   queues a plugin-owned semantic follow-up.
4. Preserve the original suffix and add the compact fixed routing policy.
5. Return a short success acknowledgement after queueing and a bounded failure
   if queueing throws.
6. Delete command-only start/attach/switch rendering and parsing code that no
   longer has an active call site.

Do not touch:

- `src/service.ts`, `src/tools.ts`, `src/driver.ts`, `src/schemas.ts`, or
  `src/types.ts` unless compilation proves a now-unused public import cleanup is
  required in `command.ts` itself;
- Python files or external adapters;
- DSH Session/Inbox internals.

### T2 — Focused semantic-entry tests

**Test write set:**

- `packages/dsh-loopx-plugin/tests/command-tools.spec.ts`

Required cases:

1. Exact `version` returns locally with zero follow-ups and zero service calls.
2. Empty input retains local status/help with zero follow-ups.
3. An unbound natural-language request queues exactly one plugin-owned
   follow-up and performs no direct start/attach/status mutation.
4. A bound natural-language request follows the identical queue path.
5. Former exact controls such as `status`, `pause`, and `attach goal-123` enter
   the semantic path rather than bypassing tools.
6. The original Unicode text and internal whitespace are preserved as quoted
   request data.
7. The follow-up references the registered `loopx_*` catalog without embedding
   a duplicated eleven-name list.
8. A synchronous follow-up failure returns the bounded delivery error and
   performs no service mutation.
9. The command derives and rejects mismatched Agent/Session lifecycle identity
   before queueing.

Existing semantic-tool tests continue to prove the eleven schemas and tool to
service boundaries; they do not need a new router harness.

### T3 — Usage documentation

Update only the existing command/semantic-entry paragraphs in:

- `packages/dsh-loopx-plugin/README.md`;
- `docs/integrations/deepseek-harness-native-plugin.md`.

Document the single-turn path, explicit Goal-id rule, local exceptions, and
prompt-guidance versus hard-allowlist boundary. Do not add architecture or
recovery prose. Any README first-screen correction remains subject to the
repository's separate owner-preview gate.

### T4 — Validation

Update only the existing packaged profile smoke assertions that encoded the
old direct-command start/status path. The durable smoke must now prove semantic
follow-up delivery first, then exercise planning through the registered typed
start tool; it must not reintroduce command-side routing.

Run focused validation first, then the existing package acceptance:

```bash
pnpm exec vitest run tests/command-tools.spec.ts tests/semantic-tools.spec.ts
pnpm typecheck
pnpm test
pnpm build
pnpm pack --pack-destination <temporary-directory>
node smoke/dsh-profile-smoke.mjs --package-path .
node smoke/dsh-profile-smoke.mjs --tarball <temporary-tgz>
git diff --check
loopx canary premerge --from-git-diff
```

Python regressions are required only as no-regression evidence for the existing
broader branch; this semantic-entry delta must not create a Python diff.

## Acceptance Criteria

1. Every non-empty `/loopx` suffix except exact `version` queues one and only
   one same-Session semantic follow-up.
2. Empty `/loopx` and exact `/loopx version` queue nothing.
3. The command handler performs no LoopX service mutation for semantic input.
4. The current main DSH model receives the original request and the compact
   routing policy in one ordinary turn.
5. The runtime message does not duplicate the eleven-tool catalog.
6. The fixed instruction tells the model that an unbound request may attach
   only from an explicit Goal id plus binding intent; otherwise it must start a
   new Goal. The plugin does not claim machine-enforced prose provenance.
7. The fixed instruction tells the model to preserve a bound Goal unless a
   different exact Goal id and switching intent are explicit, while explicit
   detach intent may detach the current binding without a Goal id. Existing tool
   and service validation still governs the resulting transition.
8. Ambiguous requests may clarify without mutation; the plugin never fuzzy
   matches a Goal.
9. No semantic router, tool restriction lifecycle, quarantine, ACK, replay, or
   additional persistent state is introduced.
10. The eleven tool contracts and LoopX/DSH/sidecar authority boundaries remain
    unchanged.
11. Focused tests, package tests/build/pack/profile smoke, diff checks, boundary
    scans, and risk-based premerge validation pass or record an exact external
    gate.
12. No generated `lib/`, package tarball, private state, raw log, local path, or
    credential is committed.
