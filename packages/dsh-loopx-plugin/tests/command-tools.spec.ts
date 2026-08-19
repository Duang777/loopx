import { describe, expect, it } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import type { CommandDefinition, CommandInvocation } from '@deepseek-ai/dsh-commands'
import { validateJsonSchemaValue } from '@deepseek-ai/dsh-tools'
import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'
import { PLUGIN_VERSION, apply as applyCommand } from '../src/command.ts'
import { apply as applyTools } from '../src/tools.ts'
import type {
  LoopXAttachRequest,
  LoopXAttachValue,
  LoopXBindingFence,
  LoopXBindingPhase,
  LoopXBindingReason,
  LoopXBindingRow,
  LoopXFailure,
  LoopXPlanningCheckpoint,
  LoopXQuotaDecision,
  LoopXResult,
  LoopXSchedulerHint,
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStartValue,
  LoopXStatusValue,
  LoopXTaskBody,
  LoopXTodoClaimRequest,
  LoopXTodoAddRequest,
  LoopXTodoAddValue,
  LoopXTodoCompleteRequest,
  LoopXTodoMutationValue,
  LoopXTodoUpdateRequest,
} from '../src/types.ts'

const signal = new AbortController().signal

function success<T>(value: T): LoopXResult<T> {
  return { ok: true, value }
}

function failure(
  code: LoopXFailure['code'],
  operation: string,
  outcomeUncertain = false,
): LoopXResult<never> {
  return {
    ok: false,
    error: {
      code,
      message: `safe ${operation} failure`,
      operation,
      retryable: false,
      outcomeUncertain,
    },
  }
}

function binding(
  phase: LoopXBindingPhase = 'active_armed',
  overrides: Partial<LoopXBindingRow> = {},
): LoopXBindingRow {
  return {
    schemaVersion: 'loopx_dsh_binding_row_v0',
    session: { createdAt: 42, cwd: 'SENSITIVE_SESSION_CWD' },
    hostSurface: 'deepseek-harness-native',
    goalId: 'goal-a',
    agentId: 'agent-a',
    projectLocator: 'SENSITIVE_PROJECT_LOCATOR',
    registryLocator: 'SENSITIVE_REGISTRY_LOCATOR',
    runtimeRootLocator: 'SENSITIVE_RUNTIME_LOCATOR',
    phase,
    generation: 3,
    unchangedPollCount: 0,
    bindingCreatedAt: 40,
    updatedAt: 42,
    ...overrides,
  }
}

function planning(goalId = 'goal-a', agentId = 'agent-a'): LoopXPlanningCheckpoint {
  return {
    schemaVersion: 'dsh_loopx_planning_checkpoint_v0',
    goalId,
    agentId,
    goalText: 'plan the bounded work',
    planner: {
      defaultProfile: 'clear_bounded_problem',
      profileSelection: 'select the matching profile',
      openEndedProductDirection: { suggestedItemsMin: 2, suggestedItemsMax: 5, intent: 'rank work' },
      clearBoundedProblem: {
        itemCountPolicy: 'planner_sized',
        mayReuseCurrentTodoWhenItAlreadyRepresentsThePlan: true,
        intent: 'minimum sufficient plan',
      },
      allowedPriorities: ['P0', 'P1', 'P2'],
      defaultRole: 'agent',
      defaultTaskClass: 'advancement_task',
      requiredFields: ['priority', 'text', 'task_class', 'action_kind'],
      publicSafeOnly: true,
      budgetPolicy: 'minimum sufficient plan',
    },
    writeback: {
      todoTool: 'loopx_todo_add',
      minimumTodos: 1,
      maximumTodos: 5,
      ordering: 'priority_then_tool_call_order',
      activationTool: 'loopx_goal_activate',
      activationArguments: { goalId, agentId },
    },
    stopConditions: ['stop at a user gate'],
    forbidden: ['shell_or_bash', 'raw_loopx_cli', 'registry_edit', 'ctx.goals'],
  }
}

interface StubAgent {
  readonly agent: Agent
  readonly followups: unknown[]
  readonly sends: unknown[]
  readonly toolDefinitions: Map<string, ToolDefinition>
}

