# DSH LoopX Goal-Round Continuation Design

**Date:** 2026-08-20

**Status:** Confirmed; awaiting implementation authorization

## Goal and scope

Make a LoopX Goal in a live DSH Session continue with the same predictable
behavior as DSH's native same-session Goal rounds, while preserving LoopX's
stronger Todo, quota, evidence, terminal, and Host-binding boundaries.

The change removes two avoidable interruption points:

1. a successful Goal start must not remain indefinitely in `planning` merely
   because the initiating model turn omitted `loopx_goal_activate`;
2. an ordinary user message must temporarily take priority without permanently
   pausing an otherwise valid LoopX continuation.

Success means:

- a newly started planning binding receives at most one automatic planning-only
  recovery round when the initiating turn did not activate it;
- an active automatic round yields to queued human work without treating the
  human message as a durable pause request;
- every planning and delivery follow-up is rejected before model admission when
  its exact Session, Goal, agent, generation, message, or lifecycle authority is
  stale;
- restart, Session resume, fork, and plugin reload continue to require explicit
  re-arming;
- LoopX remains the sole authority for Goal, Todo, quota, status, evidence,
  scheduler, and terminal facts.

This design is a DSH Host integration change. It builds on the semantic entry
contract in
`docs/superpowers/specs/2026-08-19-dsh-loopx-semantic-entry-design.md`.

### Non-goals

- No Python core, CLI schema, quota algorithm, heartbeat prompt, or external
  adapter change.
- No use of or synchronization with DSH `ctx.goals`.
- No cross-process scheduler, daemon, lease service, or unattended cold-start
  recovery.
- No persistent automatic-execution authority.
- No direct transition from fresh start to delivery before Todo writeback and
  activation readback.
- No repeated planning loop, hidden planning model, new Session, fork, or
  subagent.
- No change to LoopX's terminal, evidence, spend, or Todo semantics.

## Existing context and verified facts

- `LoopXContinuationDriver` already watches the exact live DSH Agent, evaluates
  `quota should-run` at idle, obtains the authoritative task body, and queues a
  plugin-owned `agent.followup(...)` for the same Session.
- The driver already uses Session/Goal/agent/generation fences, bounded quota
  retry, local scheduler timers, terminal observation, and fail-closed pause or
  uncertain transitions.
- The driver currently considers only `active_armed` bindings runnable.
  `planning` therefore has no recovery path after the initiating model turn.
- `LoopXService.start(...)` already returns a bounded
  `dsh_loopx_planning_checkpoint_v0` containing the exact Goal and agent ids,
  Todo tool, Todo bounds, activation tool, activation arguments, and forbidden
  paths.
- `LoopXService.activate(...)` already verifies planning writeback with
  suppressed external sinks, rereads the exact activation binding, obtains the
  task body, and only then transitions the Host binding to `active_armed`.
- The current driver treats every non-owned user message or command as foreign
  input and persistently pauses an armed binding.
- DSH's native Goal mode separates durable Goal phase from process-local
  continuation activation. Its goal-round driver waits for Agent idle, flushes
  durable mutations, reserves one exact Goal round, calls
  `agent.followup(...)`, and validates the reservation around `agent/pre-step`.
- DSH native Goal activation is deliberately absent from replay. Resume, fork,
  or driver replacement preserves durable Goal history but requires a later
  human-authorized resume before automatic work restarts.

**Inference:** the missing behavior is not a LoopX control-plane deficiency.
It is a Host admission gap between an already-valid planning checkpoint and the
existing active continuation driver.

## Confirmed decisions

