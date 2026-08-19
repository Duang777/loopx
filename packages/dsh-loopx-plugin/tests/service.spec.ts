import { chmod, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import Storage from '@deepseek-ai/dsh-storage'
import * as StorageDomain from '@deepseek-ai/dsh-storage-domain'
import * as StorageJson from '@deepseek-ai/dsh-storage-json'
import { afterEach, describe, expect, it, vi } from 'vitest'
import LoopXService from '../src/service.ts'
import type {
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStartOptions,
  LoopXTodoAddRequest,
} from '../src/types.ts'

interface FakeLoopXState {
  readonly goalId: string
  readonly goals: string[]
  readonly agents: string[]
  readonly bindingGoal: string | null
  readonly bindingAgent: string | null
  readonly taskBody: string
  readonly connectionState?:
    | 'not_connected'
    | 'registry_without_goal'
    | 'registry_invalid'
    | 'registry_goal_missing_state_file'
    | 'state_file_missing'
    | undefined
  readonly bootstrapFailure?: boolean | undefined
  readonly delayCommand?: string | undefined
  readonly delayMs?: number | undefined
  readonly invalidJsonFor?: string | undefined
  readonly registerAgentFailure?:
    | 'collision'
    | 'preflight'
    | 'partial'
    | 'readback-mismatch'
    | undefined
  readonly fineGrained?: boolean | undefined
  readonly todoAddCount?: number | undefined
  readonly todoAddFailureAt?: number | undefined
  readonly todoAddAuthoritativeFailure?: boolean | undefined
  readonly threadBindingAuthoritativeFailure?: boolean | undefined
  readonly refreshFailure?:
    | 'authoritative'
    | 'global-sync'
    | 'suppression'
    | 'partial'
    | 'locator'
    | undefined
}

interface Harness {
  readonly ctx: Context
  readonly root: string
  readonly project: string
  readonly statePath: string
  readonly callsPath: string
  service: LoopXServiceApi
  disposeService(): Promise<void>
  reloadService(): Promise<void>
  readState(): Promise<FakeLoopXState>
  writeState(update: Partial<FakeLoopXState>): Promise<void>
  storageText(): Promise<string>
  dispose(): Promise<void>
}

const fakeLoopXSource = String.raw`#!/usr/bin/env node
import { appendFile, readFile, writeFile } from 'node:fs/promises'

const statePath = process.env.LOOPX_FAKE_STATE
if (!statePath) throw new Error('LOOPX_FAKE_STATE is required')
const args = process.argv.slice(2)
const value = flag => {
  const index = args.indexOf(flag)
  return index === -1 ? undefined : args[index + 1]
}
let index = 0
while (index < args.length) {
  if (['--format', '--registry', '--runtime-root'].includes(args[index])) index += 2
  else break
}
const command = args[index]
const subcommand = command === 'todo' || command === 'quota' ? args[index + 1] : undefined
const key = subcommand ? command + '-' + subcommand : command
let state = JSON.parse(await readFile(statePath, 'utf8'))
await appendFile(statePath + '.calls', 'start:' + key + '\n')
await appendFile(statePath + '.calls', 'argv:' + JSON.stringify(args) + '\n')
if (state.delayCommand === key) {
  await new Promise(resolve => setTimeout(resolve, state.delayMs ?? 25))
}

const selectedGoal = value('--goal-id') ?? value('--fork-goal')
const goalId = selectedGoal ?? state.goalId
const threadId = value('--thread-id')
const project = value('--project') ?? process.cwd()
const requestedAgent = value('--agent-id')
const newPeer = args.includes('--new-peer')
const binding = state.bindingAgent === null || state.bindingGoal !== goalId
  ? { status: 'missing', agent_id: null }
  : { status: 'bound', agent_id: state.bindingAgent }
const selectionGate = defaultAction => ({
  schema_version: 'loopx_host_loop_identity_selection_v0',
  default_action: defaultAction,
  reason: 'Select an exact LoopX agent lane.',
  choices: state.agents.map(agent_id => ({ agent_id })),
  ...(defaultAction === 'register_fresh_agent'
    ? { fresh_agent_registration: { agent_id: '<new-public-safe-agent-id>' } }
    : { fresh_agent_registration: null }),
})
const goalStartContract = goalText => ({
  schema_version: 'loopx_goal_start_command_v0',
  goal_text: goalText,
  planner: {
    required_before_todo_write: true,
    default_profile: 'open_ended_product_direction',
    profile_selection: 'Choose the profile that matches the bounded objective.',
    profiles: {
      open_ended_product_direction: {
        suggested_items_min: 2,
        suggested_items_max: 5,
        intent: 'Rank public-safe work before execution.',
      },
      clear_bounded_problem: {
        item_count_policy: 'planner_sized',
        may_reuse_current_todo_when_it_already_represents_the_plan: true,
        intent: 'Use the minimum sufficient explicit plan.',
      },
    },
    allowed_priorities: ['P0', 'P1', 'P2'],
    default_role: 'agent',
    default_task_class: 'advancement_task',
    required_fields: ['priority', 'text', 'task_class', 'action_kind'],
    public_safe_only: true,
    budget_policy: 'minimum sufficient plan; no fixed-count filler',
    ...(state.fineGrained
      ? {
          fine_grained_plan_horizon: 'write one current runnable checkpoint',
          maximum_runnable_todos_written_ahead: 1,
        }
      : {}),
  },
  activation: { host_loop_required_after_todo_writeback: true },
  stop_conditions: [
    'private material is required',
    'credentials or destructive authority are required',
  ],
})

const connectionState = state.connectionState
  ?? (state.goals.includes(goalId) ? 'connected' : 'registry_without_goal')
const connection = {
  project,
  registry: project + '/.loopx/registry.json',
  goal_id: goalId,
  connection_state: connectionState,
}

let output
if (command === 'start-goal') {
  if (selectedGoal === undefined && state.goals.length > 1) {
    const choices = state.goals.map(goal_id => ({ goal_id }))
    output = {
      schema_version: 'loopx_start_goal_guided_v0',
      ok: true,
      read_only: true,
      guided: true,
      project,
      goal_id: null,
      agent_id: null,
      host_surface: 'deepseek-harness-native',
      project_connection: {
        ...connection,
        goal_id: null,
        connection_state: 'goal_selection_required',
      },
      goal_selection_gate: {
        schema_version: 'loopx_goal_selection_gate_v0',
        state: 'selection_required',
        reason: 'Select one exact Goal.',
        choices,
      },
      guided_transaction: {
        schema_version: 'loopx_start_goal_guided_v0',
        blocked_by: 'goal_selection',
        ordered_steps: [{ id: 'inspect', kind: 'read_only' }],
      },
    }
  } else {
  const selected = requestedAgent ?? state.bindingAgent
  const exact = selected !== null && selected !== undefined
    && state.agents.includes(selected)
    && state.bindingGoal === goalId
    && state.bindingAgent === selected
  const gate = exact
    ? undefined
    : selectionGate(
        newPeer || state.agents.length === 0 || (threadId && binding.status === 'missing')
          ? 'register_fresh_agent'
          : 'select_agent_identity',
      )
  output = {
    schema_version: 'loopx_start_goal_guided_v0',
    ok: true,
    read_only: true,
    guided: true,
    project,
    goal_id: goalId,
    agent_id: exact ? selected : null,
    host_surface: 'deepseek-harness-native',
    thread_id: threadId,
    thread_agent_binding: binding,
    project_connection: connection,
    command_pack: {
      schema_version: 'loopx_bootstrap_command_pack_v0',
      goal_start_contract: goalStartContract(value('--goal-text')),
    },
    guided_transaction: {
      schema_version: 'loopx_start_goal_guided_v0',
      ...(gate ? { blocked_by: 'agent_identity_selection', identity_selection_gate: gate } : {}),
      ordered_steps: [
        { id: 'inspect', kind: 'read_only' },
        {
          id: 'connect_if_needed',
          kind: 'conditional_mutation',
          command: 'touch LOOPX_RETURNED_COMMAND_MUST_NOT_RUN',
          connect_contract: {
            schema_version: 'loopx_start_goal_connect_v0',
            operation: 'bootstrap_connect',
            goal_id: goalId,
            objective: value('--goal-text'),
            adapter_kind: 'read_only_project_map_v0',
            adapter_status: 'connected-read-only',
            onboarding_scan_enabled: false,
            fine_grained: false,
          },
        },
        { id: 'plan', kind: 'model_checkpoint', prompt: 'Plan and write the bounded LoopX Todos.' },
      ],
    },
  }
  }
} else if (command === 'bootstrap-command-pack') {
  const selected = (newPeer ? null : requestedAgent)
    ?? state.bindingAgent
    ?? (state.agents.length === 1 ? state.agents[0] : null)
  const allowed = !newPeer && selected !== null && state.agents.includes(selected)
  const activationArguments = { goalId, ...(selected ? { agentId: selected } : {}) }
  output = {
    schema_version: 'loopx_bootstrap_command_pack_v0',
    ok: true,
    read_only: true,
    project,
    goal_id: goalId,
    agent_id: selected,
    agent_type: 'deepseek-harness-native',
    host_surface: 'deepseek-harness-native',
    thread_id: threadId,
    thread_agent_binding: binding,
    project_connection: connection,
    host_loop_activation: {
      schema_version: 'loopx_host_loop_activation_v1',
      agent_type: 'deepseek-harness-native',
      goal_id: goalId,
      agent_id: selected,
      activation_allowed: allowed,
      identity_contract: {
        schema_version: 'loopx_host_loop_identity_selection_v0',
        registered_agents: state.agents,
      },
      identity_selection_gate: allowed
        ? null
        : selectionGate(newPeer ? 'register_fresh_agent' : 'select_agent_identity'),
      host_surface: 'deepseek_harness_native_session',
      activation_method: 'current_session_host_tool',
      activation_input: {
        schema_version: 'loopx_deepseek_harness_native_activation_input_v0',
        tool: 'loopx_goal_activate',
        arguments: activationArguments,
      },
      host_mutation: {
        owner: 'DSH LoopX plugin',
        host_tool: 'loopx_goal_activate',
        current_session_only: true,
        cli_can_mutate_directly: false,
        forbidden_tool_arguments: ['sessionId', 'registryPath', 'taskBody', 'argv'],
      },
    },
  }
} else if (command === 'bootstrap') {
  if (!state.bootstrapFailure) {
    if (!state.goals.includes(goalId)) state.goals.push(goalId)
    state.goalId = goalId
    state.connectionState = undefined
  }
  output = state.bootstrapFailure
    ? {
        schema_version: 'loopx_bootstrap_result_v0',
        ok: false,
        error_kind: 'fixture_bootstrap_failure',
      }
    : {
        schema_version: 'loopx_bootstrap_result_v0',
        ok: true,
        project,
        goal_id: goalId,
        registry: project + '/.loopx/registry.json',
        state_file: project + '/.codex/goals/' + goalId + '/ACTIVE_GOAL_STATE.md',
        registry_goal_action: 'appended',
        state_action: 'created',
        global_sync: { ok: true, synced_goal_ids: [goalId], wrote: true },
      }
} else if (command === 'register-agent') {
  const agent = requestedAgent
  const beforeAgents = [...state.agents]
  const failureMode = state.registerAgentFailure
  if (failureMode === 'collision') {
    output = {
      schema_version: 'loopx_register_agent_v0',
      ok: false,
      goal_id: goalId,
      changed: false,
      written: false,
      partial_write: false,
      error_kind: 'agent_identity_already_registered',
      requested_agents: [agent],
      registered_agents: beforeAgents,
      global_sync: { ok: false, wrote: false, phase: 'preflight' },
      registration_readback: {
        schema_version: 'loopx_agent_registration_readback_v0',
        performed: false,
        verified: false,
      },
    }
  } else if (failureMode === 'preflight') {
    output = {
      schema_version: 'loopx_register_agent_v0',
      ok: false,
      goal_id: goalId,
      changed: false,
      written: false,
      partial_write: false,
      error_kind: 'agent_registration_sync_preflight_failed',
      requested_agents: [agent],
      registered_agents: beforeAgents,
      global_sync: {
        ok: false,
        wrote: false,
        phase: 'preflight',
        error_kind: 'agent_registration_sync_preflight_failed',
      },
      registration_readback: {
        schema_version: 'loopx_agent_registration_readback_v0',
        performed: false,
        verified: false,
      },
    }
  } else {
    const changed = !state.agents.includes(agent)
    if (changed) state.agents.push(agent)
    const partial = failureMode === 'partial'
    const mismatched = failureMode === 'readback-mismatch'
    output = {
      schema_version: 'loopx_register_agent_v0',
      ok: !partial,
      goal_id: goalId,
      changed,
      written: changed,
      partial_write: partial,
      ...(partial ? { error_kind: 'agent_registration_global_sync_failed' } : {}),
      requested_agents: [agent],
      registered_agents: state.agents,
      global_sync: {
        ok: !partial,
        wrote: !partial,
        ...(partial ? { phase: 'commit', error_kind: 'agent_registration_global_sync_failed' } : {}),
      },
      registration_readback: {
        schema_version: 'loopx_agent_registration_readback_v0',
        performed: true,
        verified: !partial,
        requested_agents: [agent],
        source_registered_agents: mismatched ? beforeAgents : state.agents,
        global_registered_agents: partial || mismatched ? beforeAgents : state.agents,
      },
    }
  }
} else if (command === 'bind-agent-thread') {
  const agent = requestedAgent
  const conflict = state.bindingAgent !== null
    && (state.bindingGoal !== goalId || state.bindingAgent !== agent)
  if (!conflict && !state.threadBindingAuthoritativeFailure) {
    state.bindingGoal = goalId
    state.bindingAgent = agent
  }
  output = state.threadBindingAuthoritativeFailure
    ? {
        schema_version: 'loopx_thread_agent_binding_command_v0',
        ok: false,
        goal_id: goalId,
        changed: false,
        written: false,
        error_kind: 'global_registry_write_denied',
      }
    : {
        schema_version: 'loopx_thread_agent_binding_command_v0',
        ok: !conflict,
        goal_id: goalId,
        thread_id: threadId,
        host_surface: 'deepseek-harness-native',
        agent_id: agent,
        changed: !conflict,
        written: !conflict,
        binding: conflict
          ? { schema_version: 'loopx_thread_agent_binding_v0', status: 'conflict', thread_id: threadId, host_surface: 'deepseek-harness-native' }
          : { schema_version: 'loopx_thread_agent_binding_v0', status: 'bound', thread_id: threadId, host_surface: 'deepseek-harness-native', agent_id: agent },
        global_sync: { ok: !conflict },
        registration_readback: { verified: !conflict },
      }
} else if (command === 'unbind-agent-thread') {
  const agent = requestedAgent
  const matches = state.bindingAgent === null
    || (state.bindingGoal === goalId && state.bindingAgent === agent)
  if (matches) {
    state.bindingGoal = null
    state.bindingAgent = null
  }
  output = {
    schema_version: 'loopx_thread_agent_binding_command_v0',
    ok: matches,
    goal_id: goalId,
    thread_id: threadId,
    host_surface: 'deepseek-harness-native',
    agent_id: agent,
    changed: matches,
    written: matches,
    binding: {
      schema_version: 'loopx_thread_agent_binding_v0',
      status: matches ? 'missing' : 'conflict',
      thread_id: threadId,
      host_surface: 'deepseek-harness-native',
      agent_id: null,
    },
    global_sync: { ok: matches },
    registration_readback: { verified: matches },
  }
} else if (command === 'refresh-state') {
  const registry = value('--registry') ?? project + '/.loopx/registry.json'
  const failureMode = state.refreshFailure
  output = failureMode === 'authoritative'
    ? {
        schema_version: 'loopx_refresh_state_result_v0',
        ok: false,
        registry,
        runtime_root: null,
        goal_id: goalId,
        classification: 'progress',
        appended: false,
        dry_run: false,
        error: 'fixture authoritative refresh rejection',
      }
    : {
    schema_version: 'loopx_refresh_state_result_v0',
    ok: failureMode !== 'global-sync',
    dry_run: false,
    appended: true,
    partial_write: failureMode === 'partial',
    registry,
    project: failureMode === 'locator' ? project + '/wrong' : value('--project'),
    goal_id: goalId,
    agent_id: requestedAgent,
    agent_lane: value('--agent-lane'),
    progress_scope: value('--progress-scope'),
    external_sink_delivery_authorized: failureMode === 'suppression',
    global_sync: {
      ok: failureMode !== 'global-sync',
      skipped: false,
      registry,
      global_registry: project + '/runtime/registry.global.json',
      synced_goal_ids: failureMode === 'global-sync' ? [] : [goalId],
      wrote: failureMode !== 'global-sync',
    },
      }
} else if (command === 'heartbeat-prompt') {
  output = {
    schema_version: 'loopx_heartbeat_prompt_v0',
    ok: true,
    goal_id: goalId,
    agent_id: requestedAgent,
    runtime_profile: 'generic_cli',
    task_body: state.taskBody,
  }
} else if (command === 'status') {
  output = {
    schema_version: 'loopx_status_v0',
    ok: true,
    goal_filter: goalId,
    registry: project + '/private-registry.json',
    attention_queue: {
      items: [{
        goal_id: goalId,
        status: 'active',
        waiting_on: 'agent',
        severity: 'normal',
        recommended_action: 'Continue the selected Todo.',
        private_path: project + '/must-not-project',
      }],
    },
  }
} else if (command === 'todo' && subcommand === 'add') {
  state.todoAddCount = (state.todoAddCount ?? 0) + 1
  const role = value('--role')
  const agent = role === 'agent' ? value('--claimed-by') : value('--agent-id')
  const requestedTodo = value('--text')
  const mismatched = state.todoAddFailureAt === state.todoAddCount
  output = state.todoAddAuthoritativeFailure
    ? {
        schema_version: 'loopx_todo_command_v0',
        ok: false,
        dry_run: false,
        added: false,
        already_exists: false,
        goal_id: goalId,
        role,
        todo: requestedTodo,
        error: 'fixture authoritative Todo rejection',
      }
    : {
        schema_version: 'loopx_todo_command_v0',
        ok: true,
        dry_run: false,
        added: true,
        already_exists: false,
        goal_id: goalId,
        role,
        todo: mismatched ? requestedTodo + ' mismatch' : requestedTodo,
        todo_id: 'todo-fixture-' + state.todoAddCount,
        status: 'open',
        task_class: value('--task-class'),
        action_kind: value('--action-kind'),
        claimed_by: role === 'agent' ? agent : null,
        bound_agent: role === 'user' ? value('--bound-agent') : null,
        agent_id: role === 'user' ? agent : null,
        blocks_agent: role === 'user' ? value('--blocks-agent') : null,
        target_key: value('--target-key') ?? null,
      }
} else if (command === 'todo') {
  output = {
    schema_version: 'loopx_todo_command_v0',
    ok: true,
    goal_id: goalId,
    todo_id: value('--todo-id'),
    status: key === 'todo-complete' ? 'done' : value('--status') ?? 'open',
    changed: true,
    dry_run: false,
    state_file: project + '/private-state.md',
  }
} else if (command === 'quota') {
  output = {
    schema_version: 'loopx_quota_should_run_v0',
    ok: true,
    mode: 'should-run',
    goal_id: goalId,
    decision: 'run',
    should_run: true,
    effective_action: 'run_now',
    agent_identity: { agent_id: requestedAgent },
    heartbeat_receipt: {
      schema_version: 'heartbeat_quota_receipt_v0',
      turn_instance_id: value('--turn-instance-id'),
      status: 'committed',
    },
    scheduler_hint: {
      schema_version: 'scheduler_hint_v0',
      source: 'quota.should-run',
      action: 'run_now',
      cadence_class: 'immediate',
      reset_policy: { reset_token: 'reset-1' },
      unchanged_poll: { limits: { local_scheduler: 2 }, after_limits: { local_scheduler: 'pause' } },
      cold_path_detail: {
        schema_version: 'scheduler_hint_detail_v0',
        local_scheduler: {
          recommended_interval_minutes: 3,
          unchanged_poll_limit: 2,
          after_limit: 'pause',
        },
      },
    },
  }
} else {
  output = { schema_version: 'unknown_v0', ok: false }
}

await writeFile(statePath, JSON.stringify(state))
await appendFile(statePath + '.calls', 'end:' + key + '\n')
if (state.invalidJsonFor === key) process.stdout.write('PRIVATE INVALID OUTPUT')
else process.stdout.write(JSON.stringify(output))
`

const cleanups: Array<() => Promise<void>> = []

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(cleanups.splice(0).map(cleanup => cleanup()))
})