function stubAgent(
  id = 'session-current',
  createdAt = 42,
  cwd = 'SENSITIVE_SESSION_CWD',
): StubAgent {
  const followups: unknown[] = []
  const sends: unknown[] = []
  const toolDefinitions = new Map<string, ToolDefinition>()
  const nextTurn: UserMessage[] = []
  const session = {
    id,
    header: { version: 0, id, createdAt, cwd },
  }
  const agent = {
    id,
    session,
    status: 'idle',
    inbox: {
      nextTurn,
      nextStep: [],
      get hasPending() { return nextTurn.length > 0 },
    },
    ctx: { tools: { get(name: string) { return toolDefinitions.get(name) } } },
    followup(message: UserMessage) { followups.push(message); nextTurn.push(message) },
    send(message: UserMessage) { sends.push(message); nextTurn.push(message) },
    cancel() {},
    whenIdle() { return Promise.resolve() },
  } as unknown as Agent
  return { agent, followups, sends, toolDefinitions }
}

class FakeService implements LoopXServiceApi {
  binding: LoopXBindingRow | undefined
  startResult: LoopXResult<LoopXStartValue> | undefined
  attachResult: LoopXResult<LoopXAttachValue> | undefined
  activateResult: LoopXResult<LoopXBindingRow> | undefined
  statusResult: LoopXResult<LoopXStatusValue> | undefined
  detachResult: LoopXResult<{ readonly detached: true }> | undefined
  todoFailure: LoopXResult<never> | undefined
  readonly sessions: LoopXSessionRef[] = []
  readonly starts: string[] = []
  readonly attaches: LoopXAttachRequest[] = []
  readonly activations: { goalId: string; agentId?: string }[] = []
  readonly claims: LoopXTodoClaimRequest[] = []
  readonly additions: LoopXTodoAddRequest[] = []
  readonly updates: LoopXTodoUpdateRequest[] = []
  readonly completions: LoopXTodoCompleteRequest[] = []
  readonly pauses: LoopXBindingReason[] = []
  readonly pauseFences: Array<LoopXBindingFence | undefined> = []
  readonly uncertainFences: Array<LoopXBindingFence | undefined> = []
  uncertainCalls = 0
  statusCalls = 0

  constructor(initial: LoopXBindingRow | null = binding()) {
    this.binding = initial ?? undefined
  }

  getBinding(session: LoopXSessionRef): LoopXResult<LoopXBindingRow | undefined> {
    this.sessions.push(session)
    return success(this.binding)
  }