| Decision | Confirmed choice | Rationale |
| --- | --- | --- |
| Start-to-continuation bridge | Grant one process-local planning-only recovery opportunity after a successful start. | Removes the planning dead zone without authorizing delivery before Todo and activation validation. |
| Planning retry limit | Admit at most one automatic planning recovery round per exact planning generation. | Covers an omitted activation call without creating an infinite planning loop. |
| Planning accounting | Planning recovery does not call delivery quota or spend delivery quota. | It only completes the already-authorized planning checkpoint. |
| Ordinary user input | Temporarily yield, then reread binding and quota after the human turn. | Matches native Goal ergonomics while retaining LoopX as the state authority. |
| Admitted automatic work | Remove queued automatic work before admission; allow claimed/admitted work to settle before the human turn. | Avoids cancelling after partial tool effects and manufacturing uncertain outcomes. |
| Commands and failures | Explicit commands, lifecycle loss, stale readback, and uncertain effects retain fail-closed behavior. | These are authority or integrity transitions, not ordinary conversation. |
| Cold lifecycle | Never inherit automatic authority across Session resume/fork, plugin reload, or DSH restart. | Matches DSH Goal activation and prevents an old authorization from starting work in a new process lifecycle. |
| Core ownership | Keep the change inside `packages/dsh-loopx-plugin`; do not change Python core. | Existing CLI contracts already expose every authoritative fact the Host needs. |

## Design

### Two continuation lanes

The driver owns two distinct Host admission lanes over the same exact binding:

```text
planning binding
  -> at most one planning-only follow-up
  -> Todo writeback + loopx_goal_activate
  -> active_armed binding
  -> quota-gated delivery follow-ups
```

The planning lane is not an early delivery lane. It may present only the
already-produced planning checkpoint and its typed tool obligations. It must
not call `quota should-run`, fetch or execute a delivery task body, write spend,
or infer that planning succeeded.

The delivery lane remains unchanged in authority: only an exact
`active_armed` binding may enter quota evaluation and receive a heartbeat task
body.

### Planning-only recovery authority

A successful `start(...)` stores the rendered planning checkpoint only in
process memory, keyed by the exact Session and binding generation. Goal text or
the rendered checkpoint must not be added to the Host binding sidecar.

When the initiating Agent becomes idle:

1. if the binding has already become `active_armed`, discard the cached
   planning body and use the ordinary quota path;
2. if the binding is still the exact `planning` generation and no planning
   recovery has been admitted, queue one plugin-owned planning follow-up;
3. if no exact in-memory planning body exists, do nothing and require explicit
   user continuation;
4. if the planning follow-up is admitted and the Agent later returns to idle
   with the same generation still in `planning`, mark that generation's
   automatic recovery exhausted and remain quiet;
5. if activation succeeds, generation changes and the ordinary armed driver
   becomes eligible;
6. if the binding changes, the Session lifecycle changes, or the service is
   disposed, discard the planning authority.

Removing a queued planning follow-up to let a human message run does not consume
the one recovery opportunity. Admission into a model step consumes it. A stale
or downstream-rejected reservation is discarded without automatic retry and
does not mark a newer generation exhausted.

The exhausted state is process-local. The durable planning binding remains
available for explicit semantic continuation, Todo repair, activation, detach,
or switch. It must not be reclassified as terminal or blocked.

### In-memory service contract

The Host service exposes a narrow read for the exact current planning
continuation. Its result must include:

- the exact `LoopXBindingFence`;
- the rendered planning body;
- a discriminator proving it is a planning body rather than a delivery task
  body.

The service returns a bounded failure when the Session is not bound, the phase
is not `planning`, the generation differs, the lifecycle identity differs, or
the in-memory body is absent. It never reconstructs planning text from the
sidecar and never invokes Python merely to replace a lost process-local
authorization.

Implementations may unify the existing task-body cache and the planning cache
behind one internal discriminated entry, but the public service result must not
allow a planning body to pass through the delivery path accidentally.

### Follow-up identity and pre-step fence

Every automatic message carries:

- one fresh DSH message id;
- plugin-owned source attribution;
- the exact binding generation;
- a lane discriminator: `planning` or `delivery`;
- a local phase: `queued`, `claimed`, or `admitted`.

The driver adds an `agent/pre-step` listener modelled on DSH's native Goal
round driver. Before delegating downstream and again after downstream returns,
it validates:

- the message id, source, content, and lane match the current reservation;
- the exact Agent object is still the live registry entry;
- the Session identity and driver epoch are current;
- the Goal id, agent id, and generation still match;
- `planning` messages still target `planning`, while delivery messages still
  target `active_armed`;
- plugin/service teardown has not begun.

If validation fails, reject only the stale plugin-owned automatic message and
restore any unrelated claimed messages to the DSH inbox in their original
order. Do not let a stale automatic body enter model history. Do not mutate
LoopX Goal or Todo state merely because admission was rejected.

### Human-input yielding

Ordinary human input is competing work, not an implicit LoopX pause command.

When a non-owned user message arrives:

- if the automatic follow-up is still queued, remove it and clear the local
  reservation so the human message wins;
- if the automatic follow-up is claimed or admitted, do not cancel the running
  Agent solely because of the new message; allow the bounded automatic round to
  settle and leave the human message queued for the next turn;
- while any competing human next-turn input is pending, do not reserve another
  automatic follow-up;
- after the human turn settles and the Agent becomes idle, reread the exact
  binding;
- if it is `active_armed`, run a fresh `quota should-run` with a new turn id;
- if it is `planning` and its one recovery opportunity remains, the planning
  lane may run;
- if it is paused, uncertain, terminal, detached, switched, or stale, remain
  quiet.

No semantic inference is performed by the driver. If the human message intends
pause, detach, switch, Todo mutation, or status inspection, the main model uses
the existing typed tools and those mutations determine the subsequent binding.

Direct DSH command execution remains a strong boundary. `command/run`, Session
dispose, Agent dispose, service unload, explicit driver pause, detach, switch,
readback failure, and outcome uncertainty retain their existing cancellation or
fail-closed behavior.

### Lifecycle and restart behavior

Planning recovery and delivery activation are valid only for the current live
DSH lifecycle.

- Loading the driver over an existing live Agent does not inherit either lane.
- `agent/session-start` disarms inherited automatic authority.
- Session or Agent disposal drains accepted work and leaves the binding
  non-armed according to the existing lifecycle transition.
- Cold restoration never recreates a missing planning body and never turns an
  earlier `active_armed` row back into armed.
- A human may express continue/resume in natural language or use `/loopx
  resume`; the existing typed resume operation rereads authoritative LoopX
  state before arming.

DSH Schedule, background jobs, persistent terminals, and subagents are not used
as substitutes for this lifecycle. They do not own LoopX quota or cold-session
wakeup authority.

### Compatibility and authority boundaries

- Existing `/loopx` semantic routing and all eleven typed tool names remain
  compatible.
- Existing active quota, timer, terminal, bounded retry, and scheduler behavior
  remains unchanged after activation.
- Planning still requires at least one accepted Todo and exact activation
  readback; recovery does not lower that gate.
- `ctx.loopx` and `ctx.goals` remain fully isolated.
- The sidecar continues to store only Host binding and race-control metadata.
- No raw CLI output, Goal text, task body, local path, credential, private
  state, or model transcript enters the sidecar or public evidence.

## Failure behavior

| Condition | Required behavior |
| --- | --- |
| Planning body absent after cold restore | Stay in planning without automatic follow-up; require explicit continuation. |
| Planning generation changes before admission | Reject the stale message and discard its local reservation. |
| Planning follow-up admitted but activation omitted | Exhaust automatic planning recovery and remain quiet. |
| Planning write outcome uncertain | Preserve existing uncertain/fail-closed service transition; never retry automatically. |
| Human message arrives before automatic claim | Remove the queued automatic message and let the human turn run first. |
| Human message arrives after automatic admission | Let the bounded automatic round settle, then run the queued human turn. |
| Explicit command or lifecycle disposal | Preserve strong cancellation/disarm semantics. |
| Binding changes during human or automatic work | Old generation cannot schedule, admit, pause, or resume the new binding. |
| Quota read fails with a determined retryable outcome | Preserve the existing same-turn bounded retry. |
| Quota or write outcome is uncertain | Mark uncertain and stop automatically. |

## Testing and acceptance