async function setupHarness(initial: Partial<FakeLoopXState> = {}): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), 'dsh-loopx-service-test-'))
  const project = join(root, 'project')
  const storageRoot = join(root, 'storage')
  const statePath = join(root, 'fake-state.json')
  const callsPath = `${statePath}.calls`
  const executable = join(root, 'loopx-fixture.mjs')
  await mkdir(project, { recursive: true })
  await mkdir(storageRoot, { recursive: true })
  await writeFile(executable, fakeLoopXSource)
  await chmod(executable, 0o755)
  await writeFile(callsPath, '')
  await writeFile(statePath, JSON.stringify({
    goalId: 'goal-a',
    goals: ['goal-a'],
    agents: ['agent-a'],
    bindingGoal: 'goal-a',
    bindingAgent: 'agent-a',
    taskBody: 'PRIVATE TASK BODY FROM LOOPX',
    ...initial,
  }))

  const ctx = new Context()
  await ctx.plugin(Storage)
  await ctx.plugin(StorageJson, { root: storageRoot })
  await ctx.plugin(StorageDomain, { backend: 'json' })
  let serviceFiber = await ctx.plugin(LoopXService, {
    loopxBin: executable,
    project,
    environment: { LOOPX_FAKE_STATE: statePath },
  })
  let disposed = false
  const harness: Harness = {
    ctx,
    root,
    project,
    statePath,
    callsPath,
    service: ctx.loopx,
    async disposeService() {
      await serviceFiber.dispose()
    },
    async reloadService() {
      serviceFiber = await ctx.plugin(LoopXService, {
        loopxBin: executable,
        project,
        environment: { LOOPX_FAKE_STATE: statePath },
      })
      harness.service = ctx.loopx
    },
    async readState() {
      return JSON.parse(await readFile(statePath, 'utf8')) as FakeLoopXState
    },
    async writeState(update) {
      const current = await harness.readState()
      await writeFile(statePath, JSON.stringify({ ...current, ...update }))
    },
    async storageText() {
      const names = await readdir(storageRoot)
      return (await Promise.all(names.map(name => readFile(join(storageRoot, name), 'utf8')))).join('\n')
    },
    async dispose() {
      if (disposed) return
      disposed = true
      await ctx.fiber.dispose()
      await rm(root, { recursive: true, force: true })
    },
  }
  cleanups.push(harness.dispose)
  return harness
}

