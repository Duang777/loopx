import { Context } from '@deepseek-ai/cordis'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  LoopXCliBindingRequest,
  LoopXCliRequest,
} from '../src/cli-client.ts'
import { coordinatorFor } from '../src/coordinator.ts'
import LoopXService, { type Config } from '../src/service.ts'
import type {
  LoopXBoundHostThreadBindingV1,
  LoopXHostThreadBindingV1,
  LoopXSessionRef,
} from '../src/types.ts'

interface Call {
  readonly operation: string
  readonly args: readonly string[]
  readonly cwd: string
}

interface AuthorityOptions {
  unhealthy?: boolean
  commandPackValid?: boolean
  refreshAppended?: boolean
}

function arg(args: readonly string[], flag: string): string | undefined {
  const index = args.indexOf(flag)
  return index < 0 ? undefined : args[index + 1]
}

function wireBinding(binding: LoopXHostThreadBindingV1) {
  const base = {
    schema_version: binding.schemaVersion,
    host_surface: binding.hostSurface,
    thread_id: binding.threadId,
    revision: binding.revision,
    state: binding.state,
  }
  return binding.state === 'bound'
    ? { ...base, target: { goal_id: binding.target.goalId, agent_id: binding.target.agentId } }
    : base
}

function bound(threadId = 'session-a', revision = 1): LoopXBoundHostThreadBindingV1 {
  return Object.freeze({
    schemaVersion: 'loopx_host_thread_binding_v1',
    hostSurface: 'dsh',
    threadId,
    revision,
    state: 'bound',
    target: Object.freeze({ goalId: 'goal-a', agentId: 'agent-a' }),
  })
}

function unbound(revision = 2): LoopXHostThreadBindingV1 {
  return Object.freeze({
    schemaVersion: 'loopx_host_thread_binding_v1',
    hostSurface: 'dsh',
    threadId: 'session-a',
    revision,
    state: 'unbound',
  })
}

class FakeAuthorityCli {
  readonly binarySource = 'config' as const
  readonly calls: Call[] = []
  binding: LoopXHostThreadBindingV1 | undefined
  unhealthy = false
  commandPackValid = true
  refreshAppended = true
  bindConflict = false
  bindConflictBinding: LoopXHostThreadBindingV1 | undefined
  statusItems: readonly unknown[] = []

  constructor(binding?: LoopXHostThreadBindingV1, options: AuthorityOptions = {}) {
    this.binding = binding
    this.unhealthy = options.unhealthy ?? false
    this.commandPackValid = options.commandPackValid ?? true
    this.refreshAppended = options.refreshAppended ?? true
  }

