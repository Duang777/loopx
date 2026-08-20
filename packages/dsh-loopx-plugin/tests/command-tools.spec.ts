import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { describe, expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import { Inbox } from '@deepseek-ai/dsh-agent'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { CommandRuntime } from '@deepseek-ai/dsh-commands'
import type { CommandDefinition, CommandInvocation } from '@deepseek-ai/dsh-commands'
import { SessionId, SessionStore } from '@deepseek-ai/dsh-session'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import { validateJsonSchemaValue } from '@deepseek-ai/dsh-tools'
import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'
import { PLUGIN_VERSION, apply as applyCommand } from '../src/command.ts'
import {
  CoordinatorRegistry,
  installCoordinator,
} from '../src/coordinator.ts'
import { LoopXContinuationDriver } from '../src/driver.ts'
import { apply as applyTools } from '../src/tools.ts'
import type {
  LoopXAppliedSubEffect,
  LoopXAttachValue,
  LoopXBoundHostThreadBindingV1,
  LoopXFailure,
  LoopXResult,
  LoopXServiceApi,
  LoopXStartValue,
  LoopXStatusValue,
  LoopXTodoMutationValue,
} from '../src/types.ts'

const signal = new AbortController().signal

function success<T>(
  value: T,
  application: 'yes' | 'no' = 'no',
): LoopXResult<T> {
  return { ok: true, value, application }
}

function failure(
  code: LoopXFailure['code'],
  operation: string,
  application: 'yes' | 'no' | 'unknown' = 'no',
  subEffects?: readonly LoopXAppliedSubEffect[],
): LoopXResult<never> {
  return {
    ok: false,
    application,
    error: {
      code,
      message: `safe ${operation} failure`,
      operation,
      retryable: false,
      outcomeUncertain: application === 'unknown',
    },
    ...(subEffects === undefined ? {} : { subEffects }),
  }
}

function bound(revision = 3): LoopXBoundHostThreadBindingV1 {
  return Object.freeze({
    schemaVersion: 'loopx_host_thread_binding_v1',
    hostSurface: 'dsh',
    threadId: 'session-a',
    revision,
    state: 'bound',
    target: Object.freeze({ goalId: 'goal-a', agentId: 'agent-a' }),
  })
}

function planning(binding = bound()): LoopXStartValue {
  return {
    kind: 'planning',
    binding,
    planning: {
      schemaVersion: 'dsh_loopx_planning_checkpoint_v1',
      goalId: binding.target.goalId,
      agentId: binding.target.agentId,
      goalText: 'bounded objective',
      planner: {
        defaultProfile: 'clear_bounded_problem',
        profileSelection: 'select',
        openEndedProductDirection: { suggestedItemsMin: 2, suggestedItemsMax: 5, intent: 'rank' },
        clearBoundedProblem: {
          itemCountPolicy: 'planner_sized',
          mayReuseCurrentTodoWhenItAlreadyRepresentsThePlan: true,
          intent: 'plan',
        },
        allowedPriorities: ['P0', 'P1', 'P2'],
        defaultRole: 'agent',
        defaultTaskClass: 'advancement_task',
        requiredFields: ['priority', 'text'],
        publicSafeOnly: true,
        budgetPolicy: 'minimum',
      },
      writeback: {
        todoTool: 'loopx_todo_add',
        minimumTodos: 1,
        maximumTodos: 5,
        ordering: 'priority_then_tool_call_order',
        activationTool: 'loopx_goal_activate',
        activationArguments: { ...binding.target },
      },
      stopConditions: ['user gate'],
      forbidden: ['shell_or_bash', 'raw_loopx_cli', 'registry_edit', 'ctx.goals'],
    },
    modelCheckpoint: '<loopx_planning>plan</loopx_planning>',
  }
}

function statusValue(binding = bound()): LoopXStatusValue {
  return {
    host: {
      binarySource: 'path',
      binding,
      activation: 'disarmed',
      automaticFollowupSuppressed: false,
    },
    authority: {
      schemaVersion: 'loopx_status_projection_v1',
      ok: true,
      goalId: binding.target.goalId,
      attention: [{
        goalId: binding.target.goalId,
        status: 'active',
      }],
    },
  }
}

interface StubAgent {
  agent: Agent
  readonly followups: UserMessage[]
  readonly steers: UserMessage[]
  readonly nextTurn: UserMessage[]
  maintenanceClaims: number
  whenIdleCalls: number
  maintenanceCollisions: number
  throwDelivery: boolean
  setStatus(value: 'idle' | 'running'): void
}

interface CommandScope {
  readonly ctx: Context
  dispose(): Promise<void>
}

async function createCommandScope(ctx: Context, key: object): Promise<CommandScope> {
  const require = createRequire(import.meta.url)
  const commandsManifest = require.resolve('@deepseek-ai/dsh-commands/package.json')
  const commandsRequire = createRequire(commandsManifest)
  const scopeEntry = commandsRequire.resolve('@deepseek-ai/dsh-scope')
  const scopeModule = await import(/* @vite-ignore */ pathToFileURL(scopeEntry).href) as {
    createScope(context: Context, scopeKey: object): CommandScope
  }
  return scopeModule.createScope(ctx, key)
}

function stubAgent(id = 'session-a'): StubAgent {
  let status: 'idle' | 'running' = 'idle'
  const followups: UserMessage[] = []
  const steers: UserMessage[] = []
  const nextTurn: UserMessage[] = []
  const stub: StubAgent = {
    agent: undefined as unknown as Agent,
    followups,
    steers,
    nextTurn,
    maintenanceClaims: 0,
    whenIdleCalls: 0,
    maintenanceCollisions: 0,
    throwDelivery: false,
    setStatus(value) { status = value },
  }
  const session = { id, header: { version: 0, id, createdAt: 42, cwd: '/PRIVATE/CWD' } }
  stub.agent = {
    id,
    session,
    get status() { return status },
    inbox: {
      get nextTurn() { return nextTurn },
      nextStep: [],
      get hasPending() { return nextTurn.length > 0 },
      remove(messageId: UserMessage['id']) {
        const index = nextTurn.findIndex(message => message.id === messageId)
        if (index < 0) return false
        nextTurn.splice(index, 1)
        return true
      },
    },
    runMaintenance<T>(task: (taskSignal: AbortSignal) => Promise<T>): Promise<T> {
      stub.maintenanceClaims += 1
      if (stub.maintenanceCollisions > 0) {
        stub.maintenanceCollisions -= 1
        throw new Error('hidden maintenance owns idle')
      }
      return task(new AbortController().signal)
    },
    whenIdle() {
      stub.whenIdleCalls += 1
      return Promise.resolve()
    },
    followup(message: UserMessage) {
      if (stub.throwDelivery) throw new Error('followup failed')
      followups.push(message)
      nextTurn.push(message)
    },
    steer(message: UserMessage) {
      if (stub.throwDelivery) throw new Error('steer failed')
      steers.push(message)
    },
    send() {},
    cancel() {},
  } as unknown as Agent
  return stub
}

class FakeService {
  readonly coordinator = new CoordinatorRegistry()
  readonly calls: string[] = []
  startResult: LoopXResult<LoopXStartValue> = success(planning(), 'yes')
  attachResult: LoopXResult<LoopXAttachValue> = success({ kind: 'attached', binding: bound() }, 'yes')
  statusResult: LoopXResult<LoopXStatusValue> = success(statusValue())
  detachResult = success({
    detached: true as const,
    binding: {
      schemaVersion: 'loopx_host_thread_binding_v1' as const,
      hostSurface: 'dsh' as const,
      threadId: 'session-a',
      revision: 4,
      state: 'unbound' as const,
    },
  }, 'yes')

  constructor() {
    installCoordinator(this, this.coordinator)
  }

  status(): Promise<LoopXResult<LoopXStatusValue>> {
    this.calls.push('status')
    return Promise.resolve(this.statusResult)
  }

  start(): Promise<LoopXResult<LoopXStartValue>> {
    this.calls.push('start')
    return Promise.resolve(this.startResult)
  }

  attach(): Promise<LoopXResult<LoopXAttachValue>> {
    this.calls.push('attach')
    return Promise.resolve(this.attachResult)
  }

  resume() {
    this.calls.push('resume')
    return Promise.resolve(success(bound(), 'no'))
  }

  detach() {
    this.calls.push('detach')
    return Promise.resolve(this.detachResult)
  }

  pause() {
    this.calls.push('pause')
    return Promise.resolve(success({ paused: true as const, binding: bound() }, 'no'))
  }

  activate() {
    this.calls.push('activate')
    return Promise.resolve(success(bound(), 'yes'))
  }

  todoAdd() {
    this.calls.push('todoAdd')
    return Promise.resolve(success({
      todoId: 'todo-a', status: 'open' as const, priority: 'P0' as const, role: 'agent' as const,
      payload: {
        schemaVersion: 'loopx_todo_projection_v1' as const,
        goalId: 'goal-a', todoId: 'todo-a', status: 'open' as const, role: 'agent' as const,
        taskClass: 'advancement_task', actionKind: 'implement', added: true, alreadyExists: false,
      },
    }, 'yes'))
  }

  todoClaim() { return this.todoMutation('todoClaim') }
  todoUpdate() { return this.todoMutation('todoUpdate') }
  todoComplete() { return this.todoMutation('todoComplete') }

  private todoMutation(name: string) {
    this.calls.push(name)
    return Promise.resolve(success({
      todoId: 'todo-a', status: 'done',
      payload: {
        schemaVersion: 'loopx_todo_projection_v1' as const,
        goalId: 'goal-a', todoId: 'todo-a', status: 'done', changed: true,
      },
    }, 'yes'))
  }

  disposeSession(): Promise<void> {
    return Promise.resolve()
  }
}

function registerCommand(service: FakeService): CommandDefinition {
  let definition: CommandDefinition | undefined
  applyCommand({
    loopx: service,
    commands: { register(value: CommandDefinition) { definition = value } },
  } as unknown as Context)
  if (definition === undefined) throw new Error('command missing')
  return definition
}

async function runCommand(
  service: FakeService,
  current: StubAgent,
  rawInput: string,
  commandId = `cmd-${randomId++}`,
) {
  service.coordinator.commandRun(commandId, current.agent.session, current.agent)
  return registerCommand(service).handler({
    commandId,
    agent: current.agent,
    rawInput,
    signal,
  } as unknown as CommandInvocation)
}

let randomId = 1

function receiptFrom(message: UserMessage): Record<string, unknown> {
  const text = (message.content[0] as { readonly text: string }).text
  const start = text.indexOf('{"schemaVersion"')
  if (start < 0) throw new Error('receipt missing')
  return JSON.parse(text.slice(start)) as Record<string, unknown>
}

function receiptFromResult(result: { readonly text?: string }): Record<string, unknown> {
  if (result.text === undefined) throw new Error('command text missing')
  return JSON.parse(result.text.split('\n\nUsage:')[0] as string) as Record<string, unknown>
}

function registerTools(service: FakeService): ReadonlyMap<string, ToolDefinition> {
  const tools = new Map<string, ToolDefinition>()
  applyTools({
    loopx: service,
    tools: { register(value: ToolDefinition) { tools.set(value.name, value) } },
  } as unknown as Context)
  return tools
}

async function callTool(
  service: FakeService,
  name: string,
  args: unknown,
  agent: Agent,
): Promise<Record<string, unknown>> {
  const definition = registerTools(service).get(name)
  if (definition === undefined) throw new Error(`missing tool ${name}`)
  const value = await definition.execute(args, {
    name,
    arguments: args,
    agent,
    signal,
    callId: `call-${name}`,
    rootCallId: `call-${name}`,
    token: Symbol(name),
    deferContext() {},
    concludeTurn() {},
  } as unknown as ToolRunContext)
  expect(validateJsonSchemaValue(definition.output.schema, value, '')).toEqual([])
  return value as Record<string, unknown>
}

describe('/loopx closed grammar and routing', () => {
  it('returns exact version locally under an owned barrier', async () => {
    const service = new FakeService()
    const current = stubAgent()
    expect(await runCommand(service, current, ' version ')).toEqual({
      kind: 'success', text: `dsh-loopx-plugin ${PLUGIN_VERSION}`,
    })
    expect(service.calls).toEqual([])
    expect(current.followups).toEqual([])
  })

  it.each([
    ['', true],
    ['status', false],
  ] as const)('routes exact read %j through idle maintenance and followup', async (input, usage) => {
    const service = new FakeService()
    const current = stubAgent()
    const result = await runCommand(service, current, input)
    expect(service.calls).toEqual(['status'])
    expect(current.maintenanceClaims).toBe(1)
    expect(current.followups).toHaveLength(1)
    expect(receiptFrom(current.followups[0] as UserMessage)).toMatchObject({
      kind: 'operation_result', operation: 'status', execution: 'succeeded',
      application: 'no', delivery: 'followup_queued',
    })
    expect(result.text?.includes('Usage: /loopx')).toBe(usage)
    expect(JSON.stringify(result)).not.toContain('/PRIVATE/CWD')
  })

  it.each([
    ['start ship it', 'start'],
    ['attach goal-a', 'attach'],
    ['attach goal-a agent-a', 'attach'],
    ['attach goal-a --new-peer', 'attach'],
    ['resume', 'resume'],
    ['detach', 'detach'],
  ] as const)('executes exact idle write %j once', async (input, call) => {
    const service = new FakeService()
    const current = stubAgent()
    await runCommand(service, current, input)
    expect(service.calls).toEqual([call])
    expect(current.maintenanceClaims).toBe(1)
    expect(current.followups).toHaveLength(1)
    expect(receiptFrom(current.followups[0] as UserMessage)).toMatchObject({
      kind: 'operation_result', execution: 'succeeded', delivery: 'followup_queued',
    })
  })

  it.each([
    'start', 'attach', 'attach --new-peer', 'attach --new-peer goal-a',
    'attach goal-a --new-peer extra', 'attach goal-a agent-a extra',
    'status now', 'pause please', 'resume later', 'detach goal-a',
    'version with details', 'please status', 'start\nobjective',
    'status\n', 'attach goal-a\r\n', 'start objective\n',
  ])('preserves non-grammar input %j as semantic data', async (input) => {
    const service = new FakeService()
    const current = stubAgent()
    await runCommand(service, current, input)
    expect(service.calls).toEqual([])
    const receipt = receiptFrom(current.followups[0] as UserMessage)
    expect(receipt).toMatchObject({
      kind: 'semantic_request', request: input, execution: 'not_attempted', application: 'no',
    })
  })

  it('uses running steer for reads and typed not-attempted intent for writes', async () => {
    const service = new FakeService()
    const current = stubAgent()
    current.setStatus('running')
    await runCommand(service, current, 'status')
    expect(service.calls).toEqual(['status'])
    expect(receiptFrom(current.steers[0] as UserMessage)).toMatchObject({
      kind: 'operation_result', delivery: 'steered',
    })

    service.calls.length = 0
    await runCommand(service, current, 'attach goal-a --new-peer')
    expect(service.calls).toEqual([])
    expect(receiptFrom(current.steers[1] as UserMessage)).toMatchObject({
      kind: 'typed_intent', operation: 'goal-attach', execution: 'not_attempted',
      arguments: { goalId: 'goal-a', newPeer: true }, delivery: 'steered',
    })
  })

  it('pauses synchronously without Service admission and only steers while running', async () => {
    const service = new FakeService()
    const current = stubAgent()
    const ref = {
      id: 'session-a', session: current.agent.session,
      identity: { createdAt: 42, cwd: '/PRIVATE/CWD' },
    }
    service.coordinator.observeBinding(ref, { key: 'home', cwd: '/PRIVATE/CWD' }, bound())
    service.coordinator.arm(ref, { key: 'home', cwd: '/PRIVATE/CWD' }, bound())
    expect((await runCommand(service, current, 'pause')).kind).toBe('success')
    expect(service.calls).toEqual([])
    expect(service.coordinator.snapshot(ref)?.activation).toBe('disarmed')
    expect(current.followups).toEqual([])

    service.coordinator.arm(ref, { key: 'home', cwd: '/PRIVATE/CWD' }, bound())
    current.setStatus('running')
    await runCommand(service, current, 'pause')
    expect(receiptFrom(current.steers[0] as UserMessage)).toMatchObject({
      operation: 'driver-pause', application: 'no', delivery: 'steered',
    })
  })

  it('waits for a hidden maintenance owner without busy-running the Service', async () => {
    const service = new FakeService()
    const current = stubAgent()
    current.maintenanceCollisions = 1
    await runCommand(service, current, 'status')
    expect(current.maintenanceClaims).toBe(2)
    expect(current.whenIdleCalls).toBe(1)
    expect(service.calls).toEqual(['status'])
  })

  it('keeps an applied write receipt non-retryable when delivery fails', async () => {
    const service = new FakeService()
    const current = stubAgent()
    current.throwDelivery = true
    const result = await runCommand(service, current, 'detach')
    expect(result.kind).toBe('error')
    expect(receiptFromResult(result)).toMatchObject({
      execution: 'succeeded', application: 'yes', delivery: 'failed', recovery: 'none',
    })
    expect(service.calls).toEqual(['detach'])
  })

  it('does not release an owned barrier on early command/done', async () => {
    const service = new FakeService()
    const current = stubAgent()
    const pending = Promise.withResolvers<LoopXResult<LoopXStatusValue>>()
    service.status = () => pending.promise
    const commandId = 'early-done'
    service.coordinator.commandRun(commandId, current.agent.session, current.agent)
    const operation = registerCommand(service).handler({
      commandId, agent: current.agent, rawInput: 'status', signal,
    } as unknown as CommandInvocation)
    service.coordinator.commandDone(commandId, current.agent.session)
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(true)
    pending.resolve(success(statusValue()))
    await operation
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(false)
  })

  it('settles a synchronous Service throw once and releases its owned barrier', async () => {
    const service = new FakeService()
    const current = stubAgent()
    current.setStatus('running')
    service.status = () => { throw new Error('synchronous Service failure') }
    let releases = 0
    const stop = service.coordinator.onInvalidated(event => {
      if (event.kind === 'barrier_released') releases += 1
    })
    const commandId = 'synchronous-throw'
    service.coordinator.commandRun(commandId, current.agent.session, current.agent)
    const operation = registerCommand(service).handler({
      commandId, agent: current.agent, rawInput: 'status', signal,
    } as unknown as CommandInvocation)
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(true)
    await operation
    stop()
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(false)
    expect(service.coordinator.snapshot(current.agent.session)?.failureCount).toBe(1)
    expect(releases).toBe(1)
  })

  it('keeps overlapping owned command ids isolated within one Session', async () => {
    const service = new FakeService()
    const current = stubAgent()
    current.setStatus('running')
    const first = Promise.withResolvers<LoopXResult<LoopXStatusValue>>()
    const second = Promise.withResolvers<LoopXResult<LoopXStatusValue>>()
    const pending = [first, second]
    service.status = () => {
      const operation = pending.shift()
      if (operation === undefined) throw new Error('unexpected status call')
      return operation.promise
    }
    const handler = registerCommand(service).handler
    service.coordinator.commandRun('overlap-a', current.agent.session, current.agent)
    const operationA = handler({
      commandId: 'overlap-a', agent: current.agent, rawInput: 'status', signal,
    } as unknown as CommandInvocation)
    service.coordinator.commandRun('overlap-b', current.agent.session, current.agent)
    const operationB = handler({
      commandId: 'overlap-b', agent: current.agent, rawInput: 'status', signal,
    } as unknown as CommandInvocation)

    service.coordinator.commandDone('overlap-a', current.agent.session)
    first.resolve(success(statusValue()))
    await operationA
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(true)

    service.coordinator.commandDone('overlap-b', current.agent.session)
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(true)
    second.resolve(success(statusValue()))
    await operationB
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(false)
  })

  it('keeps an owned barrier through UI abort until raw cancellation settles', async () => {
    const service = new FakeService()
    const current = stubAgent()
    current.setStatus('running')
    const controller = new AbortController()
    const pending = Promise.withResolvers<LoopXResult<LoopXStatusValue>>()
    service.status = (...args: unknown[]) => {
      expect(args[1]).toBe(controller.signal)
      return pending.promise
    }
    const commandId = 'ui-abort'
    service.coordinator.commandRun(commandId, current.agent.session, current.agent)
    const operation = registerCommand(service).handler({
      commandId, agent: current.agent, rawInput: 'status', signal: controller.signal,
    } as unknown as CommandInvocation)

    controller.abort(new Error('UI request cancelled'))
    service.coordinator.commandDone(commandId, current.agent.session)
    await Promise.resolve()
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(true)
    expect(service.coordinator.snapshot(current.agent.session)?.failureCount).toBe(0)

    pending.resolve(failure('LOOPX_CLI_ABORTED', 'status'))
    await operation
    expect(service.coordinator.hasBarrier(current.agent.session)).toBe(false)
    expect(service.coordinator.snapshot(current.agent.session)?.failureCount).toBe(0)
    expect(receiptFrom(current.steers[0] as UserMessage)).toMatchObject({
      error: { code: 'LOOPX_CLI_ABORTED' },
    })
  })

  it('does not count a coordinator-cancelled command as a breaker failure', async () => {
    const service = new FakeService()
    const current = stubAgent()
    service.statusResult = failure('LOOPX_DRIVER_NOT_ARMED', 'status')
    await runCommand(service, current, ' status ')
    expect(service.coordinator.snapshot(current.agent.session)?.failureCount).toBe(0)
    expect(receiptFrom(current.followups[0] as UserMessage)).toMatchObject({
      request: ' status ',
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })
  })

  it('uses real CommandRuntime ownership for global /loopx and an agent-scoped shadow', async () => {
    const ctx = new Context()
    const service = new FakeService()
    let driver: LoopXContinuationDriver | undefined
    let agentScope: CommandScope | undefined
    let stopEvents: (() => void) | undefined
    try {
      await ctx.plugin(SessionStore)
      await ctx.plugin(CommandRuntime)
      let commandsCtx: Context | undefined
      await ctx.inject(['commands'], injected => { commandsCtx = injected })
      if (commandsCtx === undefined) throw new Error('commands dependency context missing')
      const session = ctx.sessions.create(SessionId('session-a'), { meta: { cwd: '/workspace' } })
      const agent = {} as Agent
      agentScope = await createCommandScope(commandsCtx, agent)
      const inbox = new Inbox(session, {
        inserted() {},
        discarded() {},
        claimed() {},
      })
      Object.assign(agent, {
        id: session.id,
        options: Object.freeze({}),
        session,
        inbox,
        status: 'running' as const,
        ctx: agentScope.ctx,
        cancel() {},
        whenIdle: () => Promise.resolve(),
        runMaintenance: <T>(task: (taskSignal: AbortSignal) => Promise<T>) =>
          task(new AbortController().signal),
        send() {},
        followup() {},
        steer() {},
        inject() {},
      })

      driver = new LoopXContinuationDriver({
        service: service as unknown as LoopXServiceApi,
        isLiveAgent: candidate => candidate === agent,
      })
      driver.observeAgent(agent)
      stopEvents = ctx.on('session/event', (published, event) => {
        if (published === session) driver?.onSessionEvent(agent, event)
      })
      const current = Object.freeze({
        id: String(session.id),
        session,
        identity: Object.freeze({
          createdAt: session.header.createdAt,
          cwd: session.header.cwd,
        }),
      })
      service.coordinator.observeBinding(current, { key: 'home', cwd: '/workspace' }, bound())
      service.coordinator.arm(current, { key: 'home', cwd: '/workspace' }, bound())

      applyCommand(commandsCtx.extend({ loopx: service }) as Context)
      const globalExecution = await ctx.commands.execute(agent, '/loopx version', signal)
      await Promise.resolve()
      expect(globalExecution).toMatchObject({
        result: { kind: 'success', text: `dsh-loopx-plugin ${PLUGIN_VERSION}` },
      })
      expect(service.coordinator.snapshot(current)).toMatchObject({
        activation: 'armed', foreignLatched: false, barred: false,
      })

      agentScope.ctx.commands.register({
        name: 'loopx',
        description: 'agent-owned shadow',
        handler: () => ({ kind: 'success', text: 'shadow-owned' }),
      })
      const shadowExecution = await ctx.commands.execute(agent, '/loopx version', signal)
      await Promise.resolve()
      expect(shadowExecution).toMatchObject({
        result: { kind: 'success', text: 'shadow-owned' },
      })
      expect(service.coordinator.snapshot(current)).toMatchObject({
        activation: 'disarmed', foreignLatched: true, barred: false,
      })

      const lifecycle = session.events.filter(event =>
        event.type === 'command/run' || event.type === 'command/done')
      expect(lifecycle).toMatchObject([
        { type: 'command/run', data: { name: 'loopx' } },
        { type: 'command/done', data: { kind: 'success' } },
        { type: 'command/run', data: { name: 'loopx' } },
        { type: 'command/done', data: { kind: 'success', text: 'shadow-owned' } },
      ])
      expect(lifecycle[0]?.data.commandId).toBe(lifecycle[1]?.data.commandId)
      expect(lifecycle[2]?.data.commandId).toBe(lifecycle[3]?.data.commandId)
    } finally {
      stopEvents?.()
      await driver?.dispose()
      await agentScope?.dispose()
      await ctx.fiber.dispose()
    }
  })
})

describe('typed tool receipts', () => {
  it('registers eleven closed tools and removes obsolete start selectors', () => {
    const tools = registerTools(new FakeService())
    expect(tools.size).toBe(11)
    for (const tool of tools.values()) {
      expect(tool.parameters).toMatchObject({ type: 'object', additionalProperties: false })
    }
    expect(Object.keys(tools.get('loopx_goal_start')?.parameters.properties ?? {})).toEqual([
      'goalText', 'switchConfirmation',
    ])
  })

  it('takes application from Service, including a successful no-op', async () => {
    const service = new FakeService()
    service.attachResult = success({ kind: 'attached', binding: bound() }, 'no')
    const result = await callTool(service, 'loopx_goal_attach', {
      goalId: 'goal-a', agentId: 'agent-a',
    }, stubAgent().agent)
    expect(result).toMatchObject({
      schemaVersion: 'dsh_loopx_operation_receipt_v1',
      kind: 'operation_result', execution: 'succeeded', application: 'no',
      delivery: 'not_needed',
    })
  })

  it('filters coordinator cancellation but counts a terminal tool failure', async () => {
    const service = new FakeService()
    const current = stubAgent().agent
    service.startResult = failure('LOOPX_FOREIGN_COMMAND_ACTIVE', 'goal-start')
    await callTool(service, 'loopx_goal_start', { goalText: 'safe' }, current)
    expect(service.coordinator.snapshot(current.session)?.failureCount).toBe(0)

    service.startResult = failure('LOOPX_READBACK_FAILED', 'goal-start')
    await callTool(service, 'loopx_goal_start', { goalText: 'safe' }, current)
    expect(service.coordinator.snapshot(current.session)?.failureCount).toBe(1)
  })

  it('preserves bounded committed sub-effects on a rejected operation', async () => {
    const service = new FakeService()
    service.attachResult = failure('LOOPX_CLI_FAILED', 'goal-attach', 'yes', [{
      operation: 'register-agent', application: 'yes',
      target: { goalId: 'goal-a', agentId: 'fresh-a' },
    }])
    const result = await callTool(service, 'loopx_goal_attach', {
      goalId: 'goal-a', newPeer: true,
    }, stubAgent().agent)
    expect(result).toMatchObject({
      execution: 'rejected', application: 'yes', recovery: 'read_authority_then_decide',
      subEffects: [{ operation: 'register-agent', application: 'yes' }],
    })
  })

  it('maps an indeterminate write to unknown application and authoritative readback', async () => {
    const service = new FakeService()
    service.detachResult = failure('LOOPX_CLI_TIMEOUT', 'goal-detach', 'unknown')
    const result = await callTool(service, 'loopx_goal_detach', {}, stubAgent().agent)
    expect(result).toMatchObject({
      execution: 'indeterminate', application: 'unknown',
      recovery: 'read_authority_then_decide', delivery: 'not_needed',
    })
  })

  it('projects only bounded status and Todo fields', async () => {
    const service = new FakeService()
    const current = stubAgent().agent
    service.statusResult = success({
      ...statusValue(),
      authority: {
        ...statusValue().authority,
        runtimeRoot: '/PRIVATE/RUNTIME',
        rawStderr: 'SECRET STDERR',
      },
    } as unknown as LoopXStatusValue)
    service.todoUpdate = (() => Promise.resolve(success({
      todoId: 'todo-a',
      status: 'done',
      payload: {
        schemaVersion: 'loopx_todo_projection_v1',
        goalId: 'goal-a',
        todoId: 'todo-a',
        status: 'done',
        changed: true,
        project: '/PRIVATE/PROJECT',
        registry: '/PRIVATE/REGISTRY',
        state_file: '/PRIVATE/STATE',
      },
    } as unknown as LoopXTodoMutationValue, 'yes'))) as unknown as FakeService['todoUpdate']
    const status = await callTool(service, 'loopx_status', {}, current)
    const todo = await callTool(service, 'loopx_todo_update', {
      todoId: 'todo-a', status: 'done',
    }, current)
    const rendered = JSON.stringify([status, todo])
    expect(rendered).toContain('loopx_status_projection_v1')
    expect(rendered).toContain('loopx_todo_projection_v1')
    expect(rendered).not.toContain('/PRIVATE/CWD')
    expect(rendered).not.toContain('SECRET STDERR')
    expect(rendered).not.toMatch(/projectLocator|registryLocator|runtimeRoot|state_file|raw stderr/i)
    expect(rendered).not.toMatch(/PRIVATE\/(?:PROJECT|REGISTRY|STATE|RUNTIME)/)
  })

  it('rejects alternate identity and locator keys before Service admission', async () => {
    const service = new FakeService()
    const result = await callTool(service, 'loopx_goal_start', {
      goalText: 'safe objective', runtimeRoot: '/PRIVATE/RUNTIME', argv: ['loopx'],
    }, stubAgent().agent)
    expect(result).toMatchObject({
      execution: 'rejected', application: 'no', error: { code: 'LOOPX_INVALID_REQUEST' },
    })
    expect(service.calls).toEqual([])
  })
})