  start(
    session: LoopXSessionRef,
    goalText: string,
    _signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXStartValue>> {
    this.sessions.push(session)
    this.starts.push(goalText)
    const planned = binding('planning')
    this.binding = planned
    return Promise.resolve(this.startResult ?? success({
      kind: 'planning',
      binding: planned,
      planning: planning(planned.goalId, planned.agentId),
      modelCheckpoint: '<loopx_planning>write the plan and Todos</loopx_planning>',
    }))
  }

  attach(
    session: LoopXSessionRef,
    request: LoopXAttachRequest,
    _signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    this.sessions.push(session)
    this.attaches.push(request)
    const attached = binding('active_armed', {
      goalId: request.goalId,
      agentId: request.agentId ?? (request.newPeer === true ? 'fresh-peer' : 'agent-a'),
    })
    this.binding = attached
    return Promise.resolve(this.attachResult ?? success({ kind: 'attached', binding: attached }))
  }

  activate(
    session: LoopXSessionRef,
    goalId: string,
    agentId?: string,
    _signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    this.sessions.push(session)
    this.activations.push({ goalId, ...(agentId === undefined ? {} : { agentId }) })
    if (this.activateResult !== undefined) return Promise.resolve(this.activateResult)
    if (this.binding === undefined || this.binding.goalId !== goalId
      || (agentId !== undefined && this.binding.agentId !== agentId)) {
      return Promise.resolve(failure('LOOPX_IDENTITY_CONFLICT', 'goal-activate'))
    }
    this.binding = binding('active_armed', {
      goalId: this.binding.goalId,
      agentId: this.binding.agentId,
      generation: this.binding.generation + 1,
    })
    return Promise.resolve(success(this.binding))
  }

  status(
    session: LoopXSessionRef,
    _signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXStatusValue>> {
    this.sessions.push(session)
    this.statusCalls += 1
    return Promise.resolve(this.statusResult ?? success({
      host: {
        binarySource: 'path',
        ...(this.binding === undefined ? {} : { binding: this.binding }),
      },
      ...(this.binding === undefined ? {} : {
        authority: {
          schema_version: 'loopx_status_v0',
          ok: true,
          goal_filter: this.binding.goalId,
          attention_queue: { items: [{ goal_id: this.binding.goalId, status: 'active' }] },
        },
      }),
    }))
  }

  pause(
    session: LoopXSessionRef,
    reason: LoopXBindingReason = 'user_pause',
    expectedFence?: LoopXBindingFence,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    this.sessions.push(session)
    this.pauses.push(reason)
    this.pauseFences.push(expectedFence)
    if (this.binding === undefined) return Promise.resolve(failure('LOOPX_SESSION_NOT_BOUND', 'pause'))
    this.binding = binding(this.binding.phase === 'planning' ? 'planning' : 'active_paused', {
      goalId: this.binding.goalId,
      agentId: this.binding.agentId,
      generation: this.binding.generation + 1,
      reason,
    })
    return Promise.resolve(success(this.binding))
  }

  resume(session: LoopXSessionRef): Promise<LoopXResult<LoopXBindingRow>> {
    this.sessions.push(session)
    if (this.binding === undefined) return Promise.resolve(failure('LOOPX_SESSION_NOT_BOUND', 'resume'))
    this.binding = binding('active_armed', {
      goalId: this.binding.goalId,
      agentId: this.binding.agentId,
      generation: this.binding.generation + 1,
    })
    return Promise.resolve(success(this.binding))
  }

  detach(session: LoopXSessionRef): Promise<LoopXResult<{ readonly detached: true }>> {
    this.sessions.push(session)
    if (this.detachResult !== undefined) {
      if (!this.detachResult.ok && this.detachResult.error.outcomeUncertain && this.binding !== undefined) {
        this.binding = binding('uncertain', {
          goalId: this.binding.goalId,
          agentId: this.binding.agentId,
          reason: 'uncertain_write',
        })
      }
      return Promise.resolve(this.detachResult)
    }
    this.binding = undefined
    return Promise.resolve(success({ detached: true }))
  }

  todoAdd(
    session: LoopXSessionRef,
    request: LoopXTodoAddRequest,
  ): Promise<LoopXResult<LoopXTodoAddValue>> {
    this.sessions.push(session)
    this.additions.push(request)
    if (this.todoFailure !== undefined) return Promise.resolve(this.todoFailure)
    return Promise.resolve(success({
      todoId: 'todo-added',
      status: 'open',
      priority: request.priority,
      role: request.role ?? 'agent',
      payload: { schema_version: 'loopx_todo_command_v0', ok: true },
    }))
  }

  todoClaim(
    session: LoopXSessionRef,
    request: LoopXTodoClaimRequest,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    this.sessions.push(session)
    this.claims.push(request)
    if (this.todoFailure !== undefined) return Promise.resolve(this.todoFailure)
    return Promise.resolve(success({
      todoId: request.todoId,
      status: 'claimed',
      payload: { schema_version: 'loopx_todo_command_v0', ok: true, todo_id: request.todoId },
    }))
  }

  todoUpdate(
    session: LoopXSessionRef,
    request: LoopXTodoUpdateRequest,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    this.sessions.push(session)
    this.updates.push(request)
    if (this.todoFailure !== undefined) return Promise.resolve(this.todoFailure)
    return Promise.resolve(success({
      todoId: request.todoId,
      status: request.status,
      payload: { schema_version: 'loopx_todo_command_v0', ok: true, todo_id: request.todoId },
    }))
  }

  todoComplete(
    session: LoopXSessionRef,
    request: LoopXTodoCompleteRequest,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    this.sessions.push(session)
    this.completions.push(request)
    if (this.todoFailure !== undefined) return Promise.resolve(this.todoFailure)
    return Promise.resolve(success({
      todoId: request.todoId,
      status: 'done',
      payload: { schema_version: 'loopx_todo_command_v0', ok: true, todo_id: request.todoId },
    }))
  }

  quotaShouldRun(): Promise<LoopXResult<LoopXQuotaDecision>> {
    return Promise.resolve(failure('LOOPX_DRIVER_NOT_ARMED', 'quota'))
  }

  taskBody(): Promise<LoopXResult<LoopXTaskBody>> {
    return Promise.resolve(failure('LOOPX_DRIVER_NOT_ARMED', 'task-body'))
  }

  updateScheduler(
    _session: LoopXSessionRef,
    _fence: LoopXBindingFence,
    _hint: LoopXSchedulerHint,
    _unchangedPollCount: number,
    _nextCheckAt?: number,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    return Promise.resolve(failure('LOOPX_DRIVER_NOT_ARMED', 'scheduler'))
  }

  fence(): LoopXResult<LoopXBindingFence> {
    return failure('LOOPX_DRIVER_NOT_ARMED', 'fence')
  }

  fenceIsCurrent(): boolean {
    return false
  }

  markUncertain(
    session: LoopXSessionRef,
    reason: LoopXBindingReason = 'uncertain_write',
    expectedFence?: LoopXBindingFence,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    this.sessions.push(session)
    this.uncertainCalls += 1
    this.uncertainFences.push(expectedFence)
    if (this.binding === undefined) return Promise.resolve(failure('LOOPX_SESSION_NOT_BOUND', 'uncertain'))
    this.binding = binding('uncertain', {
      goalId: this.binding.goalId,
      agentId: this.binding.agentId,
      generation: this.binding.generation + 1,
      reason,
    })
    return Promise.resolve(success(this.binding))
  }

  disposeSession(): Promise<void> {
    return Promise.resolve()
  }
}

function invocation(agent: Agent, rawInput: string): CommandInvocation {
  return { commandId: 'command-test', agent, rawInput, signal } as unknown as CommandInvocation
}

function registerCommand(service: LoopXServiceApi): CommandDefinition {
  let definition: CommandDefinition | undefined
  const ctx = {
    loopx: service,
    commands: { register(value: CommandDefinition) { definition = value } },
  } as unknown as Context
  applyCommand(ctx)
  if (definition === undefined) throw new Error('command was not registered')
  return definition
}

function runCommand(service: LoopXServiceApi, agent: Agent, rawInput: string) {
  return registerCommand(service).handler(invocation(agent, rawInput))
}

function registerTools(service: LoopXServiceApi): ReadonlyMap<string, ToolDefinition> {
  const definitions = new Map<string, ToolDefinition>()
  const ctx = {
    loopx: service,
    tools: { register(value: ToolDefinition) { definitions.set(value.name, value) } },
  } as unknown as Context
  applyTools(ctx)
  return definitions
}

async function callTool(
  definitions: ReadonlyMap<string, ToolDefinition>,
  name: string,
  args: unknown,
  agent?: Agent,
): Promise<Record<string, unknown>> {
  const definition = definitions.get(name)
  if (definition === undefined) throw new Error(`missing tool ${name}`)
  const exec = {
    name,
    arguments: args,
    agent,
    signal,
    callId: `call-${name}`,
    rootCallId: `call-${name}`,
    token: Symbol(name),
    deferContext() {},
    concludeTurn() {},
  } as unknown as ToolRunContext
  const value = await definition.execute(args, exec)
  expect(validateJsonSchemaValue(definition.output.schema, value, '')).toEqual([])
  return value as Record<string, unknown>
}

function errorCode(value: Record<string, unknown>): unknown {
  return (value.error as Record<string, unknown> | undefined)?.code
}

function semanticFollowupText(current: StubAgent): string {
  expect(current.followups).toHaveLength(1)
  expect(current.sends).toEqual([])
  const message = current.followups[0] as {
    readonly role?: unknown
    readonly source?: unknown
    readonly content?: readonly { readonly type?: unknown; readonly text?: unknown }[]
  }
  expect(message).toMatchObject({
    role: 'user',
    source: { kind: 'plugin', plugin: 'dsh-loopx-plugin' },
  })
  expect(message.content).toHaveLength(1)
  expect(message.content?.[0]).toMatchObject({ type: 'text' })
  const text = message.content?.[0]?.text
  if (typeof text !== 'string') throw new TypeError('semantic follow-up text is missing')
  return text
}

function expectNoCommandServiceCalls(service: FakeService): void {
  expect(service.sessions).toEqual([])
  expect(service.statusCalls).toBe(0)
  expect(service.starts).toEqual([])
  expect(service.attaches).toEqual([])
  expect(service.activations).toEqual([])
  expect(service.additions).toEqual([])
  expect(service.claims).toEqual([])
  expect(service.updates).toEqual([])
  expect(service.completions).toEqual([])
  expect(service.pauses).toEqual([])
  expect(service.uncertainCalls).toBe(0)
}

describe('/loopx command', () => {
  it('returns exact version locally without a follow-up or LoopX service call', async () => {
    const service = new FakeService()
    const current = stubAgent()
    Object.defineProperty(current.agent, 'id', { value: 'mismatched-agent' })

    expect(await runCommand(service, current.agent, ' version ')).toEqual({
      kind: 'success',
      text: `dsh-loopx-plugin ${PLUGIN_VERSION}`,
    })
    expect(current.followups).toEqual([])
    expect(current.sends).toEqual([])
    expectNoCommandServiceCalls(service)
  })

  it('keeps empty input on the local status/help path without a follow-up', async () => {
    const service = new FakeService()
    const current = stubAgent()
    const definition = registerCommand(service)
    expect(definition.name).toBe('loopx')

    const result = await definition.handler(invocation(current.agent, ''))
    expect(result.kind).toBe('success')
    expect(result.text).toContain('DSH Host sidecar (Host binding/driver state; not Goal or Todo authority)')
    expect(result.text).toContain('LoopX authoritative state (live CLI readback)')
    expect(result.text).not.toContain('SENSITIVE_PROJECT_LOCATOR')
    expect(result.text).not.toContain('SENSITIVE_REGISTRY_LOCATOR')
    expect(result.text).toContain('Usage: /loopx')
    expect(current.followups).toEqual([])
    expect(current.sends).toEqual([])
    expect(service.statusCalls).toBe(1)
    expect(service.starts).toEqual([])
    expect(service.attaches).toEqual([])
  })

  it('queues one plugin-owned semantic follow-up for an unbound natural-language request', async () => {
    const service = new FakeService(null)
    const current = stubAgent('semantic-session')
    const request = '梳理数据模型并画一张 ER 图'

    const result = await runCommand(service, current.agent, request)
    expect(result).toMatchObject({ kind: 'success' })
    expect(semanticFollowupText(current)).toContain(request)
    expectNoCommandServiceCalls(service)
  })

  it('uses the identical semantic queue path for a bound natural-language request', async () => {
    const request = 'summarize the current work and add the next safe Todo'
    const unboundService = new FakeService(null)
    const unbound = stubAgent('unbound-session')
    const existingBinding = binding('active_paused', { reason: 'user_pause' })
    const boundService = new FakeService(existingBinding)
    const bound = stubAgent('bound-session')

    expect(await runCommand(unboundService, unbound.agent, request)).toMatchObject({ kind: 'success' })
    expect(await runCommand(boundService, bound.agent, request)).toMatchObject({ kind: 'success' })
    expect(semanticFollowupText(bound)).toBe(semanticFollowupText(unbound))
    expectNoCommandServiceCalls(unboundService)
    expectNoCommandServiceCalls(boundService)
    expect(boundService.binding).toBe(existingBinding)
  })

  it.each([
    'start ship the adapter',
    'attach goal-123',
    'status',
    'pause',
    'resume',
    'detach',
    'version with details',
  ])('routes former command-shaped input %j through the semantic follow-up', async (request) => {
    const service = new FakeService()
    const current = stubAgent()

    expect(await runCommand(service, current.agent, request)).toMatchObject({ kind: 'success' })
    expect(semanticFollowupText(current)).toContain(request)
    expectNoCommandServiceCalls(service)
  })

  it('preserves original Unicode and internal whitespace as quoted request data', async () => {
    const service = new FakeService(null)
    const current = stubAgent()
    const request = '继续目标「甲」：保留\u3000全角空格、\t制表符和  双空格 🧭'

    expect(await runCommand(service, current.agent, request)).toMatchObject({ kind: 'success' })
    const text = semanticFollowupText(current)
    const quotedRequest = JSON.stringify(request)
    expect(text).toContain(quotedRequest)
    expect(text.slice(0, text.indexOf(quotedRequest))).toMatch(/quoted|user[\s_-]*(?:controlled[\s_-]*)?request/i)
    expectNoCommandServiceCalls(service)
  })

  it('references the registered tool family without copying its eleven-name catalog', async () => {
    const service = new FakeService(null)
    const current = stubAgent()

    await runCommand(service, current.agent, 'advance the current request safely')
    const text = semanticFollowupText(current)
    const policy = text.toLowerCase()
    expect(policy).toMatch(/registered\s+`?loopx_\*`?\s+tools/)
    expect(policy).toMatch(/raw loopx cli/)
    expect(policy).toMatch(/edit\w*\s+(?:the\s+)?registr/)
    expect(policy).toContain('unbound')
    expect(policy).toMatch(/explicit(?:ly)?[\s\S]{0,100}goal id/)
    expect(policy).toMatch(/attach[\s\S]{0,180}(?:otherwise|else)[\s\S]{0,80}start/)
    expect(policy).toMatch(/(?:already\s+)?bound[\s\S]{0,160}keep[\s\S]{0,80}current goal/)
    expect(policy).toMatch(/switch|detach/)
    expect(policy).toMatch(/(?:do not|never)[\s\S]{0,40}guess[\s\S]{0,80}goal id/)
    expect(policy).toMatch(/fuzzy/)
    expect(policy).toMatch(/compos/)
    expect(policy).toMatch(/clarif[\s\S]{0,160}without mutating/)

    const registeredNames = [...registerTools(service).keys()]
    expect(registeredNames).toHaveLength(11)
    expect(registeredNames.filter(name => text.includes(name))).toEqual([])
    expectNoCommandServiceCalls(service)
  })

  it('returns a bounded error when follow-up delivery throws synchronously', async () => {
    const service = new FakeService(null)
    const current = stubAgent()
    Object.defineProperty(current.agent, 'followup', {
      value() { throw new Error('SENSITIVE_SYNCHRONOUS_DELIVERY_DETAIL') },
    })

    const result = await runCommand(service, current.agent, 'ship the semantic entry')
    expect(result.kind).toBe('error')
    const errorText = result.text ?? ''
    expect(errorText).toMatch(/^LOOPX_SEMANTIC_DELIVERY_FAILED:/)
    expect(errorText).not.toContain('SENSITIVE_SYNCHRONOUS_DELIVERY_DETAIL')
    expect(errorText.length).toBeLessThan(300)
    expect(current.followups).toEqual([])
    expect(current.sends).toEqual([])
    expectNoCommandServiceCalls(service)
  })

  it('rejects a mismatched Agent and Session lifecycle before queueing', async () => {
    const service = new FakeService()
    const current = stubAgent('session-a')
    Object.defineProperty(current.agent, 'id', { value: 'session-b' })

    const result = await runCommand(service, current.agent, 'continue safely')
    expect(result).toMatchObject({ kind: 'error' })
    expect(result.text).toContain('LOOPX_SESSION_LIFECYCLE_MISMATCH')
    expect(current.followups).toEqual([])
    expect(current.sends).toEqual([])
    expectNoCommandServiceCalls(service)
  })
})

describe('bounded LoopX model tools', () => {
  it('registers exactly eleven typed tools including planning and Host lifecycle controls', () => {
    const tools = registerTools(new FakeService())
    expect([...tools.keys()]).toEqual([
      'loopx_goal_start',
      'loopx_goal_attach',
      'loopx_goal_activate',
      'loopx_status',
      'loopx_goal_detach',
      'loopx_driver_pause',
      'loopx_driver_resume',
      'loopx_todo_add',
      'loopx_todo_claim',
      'loopx_todo_update',
      'loopx_todo_complete',
    ])
  })

  it('returns the fixed unbound status failure without calling the status service', async () => {
    const service = new FakeService(null)
    const tools = registerTools(service)
    const result = await callTool(tools, 'loopx_status', {}, stubAgent().agent)
    expect(result).toMatchObject({
      schemaVersion: 'dsh_loopx_tool_result_v0',
      ok: false,
      error: { code: 'LOOPX_SESSION_NOT_BOUND' },
    })
    expect(service.statusCalls).toBe(0)
  })

  it('derives exact current Session lifecycle identity for every mutation', async () => {
    const service = new FakeService()
    const tools = registerTools(service)
    const current = stubAgent('session-exact', 777, 'SENSITIVE_EXACT_CWD')
    const result = await callTool(tools, 'loopx_todo_claim', {
      todoId: 'todo-a',
      role: 'agent',
    }, current.agent)
    expect(result).toMatchObject({
      ok: true,
      value: {
        todoId: 'todo-a',
        status: 'claimed',
        loopxAuthority: {
          schema_version: 'loopx_todo_command_v0',
          ok: true,
          todo_id: 'todo-a',
        },
      },
    })
    expect(service.claims).toEqual([{ todoId: 'todo-a', role: 'agent' }])
    expect(service.sessions.at(-1)).toEqual({
      id: 'session-exact',
      identity: { createdAt: 777, cwd: 'SENSITIVE_EXACT_CWD' },
    })

    const mismatched = stubAgent('session-a')
    Object.defineProperty(mismatched.agent, 'id', { value: 'session-b' })
    const denied = await callTool(tools, 'loopx_todo_claim', { todoId: 'todo-b' }, mismatched.agent)
    expect(errorCode(denied)).toBe('LOOPX_SESSION_LIFECYCLE_MISMATCH')

    const missing = stubAgent('session-missing')
    Object.defineProperty(missing.agent, 'id', { value: undefined })
    const missingDenied = await callTool(
      tools,
      'loopx_todo_claim',
      { todoId: 'todo-c' },
      missing.agent,
    )
    expect(errorCode(missingDenied)).toBe('LOOPX_SESSION_LIFECYCLE_MISMATCH')
  })

  it('completes the two-phase start only for the exact pending Goal and agent', async () => {
    const service = new FakeService(binding('planning'))
    const tools = registerTools(service)
    const current = stubAgent()

    const denied = await callTool(tools, 'loopx_goal_activate', {
      goalId: 'goal-other',
      agentId: 'agent-a',
    }, current.agent)
    expect(errorCode(denied)).toBe('LOOPX_IDENTITY_CONFLICT')
    expect(service.binding?.phase).toBe('planning')

    const activated = await callTool(tools, 'loopx_goal_activate', {
      goalId: 'goal-a',
      agentId: 'agent-a',
    }, current.agent)
    expect(activated).toMatchObject({
      schemaVersion: 'dsh_loopx_tool_result_v0',
      ok: true,
      value: { goalId: 'goal-a', agentId: 'agent-a', phase: 'active_armed' },
    })
    expect(JSON.stringify(activated)).not.toContain('SENSITIVE_')
  })

  it('rejects alternate identity, private locator, task-body, and arbitrary command fields and pauses an armed driver', async () => {
    const cases: readonly [string, Record<string, unknown>][] = [
      ['loopx_status', { sessionId: 'another-session' }],
      ['loopx_status', { goalId: 'another-goal' }],
      ['loopx_todo_claim', { todoId: 'todo-a', agentId: 'another-agent' }],
      ['loopx_todo_update', { todoId: 'todo-a', argv: ['status'] }],
      ['loopx_todo_complete', { todoId: 'todo-a', registryPath: 'SENSITIVE_REGISTRY_LOCATOR' }],
      ['loopx_goal_activate', { goalId: 'goal-a', taskBody: 'forged' }],
    ]
    for (const [name, args] of cases) {
      const service = new FakeService()
      const result = await callTool(registerTools(service), name, args, stubAgent().agent)
      expect(errorCode(result), name).toBe('LOOPX_INVALID_REQUEST')
      expect(service.binding?.phase, name).toBe('active_paused')
      expect(service.pauses, name).toContain('manual_resume_required')
      expect(service.pauseFences.at(-1), name).toMatchObject({ generation: 3 })
    }
  })

  it('maps the bounded Todo fields and returns stable success envelopes', async () => {
    const service = new FakeService(binding('planning'))
    const tools = registerTools(service)
    const current = stubAgent().agent
    const added = await callTool(tools, 'loopx_todo_add', {
      text: 'inspect the public schema',
      priority: 'P1',
      role: 'agent',
      actionKind: 'advance',
      targetKey: 'schema-review',
    }, current)
    expect(added).toMatchObject({
      ok: true,
      value: {
        todoId: 'todo-added',
        status: 'open',
        priority: 'P1',
        role: 'agent',
      },
    })
    expect(service.additions).toEqual([{
      text: 'inspect the public schema',
      priority: 'P1',
      role: 'agent',
      actionKind: 'advance',
      targetKey: 'schema-review',
    }])
    expect(JSON.stringify(added)).not.toContain('loopx_todo_command_v0')

    const update = await callTool(tools, 'loopx_todo_update', {
      todoId: 'todo-a',
      status: 'blocked',
      reason: 'waiting for an explicit user gate',
      taskClass: 'user_gate',
      clearClaim: true,
    }, current)
    expect(update).toMatchObject({
      schemaVersion: 'dsh_loopx_tool_result_v0',
      ok: true,
      value: {
        todoId: 'todo-a',
        status: 'blocked',
        loopxAuthority: {
          schema_version: 'loopx_todo_command_v0',
          ok: true,
          todo_id: 'todo-a',
        },
      },
    })
    expect(service.updates).toEqual([{
      todoId: 'todo-a',
      status: 'blocked',
      reason: 'waiting for an explicit user gate',
      taskClass: 'user_gate',
      clearClaim: true,
    }])

    const complete = await callTool(tools, 'loopx_todo_complete', {
      todoId: 'todo-a',
      evidence: 'public-safe evidence pointer',
      noFollowUp: true,
      turnInstanceId: 'turn-a',
      taskLeaseIdempotencyKey: 'lease-key',
      taskLeaseExpectedVersion: 2,
    }, current)
    expect(complete).toMatchObject({
      ok: true,
      value: {
        todoId: 'todo-a',
        status: 'done',
        loopxAuthority: {
          schema_version: 'loopx_todo_command_v0',
          ok: true,
          todo_id: 'todo-a',
        },
      },
    })
    expect(service.completions[0]).toMatchObject({
      todoId: 'todo-a',
      noFollowUp: true,
      turnInstanceId: 'turn-a',
      taskLeaseExpectedVersion: 2,
    })
  })

  it('exposes typed pause, resume, and detach controls over only the current binding', async () => {
    const service = new FakeService()
    const tools = registerTools(service)
    const current = stubAgent().agent
    const paused = await callTool(tools, 'loopx_driver_pause', {}, current)
    expect(paused).toMatchObject({ ok: true, value: { phase: 'active_paused' } })
    const resumed = await callTool(tools, 'loopx_driver_resume', {}, current)
    expect(resumed).toMatchObject({ ok: true, value: { phase: 'active_armed' } })
    const detached = await callTool(tools, 'loopx_goal_detach', {}, current)
    expect(detached).toMatchObject({ ok: true, value: { detached: true } })
    expect(service.binding).toBeUndefined()
  })

  it('returns uncertain writes as typed failures and disarms through the service API', async () => {
    const service = new FakeService()
    service.todoFailure = failure('LOOPX_WRITE_UNCERTAIN', 'todo-update', true)
    const result = await callTool(registerTools(service), 'loopx_todo_update', {
      todoId: 'todo-a',
      status: 'done',
    }, stubAgent().agent)
    expect(result).toMatchObject({
      schemaVersion: 'dsh_loopx_tool_result_v0',
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN', outcomeUncertain: true },
    })
    expect(service.uncertainCalls).toBe(1)
    expect(service.uncertainFences).toMatchObject([{ generation: 3 }])
    expect(service.binding?.phase).toBe('uncertain')
  })

  it('pauses an armed driver on a typed schema/readback boundary failure', async () => {
    const service = new FakeService()
    service.statusResult = failure('LOOPX_SCHEMA_UNSUPPORTED', 'status')
    const result = await callTool(
      registerTools(service),
      'loopx_status',
      {},
      stubAgent().agent,
    )
    expect(errorCode(result)).toBe('LOOPX_SCHEMA_UNSUPPORTED')
    expect(service.pauses).toEqual(['manual_resume_required'])
    expect(service.pauseFences).toMatchObject([{ generation: 3 }])
    expect(service.binding?.phase).toBe('active_paused')
  })

  it('status labels Host sidecar and LoopX authority without leaking locators', async () => {
    const service = new FakeService()
    const result = await callTool(
      registerTools(service),
      'loopx_status',
      {},
      stubAgent().agent,
    )
    expect(result).toMatchObject({
      ok: true,
      value: {
        dshHostSidecar: { authority: 'host_binding_and_driver_only' },
        loopxAuthority: { schema_version: 'loopx_status_v0' },
      },
    })
    expect(JSON.stringify(result)).not.toContain('SENSITIVE_')
  })
})