  runBindingJson<T>(request: LoopXCliBindingRequest<T>): Promise<T> {
    this.calls.push({ operation: request.operation, args: request.args, cwd: request.home.cwd })
    const command = request.args[0]
    if (command === 'resolve-agent-thread') {
      if (this.unhealthy) {
        return this.value<T>({
          schema_version: 'loopx_host_thread_binding_command_v1',
          ok: false,
          changed: false,
          application: 'no',
          error_kind: 'authority_unhealthy',
          ...(this.binding === undefined ? {} : { binding: wireBinding(this.binding) }),
        })
      }
      if (this.binding === undefined) {
        return this.value<T>({
          schema_version: 'loopx_host_thread_binding_command_v1',
          ok: false,
          changed: false,
          application: 'no',
          error_kind: 'binding_not_found',
        })
      }
      return this.value<T>({
        schema_version: 'loopx_host_thread_binding_command_v1',
        ok: true,
        changed: false,
        application: 'no',
        binding: wireBinding(this.binding),
      })
    }

    const expected = Number(arg(request.args, '--expected-revision'))
    const currentRevision = this.binding?.revision ?? 0
    if (expected !== currentRevision) {
      return this.value<T>({
        schema_version: 'loopx_host_thread_binding_command_v1',
        ok: false,
        changed: false,
        application: 'no',
        error_kind: 'revision_conflict',
        ...(this.binding === undefined ? {} : { binding: wireBinding(this.binding) }),
      })
    }
    const threadId = arg(request.args, '--thread-id') ?? 'session-a'
    if (command === 'bind-agent-thread') {
      if (this.bindConflict) {
        return this.value<T>({
          schema_version: 'loopx_host_thread_binding_command_v1',
          ok: false,
          changed: false,
          application: 'no',
          error_kind: 'revision_conflict',
          ...(this.bindConflictBinding === undefined
            ? {}
            : { binding: wireBinding(this.bindConflictBinding) }),
        })
      }
      const target = {
        goalId: arg(request.args, '--goal-id') ?? '',
        agentId: arg(request.args, '--agent-id') ?? '',
      }
      const unchanged = this.binding?.state === 'bound'
        && this.binding.target.goalId === target.goalId
        && this.binding.target.agentId === target.agentId
      if (!unchanged) {
        this.binding = Object.freeze({
          schemaVersion: 'loopx_host_thread_binding_v1',
          hostSurface: 'dsh',
          threadId,
          revision: currentRevision + 1,
          state: 'bound',
          target: Object.freeze(target),
        })
      }
      return this.value<T>({
        schema_version: 'loopx_host_thread_binding_command_v1',
        ok: true,
        changed: !unchanged,
        application: unchanged ? 'no' : 'yes',
        binding: wireBinding(this.binding as LoopXHostThreadBindingV1),
      })
    }

    const unchanged = this.binding?.state === 'unbound'
    if (!unchanged) {
      this.binding = Object.freeze({
        schemaVersion: 'loopx_host_thread_binding_v1',
        hostSurface: 'dsh',
        threadId,
        revision: currentRevision + 1,
        state: 'unbound',
      })
    }
    return this.value<T>({
      schema_version: 'loopx_host_thread_binding_command_v1',
      ok: true,
      changed: !unchanged,
      application: unchanged ? 'no' : 'yes',
      binding: wireBinding(this.binding as LoopXHostThreadBindingV1),
    })
  }

  runJson<T>(request: LoopXCliRequest<T>): Promise<T> {
    this.calls.push({ operation: request.operation, args: request.args, cwd: request.cwd })
    const goalId = arg(request.args, '--goal-id') ?? 'goal-a'
    const agentId = arg(request.args, '--agent-id') ?? 'agent-a'
    if (request.operation === 'bootstrap-connect') {
      return this.value<T>({
        ok: true,
        goal_id: goalId,
        registry_goal_action: 'appended',
        state_action: 'created',
        global_sync: { ok: true, synced_goal_ids: [goalId], wrote: true },
      })
    }
    if (request.operation === 'register-agent') {
      return this.value<T>({
        ok: true,
        goal_id: goalId,
        changed: true,
        written: true,
        partial_write: false,
        requested_agents: [agentId],
        registered_agents: [agentId],
        registration_readback: {
          performed: true,
          verified: true,
          requested_agents: [agentId],
          source_registered_agents: [agentId],
          global_registered_agents: [agentId],
        },
        global_sync: { ok: true },
      })
    }
    if (request.operation === 'start-goal') return this.value<T>(this.startPacket(goalId, agentId))
    if (request.operation === 'activate-refresh') {
      return this.value<T>({
        ok: true,
        goal_id: goalId,
        agent_id: agentId,
        appended: this.refreshAppended,
        idempotent_replay: !this.refreshAppended,
        partial_write: false,
        external_sink_delivery_authorized: false,
        global_sync: { ok: true, wrote: this.refreshAppended },
      })
    }
    if (request.operation === 'bootstrap-command-pack') {
      return this.value<T>(this.commandPack(goalId, agentId))
    }
    if (request.operation === 'heartbeat-prompt') {
      return this.value<T>({
        ok: true,
        goal_id: goalId,
        agent_id: agentId,
        task_body: 'internal task body',
      })
    }
    if (request.operation === 'resume-status' || request.operation === 'status') {
      return this.value<T>({
        ok: true,
        goal_filter: goalId,
        attention_queue: { items: this.statusItems },
      })
    }
    throw new Error(`unexpected fake operation: ${request.operation}`)
  }

  abortScope(): void {}
  close(): Promise<void> { return Promise.resolve() }