### Focused driver and service coverage

Required automated cases:

1. Start remains planning at idle and queues exactly one planning follow-up.
2. Activation in the initiating turn queues no planning recovery and enters the
   ordinary quota path.
3. An admitted planning recovery that returns to idle still in planning does
   not queue a second recovery.
4. Removing a queued planning recovery for a human message preserves the one
   recovery opportunity.
5. Planning recovery never calls quota, task-body delivery, or spend.
6. Missing in-memory planning content after cold restore remains quiet.
7. Pre-step validation rejects stale planning and delivery generations before
   model admission and preserves unrelated claimed messages.
8. A human message arriving before claim runs before automatic work.
9. A human message arriving after admission does not cancel the admitted
   automatic round and runs next.
10. After the human turn, an unchanged armed binding receives a fresh quota
    decision and may continue.
11. Pause, detach, switch, terminal, uncertain, Session dispose, Agent dispose,
    and reload prevent automatic recovery.
12. A queued old-generation pause or failure transition cannot affect a newer
    binding.

### Package acceptance

Run focused validation from `packages/dsh-loopx-plugin`, followed by package
and repository boundary checks:

```bash
pnpm exec vitest run tests/driver.spec.ts tests/service.spec.ts
pnpm typecheck
pnpm test
pnpm build
pnpm pack --pack-destination <temporary-directory>
node smoke/dsh-profile-smoke.mjs --package-path .
node smoke/dsh-profile-smoke.mjs --tarball <temporary-tgz>
git diff --check
loopx canary premerge --from-git-diff
```

The implementation review must also scan candidate files for generated `lib/`,
package archives, private state, raw logs, local absolute paths, credentials,
and accidental `ctx.goals` access. Python tests are not introduced for this
delta because Python core is outside its write set.

## Implementation plan

### Task dependencies

| ID | Task | Direct dependencies | Parallel with | Handoff |
| --- | --- | --- | --- | --- |
| T1 | Freeze planning continuation service contract | — | — | Exact in-memory planning-body read with focused service tests |
| T2 | Implement driver admission and human yielding | T1 | — | Complete planning/delivery race state machine with focused driver tests |
| T3 | Update documentation and packaged smoke | T2 | — | Public runbook and assembled profile assertions match runtime behavior |
| T4 | Integrate and run full acceptance | T3 | — | Reviewed diff and complete validation evidence |

Tasks may begin only after their direct dependencies pass focused validation.
The driver, shared types, and service contract are sequential shared writes;
parallel edits to them are not allowed.

### T1: Freeze the planning continuation service contract

**Goal:** Give the driver one exact, process-local planning body without adding
authoritative or persisted state.

**Files:**

- Modify: `packages/dsh-loopx-plugin/src/types.ts` — narrow planning
  continuation result/API.
- Modify: `packages/dsh-loopx-plugin/src/service.ts` — cache, read, invalidate,
  and dispose exact planning bodies.
- Modify: `packages/dsh-loopx-plugin/tests/service.spec.ts` — service lifecycle,
  generation, absence, and cold-restore cases.
- Do not touch: Python files, `src/driver.ts`, external adapters, or `ctx.goals`.

**Changes:**

- Cache the rendered planning checkpoint by exact Session generation after a
  successful start.
- Expose a read that returns the planning discriminator, exact fence, and body.
- Invalidate it on activation, detach, switch, Session dispose, service dispose,
  lifecycle mismatch, and generation change.
- Never persist the body or reconstruct it from sidecar fields.
- Preserve all existing start and activation result contracts.

**Handoff:** A frozen Host service API that T2 can consume without changing
LoopX CLI contracts.

**Done when / validation:** Focused service tests and package typecheck pass.

### T2: Implement Goal-style continuation admission

**Goal:** Add one-shot planning recovery, pre-step fencing, and ordinary human
message yielding while preserving active quota behavior.

**Depends on / mode:** Begins only after T1 passes. This task owns all driver
state-machine writes.

**Files:**