function session(project: string, createdAt = 1): LoopXSessionRef {
  return Object.freeze({
    id: 'dsh-session-a',
    identity: Object.freeze({ createdAt, cwd: project }),
  })
}

describe('LoopXService', () => {
  it('stays pending when storage-domain is absent instead of using memory state', async () => {
    const ctx = new Context()
    await ctx.plugin(LoopXService, { loopxBin: 'loopx' })
    expect(ctx.get('loopx')).toBeUndefined()
    await ctx.fiber.dispose()
  })

  it('keeps the two-phase checkpoint and task body in memory and cold-restores disarmed', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    const rawGoal = 'PRIVATE GOAL TEXT THAT MUST NOT PERSIST'

    const started = await harness.service.start(current, rawGoal)
    expect(started).toMatchObject({
      ok: true,
      value: {
        kind: 'planning',
        binding: { phase: 'planning', goalId: 'goal-a', agentId: 'agent-a', generation: 1 },
        planning: {
          schemaVersion: 'dsh_loopx_planning_checkpoint_v0',
          writeback: { minimumTodos: 1, maximumTodos: 5 },
        },
      },
    })
    expect(started.ok && started.value.kind === 'planning'
      ? started.value.modelCheckpoint
      : '').toContain('dsh_loopx_planning_checkpoint_v0')
    expect(started.ok && started.value.kind === 'planning'
      ? started.value.modelCheckpoint
      : '').not.toContain('LOOPX_RETURNED_COMMAND_MUST_NOT_RUN')
    const planning = harness.service.getBinding(current)
    expect(planning.ok && planning.value?.phase).toBe('planning')
    expect(planning.ok && Object.isFrozen(planning.value)).toBe(true)
    expect(harness.service.getBinding(session(harness.project, 2))).toEqual({ ok: true, value: undefined })

    await expect(harness.service.activate(current, 'goal-a', 'agent-b')).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_IDENTITY_CONFLICT' },
    })
    await expect(harness.service.todoAdd(current, {
      text: 'Implement the bounded checkpoint',
      priority: 'P0',
    })).resolves.toMatchObject({
      ok: true,
      value: {
        status: 'open',
        role: 'agent',
        priority: 'P0',
      },
    })
    const activated = await harness.service.activate(current, 'goal-a', 'agent-a')
    expect(activated).toMatchObject({
      ok: true,
      value: { phase: 'active_armed', generation: 2 },
    })
    const firstBody = await harness.service.taskBody(current, 2)
    expect(firstBody).toMatchObject({
      ok: true,
      value: { body: 'PRIVATE TASK BODY FROM LOOPX' },
    })
    const activationCalls = (await readFile(harness.callsPath, 'utf8')).trim().split('\n')
    const refreshArgv = activationCalls
      .filter(line => line.startsWith('argv:'))
      .map(line => JSON.parse(line.slice(5)) as string[])
      .find(values => values.includes('refresh-state'))
    expect(refreshArgv).toEqual([
      '--format', 'json',
      '--registry', join(harness.project, '.loopx', 'registry.json'),
      'refresh-state',
      '--goal-id', 'goal-a',
      '--project', harness.project,
      '--agent-id', 'agent-a',
      '--agent-lane', 'agent-a',
      '--progress-scope', 'agent_lane',
      '--suppress-external-sinks',
    ])
    await harness.writeState({ taskBody: 'REFRESHED PRIVATE TASK BODY' })
    await expect(harness.service.taskBody(current, 2)).resolves.toMatchObject({
      ok: true,
      value: { body: 'PRIVATE TASK BODY FROM LOOPX' },
    })
    await expect(harness.service.taskBody(current, 2, true)).resolves.toMatchObject({
      ok: true,
      value: { body: 'REFRESHED PRIVATE TASK BODY' },
    })

    const storageBefore = await harness.storageText()
    expect(storageBefore).not.toContain(rawGoal)
    expect(storageBefore).not.toContain('PRIVATE TASK BODY')
    expect(storageBefore).not.toContain('REFRESHED PRIVATE TASK BODY')

    const paused = await harness.service.pause(current)
    expect(paused).toMatchObject({ ok: true, value: { phase: 'active_paused', generation: 3 } })
    const resumed = await harness.service.resume(current)
    expect(resumed).toMatchObject({ ok: true, value: { phase: 'active_armed', generation: 4 } })
    await harness.disposeService()
    await harness.reloadService()
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: {
        phase: 'active_paused',
        reason: 'cold_restore',
        generation: 5,
      },
    })
  })

  it('uses producer-equivalent Goal whitespace normalization for connected planning', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)

    const started = await harness.service.start(current, '  Plan\tthis\nconnected   Goal  ')

    expect(started).toMatchObject({
      ok: true,
      value: {
        kind: 'planning',
        planning: { goalText: 'Plan this connected Goal' },
      },
    })
    const calls = (await readFile(harness.callsPath, 'utf8')).trim().split('\n')
    const startArgv = calls
      .filter(line => line.startsWith('argv:'))
      .map(line => JSON.parse(line.slice(5)) as string[])
      .find(values => values.includes('start-goal'))
    expect(startArgv?.[startArgv.indexOf('--goal-text') + 1]).toBe('Plan this connected Goal')
  })

  it('rejects incompatible identity selections and invalid Todo adds before invoking LoopX', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    await expect(harness.service.attach(current, { goalId: 'goal-a' }))
      .resolves.toMatchObject({ ok: true, value: { kind: 'attached' } })
    const bindingBefore = harness.service.getBinding(current)
    const callsBefore = await readFile(harness.callsPath, 'utf8')

    const incompatibleStarts: readonly LoopXStartOptions[] = [
      { agentId: 'agent-a', newPeer: true },
      { goalId: 'goal-a', newIndependent: true },
      { agentId: 'agent-a', newIndependent: true },
    ]
    for (const options of incompatibleStarts) {
      await expect(harness.service.start(current, 'Keep the current binding', undefined, options))
        .resolves.toMatchObject({
          ok: false,
          error: { code: 'LOOPX_INVALID_REQUEST', outcomeUncertain: false },
        })
    }
    await expect(harness.service.attach(current, {
      goalId: 'goal-a',
      agentId: 'agent-a',
      newPeer: true,
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_INVALID_REQUEST', outcomeUncertain: false },
    })

    const uncheckedTodo = (request: object): LoopXTodoAddRequest => (
      request as unknown as LoopXTodoAddRequest
    )
    const invalidTodos: readonly LoopXTodoAddRequest[] = [
      { text: '', priority: 'P0' },
      { text: 'x'.repeat(1001), priority: 'P0' },
      { text: '[P0] priority must stay typed', priority: 'P0' },
      { text: 'control\ncharacter', priority: 'P0' },
      uncheckedTodo({
        text: 'Unknown fields stay closed',
        priority: 'P0',
        registryPath: 'not-accepted',
      }),
      uncheckedTodo({ text: 'Priority must stay typed', priority: 'P3' }),
      uncheckedTodo({ text: 'Role must stay typed', priority: 'P0', role: 'system' }),
      { text: 'Blank action is not an action', priority: 'P0', actionKind: '   ' },
      { text: 'Owner gate with a target', priority: 'P0', role: 'user', targetKey: 'owner:gate' },
      { text: 'Invalid action kind', priority: 'P1', actionKind: 'Not Valid!' },
      { text: 'Blank target is not a target', priority: 'P1', targetKey: '   ' },
      { text: 'Invalid target key', priority: 'P1', targetKey: 'Not Valid!' },
    ]
    for (const request of invalidTodos) {
      await expect(harness.service.todoAdd(current, request)).resolves.toMatchObject({
        ok: false,
        error: { code: 'LOOPX_INVALID_REQUEST', outcomeUncertain: false },
      })
    }
    await expect(harness.service.todoAdd(current, {
      text: 'A valid Todo is still forbidden after activation',
      priority: 'P0',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED', outcomeUncertain: false },
    })

    expect(await readFile(harness.callsPath, 'utf8')).toBe(callsBefore)
    expect(harness.service.getBinding(current)).toEqual(bindingBefore)
  })

  it('derives Agent/User Todo authority while keeping planner limits as LoopX guidance', async () => {
    const agentHarness = await setupHarness({ fineGrained: true })
    const agentSession = session(agentHarness.project)
    const started = await agentHarness.service.start(agentSession, 'Plan one exact checkpoint')
    expect(started).toMatchObject({
      ok: true,
      value: { planning: { writeback: { maximumTodos: 1 } } },
    })
    await expect(agentHarness.service.todoAdd(agentSession, {
      text: 'Validate one bounded surface',
      priority: 'P1',
      actionKind: 'validate_surface',
      targetKey: 'surface:one',
    })).resolves.toMatchObject({
      ok: true,
      value: { role: 'agent' },
    })
    await expect(agentHarness.service.activate(agentSession, 'goal-a', 'agent-a'))
      .resolves.toMatchObject({ ok: true, value: { phase: 'active_armed' } })

    const userHarness = await setupHarness()
    const userSession = session(userHarness.project)
    await userHarness.service.start(userSession, 'Plan an owner decision gate')
    await expect(userHarness.service.todoAdd(userSession, {
      text: 'Approve the public release boundary',
      priority: 'P0',
      role: 'user',
    })).resolves.toMatchObject({
      ok: true,
      value: {
        role: 'user',
        payload: {
          task_class: 'user_gate',
          action_kind: 'owner_decision',
          bound_agent: 'agent-a',
          blocks_agent: 'agent-a',
          target_key: null,
        },
      },
    })
    const calls = (await readFile(userHarness.callsPath, 'utf8')).trim().split('\n')
    const argv = calls
      .filter(line => line.startsWith('argv:'))
      .map(line => JSON.parse(line.slice(5)) as string[])
      .find(values => values.includes('add'))
    expect(argv).toEqual(expect.arrayContaining([
      '--role', 'user',
      '--task-class', 'user_gate',
      '--action-kind', 'owner_decision',
      '--agent-id', 'agent-a',
      '--bound-agent', 'agent-a',
      '--blocks-agent', 'agent-a',
    ]))
  })

  it('disarms the binding after an admitted Todo mismatch', async () => {
    const harness = await setupHarness({ todoAddFailureAt: 2 })
    const current = session(harness.project)
    await harness.service.start(current, 'Plan two ordered checkpoints')
    await expect(harness.service.todoAdd(current, {
      text: 'Write the first exact checkpoint',
      priority: 'P0',
    })).resolves.toMatchObject({ ok: true })
    await expect(harness.service.todoAdd(current, {
      text: 'Write the second exact checkpoint',
      priority: 'P1',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { phase: 'uncertain', reason: 'uncertain_write', generation: 2 },
    })
    await expect(harness.service.activate(current, 'goal-a', 'agent-a'))
      .resolves.toMatchObject({ ok: false })
  })

  it('maps a versioned authoritative Todo rejection without a schema-unsupported error', async () => {
    const harness = await setupHarness({ todoAddAuthoritativeFailure: true })
    const current = session(harness.project)
    await harness.service.start(current, 'Plan before an authoritative Todo rejection')

    await expect(harness.service.todoAdd(current, {
      text: 'Write one rejected checkpoint',
      priority: 'P0',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { phase: 'uncertain', reason: 'uncertain_write' },
    })
  })

  it('maps a versioned authoritative attach rejection without a schema-unsupported error', async () => {
    const harness = await setupHarness({
      bindingGoal: null,
      bindingAgent: null,
      threadBindingAuthoritativeFailure: true,
    })
    const current = session(harness.project)

    await expect(harness.service.attach(current, {
      goalId: 'goal-a',
      agentId: 'agent-a',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
  })

  it('marks an admitted Todo write uncertain when its planning fence changes before receipt', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    await harness.service.start(current, 'Plan one fenced checkpoint')
    vi.spyOn(harness.service, 'fenceIsCurrent').mockReturnValue(false)

    await expect(harness.service.todoAdd(current, {
      text: 'Write the fenced checkpoint',
      priority: 'P0',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { phase: 'uncertain', reason: 'uncertain_write' },
    })
  })

  it.each(['authoritative', 'global-sync', 'suppression', 'partial', 'locator'] as const)(
    'never arms when refresh-state fails the %s postcondition',
    async (refreshFailure) => {
      const harness = await setupHarness({ refreshFailure })
      const current = session(harness.project)
      await harness.service.start(current, 'Plan before exact refresh validation')
      await harness.service.todoAdd(current, {
        text: 'Create the verified checkpoint',
        priority: 'P0',
      })
      await expect(harness.service.activate(current, 'goal-a', 'agent-a'))
        .resolves.toMatchObject({
          ok: false,
          error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
        })
      expect(harness.service.getBinding(current)).toMatchObject({
        ok: true,
        value: { phase: 'uncertain', reason: 'uncertain_write' },
      })
    },
  )

  it('activates from authoritative LoopX refresh without a plugin-local receipt ledger', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    await harness.service.start(current, 'Plan before activation')
    await expect(harness.service.activate(current, 'goal-a', 'agent-a'))
      .resolves.toMatchObject({
        ok: true,
        value: { phase: 'active_armed' },
      })
    const calls = await readFile(harness.callsPath, 'utf8')
    expect(calls).toContain('start:refresh-state')
  })

  it('defaults a stable unbound Session to a fresh peer while attach keeps explicit selection', async () => {
    const harness = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingAgent: null,
    })
    const current = session(harness.project)
    const started = await harness.service.start(current, 'Implement the bounded change')
    expect(started.ok).toBe(true)
    if (!started.ok || started.value.kind !== 'planning') throw new Error('fresh start failed')
    expect(started.value.binding.agentId).toMatch(/^dsh-[a-f0-9]{20}$/u)
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { agentId: started.value.binding.agentId, phase: 'planning' },
    })
    expect((await harness.readState()).agents).toContain(started.value.binding.agentId)

    const attachHarness = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingAgent: null,
    })
    const attachSession = session(attachHarness.project)
    const implicit = await attachHarness.service.attach(attachSession, { goalId: 'goal-a' })
    expect(implicit).toMatchObject({
      ok: true,
      value: { kind: 'selection_required', selection: { kind: 'agent' } },
    })
    const attached = await attachHarness.service.attach(attachSession, {
      goalId: 'goal-a',
      agentId: 'agent-b',
    })
    expect(attached).toMatchObject({
      ok: true,
      value: { kind: 'attached', binding: { agentId: 'agent-b', phase: 'active_armed' } },
    })
    expect((await attachHarness.readState()).bindingAgent).toBe('agent-b')
    await expect(harness.service.detach(current)).resolves.toEqual({
      ok: true,
      value: { detached: true },
    })
    expect((await harness.readState()).bindingAgent).toBeNull()
    expect(harness.service.getBinding(current)).toEqual({ ok: true, value: undefined })
  })

  it('separates deterministic registration rejection from partial-write uncertainty', async () => {
    const preflight = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingAgent: null,
      registerAgentFailure: 'preflight',
    })
    const preflightSession = session(preflight.project)
    await expect(preflight.service.start(
      preflightSession,
      'Start after registry validation',
    )).resolves.toMatchObject({
      ok: false,
      error: {
        code: 'LOOPX_REGISTRY_INTEGRITY',
        outcomeUncertain: false,
        retryable: false,
      },
    })
    expect(preflight.service.getBinding(preflightSession)).toEqual({
      ok: true,
      value: undefined,
    })
    expect((await preflight.readState()).agents).toEqual(['agent-a', 'agent-b'])

    const collision = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingAgent: null,
      registerAgentFailure: 'collision',
    })
    const collisionSession = session(collision.project)
    await expect(collision.service.start(
      collisionSession,
      'Start with a fresh identity',
    )).resolves.toMatchObject({
      ok: false,
      error: {
        code: 'LOOPX_IDENTITY_CONFLICT',
        outcomeUncertain: false,
        retryable: true,
      },
    })
    expect(collision.service.getBinding(collisionSession)).toEqual({
      ok: true,
      value: undefined,
    })

    const partial = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingAgent: null,
      registerAgentFailure: 'partial',
    })
    const partialSession = session(partial.project)
    await expect(partial.service.start(
      partialSession,
      'Start after a partial registration',
    )).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
    expect(partial.service.getBinding(partialSession)).toEqual({
      ok: true,
      value: undefined,
    })
    expect((await partial.readState()).agents).toHaveLength(3)
    expect((await partial.readState()).bindingAgent).toBeNull()
  })

  it('requires exact requested/source/global agent readback before binding', async () => {
    const harness = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingAgent: null,
      registerAgentFailure: 'readback-mismatch',
    })
    const current = session(harness.project)

    await expect(harness.service.start(
      current,
      'Start only after exact agent readback',
    )).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
    expect(harness.service.getBinding(current)).toEqual({ ok: true, value: undefined })
    expect((await harness.readState()).bindingAgent).toBeNull()
  })

  it('connects a fresh project with fixed argv, ignores returned command text, and rereads authority', async () => {
    const harness = await setupHarness({
      goals: [],
      agents: [],
      bindingGoal: null,
      bindingAgent: null,
      connectionState: 'not_connected',
    })
    const current = session(harness.project)
    const objective = '  Connect\tand\nplan   this fresh project  '
    const normalizedObjective = 'Connect and plan this fresh project'

    const result = await harness.service.start(current, objective)

    expect(result).toMatchObject({
      ok: true,
      value: {
        kind: 'planning',
        binding: { goalId: 'goal-a', phase: 'planning' },
      },
    })
    const calls = (await readFile(harness.callsPath, 'utf8')).trim().split('\n')
    expect(calls.filter(line => line === 'start:start-goal')).toHaveLength(3)
    const argv = calls
      .filter(line => line.startsWith('argv:'))
      .map(line => JSON.parse(line.slice(5)) as string[])
    const bootstrap = argv.find(values => values.includes('bootstrap'))
    expect(bootstrap).toEqual([
      '--format', 'json',
      'bootstrap',
      '--project', harness.project,
      '--goal-id', 'goal-a',
      '--objective', normalizedObjective,
      '--adapter-kind', 'read_only_project_map_v0',
      '--adapter-status', 'connected-read-only',
      '--no-onboarding-scan',
      '--codex-app-heartbeat', 'ask',
    ])
    const startArgv = argv.find(values => values.includes('start-goal'))
    expect(startArgv?.[startArgv.indexOf('--goal-text') + 1]).toBe(normalizedObjective)
    expect(calls.join('\n')).not.toContain('touch LOOPX_RETURNED_COMMAND_MUST_NOT_RUN')
  })

  it('uses the existing fork contract for a new independent Goal', async () => {
    const harness = await setupHarness({
      agents: [],
      bindingGoal: null,
      bindingAgent: null,
    })
    const current = session(harness.project)

    const result = await harness.service.start(
      current,
      'Create an independent Goal',
      undefined,
      { newIndependent: true },
    )

    expect(result.ok).toBe(true)
    if (!result.ok || result.value.kind !== 'planning') throw new Error('independent start failed')
    expect(result.value.binding.goalId).toMatch(/^dsh-goal-[a-f0-9]{20}$/u)
    const calls = (await readFile(harness.callsPath, 'utf8')).trim().split('\n')
    const argv = calls
      .filter(line => line.startsWith('argv:'))
      .map(line => JSON.parse(line.slice(5)) as string[])
    const bootstrap = argv.find(values => values.includes('bootstrap'))
    expect(bootstrap).toContain('--fork-goal')
    expect(bootstrap).not.toContain('--goal-id')
    expect(bootstrap?.[bootstrap.indexOf('--fork-goal') + 1]).toBe(result.value.binding.goalId)
  })

  it('re-enters authoritative Goal selection and preserves explicit agent takeover', async () => {
    const goalHarness = await setupHarness({ goals: ['goal-a', 'goal-b'] })
    const goalSession = session(goalHarness.project)
    await expect(goalHarness.service.start(goalSession, 'Resume one exact Goal'))
      .resolves.toMatchObject({
        ok: true,
        value: { kind: 'selection_required', selection: { kind: 'goal' } },
      })
    await expect(goalHarness.service.start(
      goalSession,
      'Resume one exact Goal',
      undefined,
      { goalId: 'goal-a' },
    )).resolves.toMatchObject({
      ok: true,
      value: { kind: 'planning', binding: { goalId: 'goal-a', agentId: 'agent-a' } },
    })

    const agentHarness = await setupHarness({
      agents: ['agent-a', 'agent-b'],
      bindingGoal: null,
      bindingAgent: null,
    })
    const agentSession = session(agentHarness.project)
    await expect(agentHarness.service.start(
      agentSession,
      'Select one exact lane',
      undefined,
      { agentId: 'agent-b' },
    )).resolves.toMatchObject({
      ok: true,
      value: { kind: 'planning', binding: { goalId: 'goal-a', agentId: 'agent-b' } },
    })
    expect((await agentHarness.readState()).bindingAgent).toBe('agent-b')
  })

  it('fails closed on malformed connection state and typed bootstrap rejection', async () => {
    const malformed = await setupHarness({ connectionState: 'registry_invalid' })
    await expect(malformed.service.start(session(malformed.project), 'Must not repair silently'))
      .resolves.toMatchObject({
        ok: false,
        error: { code: 'LOOPX_READBACK_FAILED', retryable: false },
      })
    expect(await readFile(malformed.callsPath, 'utf8')).not.toContain('start:bootstrap')

    const rejectedBootstrap = await setupHarness({
      goals: [],
      agents: [],
      bindingGoal: null,
      bindingAgent: null,
      connectionState: 'not_connected',
      bootstrapFailure: true,
    })
    await expect(rejectedBootstrap.service.start(
      session(rejectedBootstrap.project),
      'Typed bootstrap failure',
    )).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_BOOTSTRAP_FAILED', operation: 'bootstrap-connect' },
    })
    expect(rejectedBootstrap.service.getBinding(session(rejectedBootstrap.project)))
      .toEqual({ ok: true, value: undefined })
  })

  it('prepares a historical switch without mutation and commits after exact confirmation', async () => {
    const harness = await setupHarness({ goals: ['goal-a', 'goal-b'] })
    const current = session(harness.project)
    const attached = await harness.service.attach(current, { goalId: 'goal-a' })
    if (!attached.ok || attached.value.kind !== 'attached') throw new Error('initial attach failed')
    const callsBefore = await readFile(harness.callsPath, 'utf8')

    const prepared = await harness.service.attach(current, {
      goalId: 'goal-b',
      agentId: 'agent-a',
    })

    expect(prepared).toMatchObject({
      ok: true,
      value: {
        kind: 'switch_required',
        requiresUserConfirmation: true,
        current: { goalId: 'goal-a', agentId: 'agent-a' },
        requested: { operation: 'attach', goalId: 'goal-b', agentId: 'agent-a' },
      },
    })
    expect(await readFile(harness.callsPath, 'utf8')).toBe(callsBefore)
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { goalId: 'goal-a', agentId: 'agent-a' },
    })
    if (!prepared.ok || prepared.value.kind !== 'switch_required') {
      throw new Error('switch was not prepared')
    }
    expect(await harness.storageText()).not.toContain(prepared.value.confirmationToken)

    const committed = await harness.service.attach(current, {
      goalId: 'goal-b',
      agentId: 'agent-a',
      switchConfirmation: prepared.value.confirmationToken,
    })
    expect(committed).toMatchObject({
      ok: true,
      value: { kind: 'attached', binding: { goalId: 'goal-b', agentId: 'agent-a' } },
    })
  })

  it('rejects invalid and expired switch confirmations without mutating the old binding', async () => {
    const harness = await setupHarness({ goals: ['goal-a', 'goal-b'] })
    const current = session(harness.project)
    const initial = await harness.service.attach(current, { goalId: 'goal-a' })
    if (!initial.ok || initial.value.kind !== 'attached') throw new Error('initial attach failed')
    const prepared = await harness.service.attach(current, { goalId: 'goal-b', agentId: 'agent-a' })
    if (!prepared.ok || prepared.value.kind !== 'switch_required') throw new Error('prepare failed')
    const callsBefore = await readFile(harness.callsPath, 'utf8')

    await expect(harness.service.attach(current, {
      goalId: 'goal-b',
      agentId: 'agent-a',
      switchConfirmation: '00000000-0000-0000-0000-000000000000',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SWITCH_CONFIRMATION_INVALID' },
    })
    expect(await readFile(harness.callsPath, 'utf8')).toBe(callsBefore)

    vi.spyOn(Date, 'now').mockReturnValue(prepared.value.expiresAt + 1)
    await expect(harness.service.attach(current, {
      goalId: 'goal-b',
      agentId: 'agent-a',
      switchConfirmation: prepared.value.confirmationToken,
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SWITCH_CONFIRMATION_INVALID' },
    })
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { goalId: 'goal-a', agentId: 'agent-a' },
    })
  })

  it('accepts same-identity generation churn but rejects an old token after queued rebind', async () => {
    const churn = await setupHarness({ goals: ['goal-a', 'goal-b'] })
    const churnSession = session(churn.project)
    const initial = await churn.service.attach(churnSession, { goalId: 'goal-a' })
    if (!initial.ok || initial.value.kind !== 'attached') throw new Error('initial attach failed')
    const prepared = await churn.service.attach(churnSession, {
      goalId: 'goal-b',
      agentId: 'agent-a',
    })
    if (!prepared.ok || prepared.value.kind !== 'switch_required') throw new Error('prepare failed')
    await churn.service.pause(churnSession)
    await churn.service.resume(churnSession)
    await expect(churn.service.attach(churnSession, {
      goalId: 'goal-b',
      agentId: 'agent-a',
      switchConfirmation: prepared.value.confirmationToken,
    })).resolves.toMatchObject({
      ok: true,
      value: { kind: 'attached', binding: { goalId: 'goal-b' } },
    })

    const race = await setupHarness({ goals: ['goal-a', 'goal-b', 'goal-c'] })
    const raceSession = session(race.project)
    const raceInitial = await race.service.attach(raceSession, { goalId: 'goal-a' })
    if (!raceInitial.ok || raceInitial.value.kind !== 'attached') throw new Error('initial attach failed')
    const stale = await race.service.attach(raceSession, {
      goalId: 'goal-b',
      agentId: 'agent-a',
    })
    if (!stale.ok || stale.value.kind !== 'switch_required') throw new Error('prepare failed')
    const detach = race.service.detach(raceSession)
    const rebind = race.service.attach(raceSession, { goalId: 'goal-c', agentId: 'agent-a' })
    const staleCommit = race.service.attach(raceSession, {
      goalId: 'goal-b',
      agentId: 'agent-a',
      switchConfirmation: stale.value.confirmationToken,
    })
    await expect(detach).resolves.toMatchObject({ ok: true })
    await expect(rebind).resolves.toMatchObject({
      ok: true,
      value: { kind: 'attached', binding: { goalId: 'goal-c' } },
    })
    await expect(staleCommit).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SWITCH_CONFIRMATION_INVALID' },
    })
    expect(race.service.getBinding(raceSession)).toMatchObject({
      ok: true,
      value: { goalId: 'goal-c' },
    })
  })

  it('stops on uncertain detach and reports a failed post-detach start as truly unbound', async () => {
    const uncertain = await setupHarness({ goals: ['goal-a', 'goal-b'] })
    const uncertainSession = session(uncertain.project)
    const initial = await uncertain.service.attach(uncertainSession, { goalId: 'goal-a' })
    if (!initial.ok || initial.value.kind !== 'attached') throw new Error('initial attach failed')
    const prepared = await uncertain.service.attach(uncertainSession, {
      goalId: 'goal-b',
      agentId: 'agent-a',
    })
    if (!prepared.ok || prepared.value.kind !== 'switch_required') throw new Error('prepare failed')
    await uncertain.writeState({ invalidJsonFor: 'unbind-agent-thread' })
    await expect(uncertain.service.attach(uncertainSession, {
      goalId: 'goal-b',
      agentId: 'agent-a',
      switchConfirmation: prepared.value.confirmationToken,
    })).resolves.toMatchObject({
      ok: false,
      error: { outcomeUncertain: true },
    })
    expect(uncertain.service.getBinding(uncertainSession)).toMatchObject({
      ok: true,
      value: { goalId: 'goal-a', phase: 'uncertain' },
    })

    const incomplete = await setupHarness()
    const incompleteSession = session(incomplete.project)
    const incompleteInitial = await incomplete.service.attach(incompleteSession, { goalId: 'goal-a' })
    if (!incompleteInitial.ok || incompleteInitial.value.kind !== 'attached') {
      throw new Error('initial attach failed')
    }
    const newGoal = await incomplete.service.start(
      incompleteSession,
      'Start a replacement Goal',
      undefined,
      { newIndependent: true },
    )
    if (!newGoal.ok || newGoal.value.kind !== 'switch_required') throw new Error('prepare failed')
    await incomplete.writeState({ invalidJsonFor: 'start-goal' })
    await expect(incomplete.service.start(
      incompleteSession,
      'Start a replacement Goal',
      undefined,
      {
        newIndependent: true,
        switchConfirmation: newGoal.value.confirmationToken,
      },
    )).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SWITCH_INCOMPLETE' },
    })
    expect(incomplete.service.getBinding(incompleteSession)).toEqual({ ok: true, value: undefined })
    expect((await incomplete.readState()).bindingAgent).toBeNull()
  })

  it('registers --new-peer through official contracts and takes over an existing thread binding', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    const attached = await harness.service.attach(current, { goalId: 'goal-a', newPeer: true })
    expect(attached.ok).toBe(true)
    if (!attached.ok || attached.value.kind !== 'attached') throw new Error('new peer did not attach')
    expect(attached.value.binding.agentId).toMatch(/^dsh-[a-f0-9]{20}$/u)
    const state = await harness.readState()
    expect(state.agents).toContain(attached.value.binding.agentId)
    expect(state.bindingAgent).toBe(attached.value.binding.agentId)
  })

  it('rejects an unregistered explicit lane before changing the authoritative thread binding', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)

    await expect(harness.service.attach(current, {
      goalId: 'goal-a',
      agentId: 'agent-not-registered',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_IDENTITY_CONFLICT' },
    })
    expect((await harness.readState()).bindingAgent).toBe('agent-a')
    expect(harness.service.getBinding(current)).toEqual({ ok: true, value: undefined })
  })

  it('persists a disarmed sidecar when attach write or readback cannot be verified', async () => {
    const uncertainHarness = await setupHarness({
      bindingAgent: null,
      invalidJsonFor: 'bind-agent-thread',
    })
    const uncertainSession = session(uncertainHarness.project)

    await expect(uncertainHarness.service.attach(uncertainSession, {
      goalId: 'goal-a',
      agentId: 'agent-a',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SCHEMA_UNSUPPORTED', outcomeUncertain: true },
    })
    expect(uncertainHarness.service.getBinding(uncertainSession)).toMatchObject({
      ok: true,
      value: {
        goalId: 'goal-a',
        agentId: 'agent-a',
        phase: 'uncertain',
        reason: 'uncertain_write',
      },
    })

    const pausedHarness = await setupHarness({ invalidJsonFor: 'heartbeat-prompt' })
    const pausedSession = session(pausedHarness.project)
    await expect(pausedHarness.service.attach(pausedSession, { goalId: 'goal-a' }))
      .resolves.toMatchObject({
        ok: false,
        error: { code: 'LOOPX_SCHEMA_UNSUPPORTED', outcomeUncertain: false },
      })
    expect(pausedHarness.service.getBinding(pausedSession)).toMatchObject({
      ok: true,
      value: {
        goalId: 'goal-a',
        agentId: 'agent-a',
        phase: 'active_paused',
        reason: 'readback_failed',
      },
    })
  })

  it('serializes Session mutations, projects bounded output, and disarms uncertain writes', async () => {
    const harness = await setupHarness({ delayCommand: 'todo-update', delayMs: 35 })
    const current = session(harness.project)
    const attached = await harness.service.attach(current, { goalId: 'goal-a' })
    expect(attached.ok).toBe(true)

    const [first, second] = await Promise.all([
      harness.service.todoUpdate(current, { todoId: 'todo-a', status: 'blocked' }),
      harness.service.todoUpdate(current, { todoId: 'todo-b', status: 'open' }),
    ])
    expect(first).toMatchObject({ ok: true, value: { todoId: 'todo-a' } })
    expect(second).toMatchObject({ ok: true, value: { todoId: 'todo-b' } })
    const calls = (await readFile(harness.callsPath, 'utf8')).trim().split('\n')
    expect(calls.filter(line => line.includes('todo-update'))).toEqual([
      'start:todo-update',
      'end:todo-update',
      'start:todo-update',
      'end:todo-update',
    ])
    if (!first.ok) throw new Error('first Todo update failed')
    expect(JSON.stringify(first.value.payload)).not.toContain('private-state.md')

    const status = await harness.service.status(current)
    expect(status.ok).toBe(true)
    expect(JSON.stringify(status)).not.toContain('private-registry.json')
    expect(JSON.stringify(status)).not.toContain('must-not-project')
    const quota = await harness.service.quotaShouldRun(current, 'turn-a')
    expect(quota).toMatchObject({
      ok: true,
      value: {
        shouldRun: true,
        terminalNoFollowup: false,
        schedulerHint: { resetToken: 'reset-1', recommendedIntervalMinutes: 3 },
      },
    })

    await harness.writeState({ invalidJsonFor: 'todo-update', delayCommand: undefined })
    const uncertain = await harness.service.todoUpdate(current, {
      todoId: 'todo-c',
      note: 'public note',
    })
    expect(uncertain).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SCHEMA_UNSUPPORTED', outcomeUncertain: true },
    })
    expect(JSON.stringify(uncertain)).not.toContain('PRIVATE INVALID OUTPUT')
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { phase: 'uncertain', reason: 'uncertain_write' },
    })
  })

  it('invalidates stale scheduler fences and drains admitted work during service disposal', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    const attached = await harness.service.attach(current, { goalId: 'goal-a' })
    if (!attached.ok || attached.value.kind !== 'attached') throw new Error('attach failed')
    const fence = harness.service.fence(current)
    if (!fence.ok) throw new Error('fence missing')
    const scheduled = await harness.service.updateScheduler(
      current,
      fence.value,
      {
        action: 'wait',
        cadenceClass: 'monitor_wait',
        resetToken: 'reset-a',
        recommendedIntervalMinutes: 3,
        unchangedPollLimit: 2,
        afterLimit: 'pause',
      },
      1,
      Date.now() + 1_000,
    )
    expect(scheduled).toMatchObject({
      ok: true,
      value: { schedulerResetToken: 'reset-a', unchangedPollCount: 1 },
    })
    await harness.service.pause(current)
    expect(harness.service.fenceIsCurrent(fence.value)).toBe(false)
    const paused = harness.service.getBinding(current)
    expect(paused).toMatchObject({
      ok: true,
      value: {
        phase: 'active_paused',
      },
    })
    if (!paused.ok || paused.value === undefined) throw new Error('paused binding missing')
    expect(paused.value).not.toHaveProperty('schedulerResetToken')
    expect(paused.value).not.toHaveProperty('nextCheckAt')

    await harness.service.resume(current)
    await harness.writeState({ delayCommand: 'todo-update', delayMs: 1_000 })
    const service = harness.service
    const first = service.todoUpdate(current, { todoId: 'todo-dispose-a', status: 'open' })
    const second = service.todoUpdate(current, { todoId: 'todo-dispose-b', status: 'open' })
    await new Promise(resolve => setTimeout(resolve, 25))
    await harness.disposeService()
    await expect(Promise.all([first, second])).resolves.toHaveLength(2)
    await expect(service.todoUpdate(current, { todoId: 'after-close', status: 'open' }))
      .resolves.toMatchObject({ ok: false, error: { code: 'LOOPX_SERVICE_CLOSED' } })
  })

  it('applies fail-closed transitions with an in-queue generation fence', async () => {
    const harness = await setupHarness({ delayCommand: 'heartbeat-prompt', delayMs: 35 })
    const current = session(harness.project)
    const attached = await harness.service.attach(current, { goalId: 'goal-a' })
    if (!attached.ok || attached.value.kind !== 'attached') throw new Error('attach failed')

    const firstFence = harness.service.fence(current)
    if (!firstFence.ok) throw new Error('first fence missing')
    const firstResume = harness.service.resume(current)
    const stalePause = harness.service.pause(current, 'readback_failed', firstFence.value)
    await expect(firstResume).resolves.toMatchObject({ ok: true, value: { generation: 2 } })
    await expect(stalePause).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { phase: 'active_armed', generation: 2 },
    })

    const secondFence = harness.service.fence(current)
    if (!secondFence.ok) throw new Error('second fence missing')
    const secondResume = harness.service.resume(current)
    const staleUncertain = harness.service.markUncertain(
      current,
      'uncertain_write',
      secondFence.value,
    )
    await expect(secondResume).resolves.toMatchObject({ ok: true, value: { generation: 3 } })
    await expect(staleUncertain).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })
    expect(harness.service.getBinding(current)).toMatchObject({
      ok: true,
      value: { phase: 'active_armed', generation: 3 },
    })
    await expect(harness.service.taskBody(current, 3)).resolves.toMatchObject({
      ok: true,
      value: { body: 'PRIVATE TASK BODY FROM LOOPX' },
    })
  })

  it('keeps a certain retryable quota failure armed for the driver retry', async () => {
    const harness = await setupHarness()
    const current = session(harness.project)
    const attached = await harness.service.attach(current, { goalId: 'goal-a' })
    if (!attached.ok || attached.value.kind !== 'attached') throw new Error('attach failed')
    const before = harness.service.getBinding(current)
    const controller = new AbortController()
    controller.abort(new Error('test cancellation'))

    const result = await harness.service.quotaShouldRun(current, 'turn-retry', controller.signal)

    expect(result).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_CLI_ABORTED', retryable: true, outcomeUncertain: false },
    })
    expect(harness.service.getBinding(current)).toEqual(before)
  })
})