  private startPacket(goalId: string, agentId: string) {
    return {
      ok: true,
      goal_id: goalId,
      agent_id: agentId,
      host_thread_binding: wireBinding(this.binding as LoopXHostThreadBindingV1),
      command_pack: {
        goal_start_contract: {
          goal_text: arg(this.calls.at(-1)?.args ?? [], '--goal-text'),
          planner: {
            default_profile: 'clear_bounded_problem',
            profile_selection: '/private/sentinel-profile',
            profiles: {
              open_ended_product_direction: {
                suggested_items_min: 2,
                suggested_items_max: 4,
                intent: '/private/sentinel-open-intent',
              },
              clear_bounded_problem: {
                item_count_policy: '/private/sentinel-policy',
                may_reuse_current_todo_when_it_already_represents_the_plan: true,
                intent: '/private/sentinel-bounded-intent',
              },
            },
            required_fields: ['priority', 'text', 'task_class', 'action_kind'],
            maximum_runnable_todos_written_ahead: 3,
            budget_policy: '/private/sentinel-budget',
          },
          stop_conditions: ['/private/sentinel-stop'],
        },
      },
      guided_transaction: {
        ordered_steps: [{ kind: 'model_checkpoint', prompt: '/private/sentinel-prompt' }],
      },
    }
  }

  private commandPack(goalId: string, agentId: string) {
    const binding = wireBinding(this.binding as LoopXHostThreadBindingV1)
    return {
      ok: true,
      goal_id: goalId,
      agent_id: agentId,
      thread_id: binding.thread_id,
      host_thread_binding: binding,
      host_loop_activation: {
        activation_allowed: this.commandPackValid,
        goal_id: goalId,
        agent_id: agentId,
        identity_contract: { registered_agents: [agentId] },
        identity_selection_gate: this.commandPackValid ? null : {
          default_action: 'select_agent_identity',
          reason: '/private/sentinel-selection-reason',
          choices: [{ agent_id: agentId, label: '/private/sentinel-choice-label' }],
          fresh_agent_registration: null,
        },
        activation_input: {
          arguments: { goalId, agentId },
        },
        host_mutation: {
          forbidden_tool_arguments: ['sessionId', 'registryPath', 'taskBody', 'argv'],
        },
      },
    }
  }

  private value<T>(value: unknown): Promise<T> {
    return Promise.resolve(value as T)
  }
}

const cleanups: Array<() => Promise<void>> = []

afterEach(async () => {
  while (cleanups.length > 0) await cleanups.pop()?.()
})

function session(
  object: object = {},
  cwd: string | null = '/project',
): LoopXSessionRef {
  return Object.freeze({
    id: 'session-a',
    session: object,
    identity: Object.freeze({
      createdAt: 1,
      ...(cwd === null ? {} : { cwd }),
    }),
  })
}

async function serviceWith(
  cli: FakeAuthorityCli,
  config: Config = { loopxBin: 'loopx', runtimeRoot: '/runtime' },
): Promise<LoopXService> {
  const ctx = new Context()
  await ctx.plugin(LoopXService, config)
  const service = ctx.loopx
  Reflect.set(service, 'cli', cli)
  cleanups.push(async () => { await ctx.fiber.dispose() })
  return service
}