- Modify: `packages/dsh-loopx-plugin/src/driver.ts` — planning lane,
  reservation identity, pre-step validation, and competing-input behavior.
- Modify: `packages/dsh-loopx-plugin/tests/driver.spec.ts` — focused race and
  lifecycle matrix.
- Do not touch: service/type contracts frozen by T1, Python files, command/tool
  semantics, or external adapters.

**Changes:**

- Generalize the automatic reservation to carry planning/delivery lane and
  queued/claimed/admitted state.
- Admit at most one planning recovery per exact generation and count it only
  when it enters a model step.
- Install before/after `agent/pre-step` validation and restore unrelated claimed
  messages when rejecting a stale automatic reservation.
- Replace ordinary-message persistent pause with competing-input yield.
- Remove only queued owned follow-ups; never cancel admitted work solely because
  a human message arrived.
- Reenter planning or fresh quota evaluation only after human work settles and
  every lifecycle/fence condition is current.
- Preserve explicit command, terminal, uncertainty, disposal, reload, and
  bounded quota retry behavior.

**Handoff:** A complete live-Session continuation driver whose behavior is
covered by semantic and mutation race tests.

**Done when / validation:** Driver tests, combined service/driver tests, and
package typecheck pass with no stale-message admission or duplicate planning
recovery.

### T3: Update documentation and assembled smoke

**Goal:** Make the shipped behavior and its cold-lifecycle limit discoverable
without expanding the product scope.

**Depends on / mode:** Begins only after T2 behavior and names are stable.

**Files:**

- Modify: `packages/dsh-loopx-plugin/README.md` — concise live continuation and
  restart behavior.
- Modify: `docs/integrations/deepseek-harness-native-plugin.md` — user-facing
  start, planning recovery, interruption, and resume runbook.
- Modify: `packages/dsh-loopx-plugin/smoke/dsh-profile-smoke.mjs` only when an
  existing assertion must change or a durable assembled behavior is otherwise
  uncovered.
- Do not touch: README first viewport, Python docs, generated output, or private
  evidence.

**Changes:**

- Explain that start may receive one planning-only recovery round before normal
  quota continuation.
- Explain that ordinary messages temporarily yield, while explicit commands and
  lifecycle changes stop automatic work.
- State that DSH restart and Session resume require explicit LoopX resume.
- Keep LoopX/DSH/sidecar authority and privacy boundaries unchanged.

**Handoff:** Public-safe documentation and assembled profile expectations that
match the implementation.

**Done when / validation:** Focused package tests, build, package-path smoke, and
tarball smoke pass; first-screen review is not triggered.

### T4: Integration review and acceptance

**Goal:** Verify the complete delta, boundary discipline, and compatibility
before any commit, push, or PR gate.

**Depends on / mode:** Begins only after T3 passes. Review every changed path
before running full acceptance.

**Files:**

- Modify: none unless integration reveals a defect within the confirmed write
  sets; route fixes back to the owning task.
- Do not touch: Python core, external adapters, generated `lib/`, package
  archives, local state, or unrelated semantic-entry work.

**Changes:**

- Review the service cache lifecycle and driver race matrix against this design.
- Confirm planning never reaches delivery quota before activation.
- Confirm ordinary messages do not persist a pause and explicit boundaries
  still do.
- Confirm no old generation can affect a new binding.
- Run package build/pack/profile smoke, diff checks, public/private scans, and
  risk-based LoopX premerge validation.

**Handoff:** An implementation-ready validation packet stopped before commit,
push, or PR unless separately authorized.

**Done when / validation:** Every acceptance command passes, or an exact
external/permission gate is recorded without weakening the contract.

### Plan self-check

- The dependency graph is acyclic and lists direct dependencies only.
- Shared service/type/driver writes are sequenced rather than parallelized.
- Every confirmed requirement and non-goal has a task owner.
- Python core and external adapters remain outside all write sets.
- Every task has a reviewable handoff and proportionate validation.
- The plan introduces no persistent automatic authority, duplicate LoopX truth,
  implementation code dump, or speculative scheduler.