describe('LoopXService v1 authority and lifecycle', () => {
  it('starts a fresh Goal-Agent binding, remains disarmed, and omits CLI prose and paths', async () => {
    const cli = new FakeAuthorityCli()
    const service = await serviceWith(cli)
    const current = session()

    const result = await service.start(current, 'Build the bounded feature')

    expect(result).toMatchObject({
      ok: true,
      application: 'yes',
      value: {
        kind: 'planning',
        planning: { schemaVersion: 'dsh_loopx_planning_checkpoint_v1' },
      },
      subEffects: [
        { operation: 'bootstrap-goal', application: 'yes' },
        { operation: 'register-agent', application: 'yes' },
        { operation: 'bind-agent-thread', application: 'yes' },
      ],
    })
    expect(JSON.stringify(result)).not.toContain('/private/sentinel')
    expect(coordinatorFor(service).snapshot(current)).toMatchObject({
      activation: 'disarmed',
      observedBinding: { state: 'bound', revision: 1 },
    })
  })

  it('uses a fresh disarmed coordinator after plugin reload', async () => {
    const shared = bound()
    const first = await serviceWith(new FakeAuthorityCli(shared))
    const current = session()
    await expect(first.attach(current, { goalId: 'goal-a', agentId: 'agent-a' }))
      .resolves.toMatchObject({ ok: true })
    expect(coordinatorFor(first).snapshot(current)?.activation).toBe('armed')

    const second = await serviceWith(new FakeAuthorityCli(shared))
    const secondSession = session({})
    await expect(second.resolveBinding(secondSession)).resolves.toMatchObject({ ok: true })
    expect(coordinatorFor(second).snapshot(secondSession)?.activation).toBe('disarmed')
  })

  it('reports committed bootstrap and registration sub-effects when binding CAS loses', async () => {
    const cli = new FakeAuthorityCli()
    cli.bindConflict = true
    const service = await serviceWith(cli)
    const current = session()
    const result = await service.start(current, 'Build the bounded feature')
    expect(result).toMatchObject({
      ok: false,
      application: 'yes',
      error: { code: 'LOOPX_REVISION_CONFLICT' },
      subEffects: [
        { operation: 'bootstrap-goal', application: 'yes' },
        { operation: 'register-agent', application: 'yes' },
      ],
    })
    expect(coordinatorFor(service).snapshot(current)?.activation).toBe('disarmed')
  })

  it('rejects and never caches a wrong-thread binding attached to a mutation failure', async () => {
    const cli = new FakeAuthorityCli()
    cli.bindConflict = true
    cli.bindConflictBinding = bound('other-session', 1)
    const service = await serviceWith(cli)
    const current = session()
    const result = await service.start(current, 'Build the bounded feature')
    expect(result).toMatchObject({
      ok: false,
      application: 'yes',
      error: { code: 'LOOPX_READBACK_FAILED' },
    })
    expect(coordinatorFor(service).snapshot(current)?.observedBinding).toBeUndefined()
    const paused = await service.pause(current)
    expect(paused).toMatchObject({ ok: true, value: { paused: true } })
    expect(paused.ok && 'binding' in paused.value).toBe(false)
  })

  it('propagates binding no-op application through attach', async () => {
    const cli = new FakeAuthorityCli(bound())
    const service = await serviceWith(cli)
    const result = await service.attach(session(), { goalId: 'goal-a', agentId: 'agent-a' })
    expect(result).toMatchObject({ ok: true, application: 'no', value: { kind: 'attached' } })
    expect(result.subEffects).toEqual([])
  })

  it('resumes only after fresh binding, status, membership, task, and final binding readback', async () => {
    const cli = new FakeAuthorityCli(bound())
    const service = await serviceWith(cli)
    const current = session()
    await expect(service.resume(current)).resolves.toMatchObject({
      ok: true,
      application: 'no',
      value: { state: 'bound', revision: 1 },
    })
    expect(cli.calls.map(call => call.operation)).toEqual([
      'resolve-agent-thread',
      'resume-status',
      'bootstrap-command-pack',
      'heartbeat-prompt',
      'resolve-agent-thread',
    ])
    expect(coordinatorFor(service).snapshot(current)?.activation).toBe('armed')
  })

  it('serializes simultaneous writes through the exact Session coordinator', async () => {
    const cli = new FakeAuthorityCli(bound())
    const service = await serviceWith(cli)
    const current = session()
    const runJson = cli.runJson.bind(cli)
    let releaseFirstWrite: (() => void) | undefined
    let firstWriteEntered: (() => void) | undefined
    const firstWriteGate = new Promise<void>((resolve) => { releaseFirstWrite = resolve })
    const firstWriteStarted = new Promise<void>((resolve) => { firstWriteEntered = resolve })
    let activeWrites = 0
    let maximumActiveWrites = 0
    let writeEntries = 0
    vi.spyOn(cli, 'runJson').mockImplementation(async <T>(request: LoopXCliRequest<T>) => {
      if (request.operation !== 'activate-refresh') return runJson(request)
      writeEntries += 1
      activeWrites += 1
      maximumActiveWrites = Math.max(maximumActiveWrites, activeWrites)
      if (writeEntries === 1) {
        firstWriteEntered?.()
        await firstWriteGate
      }
      const result = await runJson(request)
      activeWrites -= 1
      return result
    })

    const first = service.activate(current, 'goal-a', 'agent-a')
    const second = service.activate(current, 'goal-a', 'agent-a')
    await firstWriteStarted
    await Promise.resolve()
    await Promise.resolve()
    expect(writeEntries).toBe(1)
    expect(cli.calls.map(call => call.operation)).toEqual(['resolve-agent-thread'])

    releaseFirstWrite?.()
    await expect(Promise.all([first, second])).resolves.toEqual([
      expect.objectContaining({ ok: true }),
      expect.objectContaining({ ok: true }),
    ])
    expect(writeEntries).toBe(2)
    expect(maximumActiveWrites).toBe(1)
    expect(cli.calls.map(call => call.operation)).toEqual([
      'resolve-agent-thread',
      'activate-refresh',
      'resolve-agent-thread',
      'bootstrap-command-pack',
      'heartbeat-prompt',
      'resolve-agent-thread',
      'resolve-agent-thread',
      'activate-refresh',
      'resolve-agent-thread',
      'bootstrap-command-pack',
      'heartbeat-prompt',
      'resolve-agent-thread',
    ])
  })

  it('preserves an applied activation refresh when later readback rejects arming', async () => {
    const cli = new FakeAuthorityCli(bound(), { commandPackValid: false })
    const service = await serviceWith(cli)
    const current = session()
    const result = await service.activate(current, 'goal-a', 'agent-a')
    expect(result).toMatchObject({
      ok: false,
      application: 'yes',
      subEffects: [{ operation: 'activate-refresh', application: 'yes' }],
    })
    expect(coordinatorFor(service).snapshot(current)?.activation).toBe('disarmed')
  })

  it('omits selected free-text status and identity fields from model-facing values', async () => {
    const cli = new FakeAuthorityCli(bound(), { commandPackValid: false })
    cli.statusItems = [{
      goal_id: 'goal-a',
      status: '/private/sentinel-status',
      waiting_on: '/private/sentinel-waiting',
      severity: 'warning',
      lifecycle_phase: 'active',
      recommended_action: '/private/sentinel-action',
    }]
    const service = await serviceWith(cli)
    const current = session()

    const status = await service.status(current)
    expect(status).toMatchObject({
      ok: true,
      value: { authority: { attention: [{ severity: 'warning', lifecyclePhase: 'active' }] } },
    })
    expect(JSON.stringify(status)).not.toContain('/private/sentinel')

    const selection = await service.attach(current, { goalId: 'goal-a' })
    expect(selection).toMatchObject({
      ok: true,
      value: {
        kind: 'selection_required',
        selection: { choices: [{ agentId: 'agent-a' }] },
      },
    })
    expect(JSON.stringify(selection)).not.toContain('/private/sentinel')
  })

  it('reports an unbound tombstone through pure status without a second command', async () => {
    const cli = new FakeAuthorityCli(unbound(4))
    const service = await serviceWith(cli)
    const result = await service.status(session())
    expect(result).toMatchObject({
      ok: true,
      application: 'no',
      value: {
        host: {
          activation: 'disarmed',
          binding: { state: 'unbound', revision: 4 },
        },
      },
    })
    expect(cli.calls.map(call => call.operation)).toEqual(['resolve-agent-thread'])
  })

  it('disarms on unhealthy authority and CAS-unbinds the bounded dangling ref', async () => {
    const cli = new FakeAuthorityCli(bound())
    const service = await serviceWith(cli)
    const current = session()
    await service.attach(current, { goalId: 'goal-a', agentId: 'agent-a' })
    expect(coordinatorFor(service).snapshot(current)?.activation).toBe('armed')

    cli.unhealthy = true
    await expect(service.resolveBinding(current)).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_AUTHORITY_UNHEALTHY' },
    })
    expect(coordinatorFor(service).snapshot(current)?.activation).toBe('disarmed')

    const detached = await service.detach(current)
    expect(detached).toMatchObject({
      ok: true,
      application: 'yes',
      value: { binding: { state: 'unbound', revision: 2 } },
    })
    expect(cli.calls.at(-1)?.args).toContain('1')
  })

  it('fails closed before invoking the CLI when no exact Session cwd selects authority', async () => {
    const cli = new FakeAuthorityCli(bound())
    const service = await serviceWith(cli, { loopxBin: 'loopx' })
    const result = await service.resolveBinding(session({}, null))
    expect(result).toMatchObject({
      ok: false,
      application: 'no',
      error: { code: 'LOOPX_BINDING_HOME_UNAVAILABLE' },
    })
    expect(cli.calls).toEqual([])
  })
})
