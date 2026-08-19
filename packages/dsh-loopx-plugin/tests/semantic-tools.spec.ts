import { describe, expect, it } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { validateJsonSchemaValue } from '@deepseek-ai/dsh-tools'
import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'
import { apply as applyTools } from '../src/tools.ts'
import type {
  LoopXAttachRequest,
  LoopXAttachValue,
  LoopXBindingRow,
  LoopXFailure,
  LoopXPlanningCheckpoint,
  LoopXResult,
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStartOptions,
  LoopXStartValue,
} from '../src/types.ts'

const signal = new AbortController().signal

function success<T>(value: T): LoopXResult<T> {
  return { ok: true, value }
}

function failure(
  code: LoopXFailure['code'],
  operation: string,
): LoopXResult<never> {
  return {
    ok: false,
    error: {
      code,
      message: `safe ${operation} failure`,
      operation,
      retryable: false,
      outcomeUncertain: false,
    },
  }
}

function binding(
  phase: LoopXBindingRow['phase'],
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

function planning(): LoopXPlanningCheckpoint {
  return {
    schemaVersion: 'dsh_loopx_planning_checkpoint_v0',
    goalId: 'goal-a',
    agentId: 'agent-a',
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
      activationArguments: { goalId: 'goal-a', agentId: 'agent-a' },
    },
    stopConditions: ['stop at a user gate'],
    forbidden: ['shell_or_bash', 'raw_loopx_cli', 'registry_edit', 'ctx.goals'],
  }
}

interface StubAgent {
  readonly agent: Agent
  readonly followups: unknown[]
}

function stubAgent(
  id = 'session-current',
  createdAt = 42,
  cwd = 'SENSITIVE_SESSION_CWD',
): StubAgent {
  const followups: unknown[] = []
  const session = { id, header: { version: 0, id, createdAt, cwd } }
  return {
    agent: {
      id,
      session,
      followup(message: unknown) { followups.push(message) },
    } as unknown as Agent,
    followups,
  }
}

interface StartCall {
  readonly session: LoopXSessionRef
  readonly goalText: string
  readonly options?: LoopXStartOptions | undefined
}

interface AttachCall {
  readonly session: LoopXSessionRef
  readonly request: LoopXAttachRequest
}

class EntryService {
  startResult: LoopXResult<LoopXStartValue> = success({
    kind: 'planning',
    binding: binding('planning'),
    planning: planning(),
    modelCheckpoint: '<loopx_planning>write the plan and Todos</loopx_planning>',
  })

  attachResult: LoopXResult<LoopXAttachValue> = success({
    kind: 'attached',
    binding: binding('active_armed'),
  })

  readonly starts: StartCall[] = []
  readonly attaches: AttachCall[] = []

  start(
    session: LoopXSessionRef,
    goalText: string,
    _signal?: AbortSignal,
    options?: LoopXStartOptions,
  ): Promise<LoopXResult<LoopXStartValue>> {
    this.starts.push({ session, goalText, ...(options === undefined ? {} : { options }) })
    return Promise.resolve(this.startResult)
  }

  attach(
    session: LoopXSessionRef,
    request: LoopXAttachRequest,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    this.attaches.push({ session, request })
    return Promise.resolve(this.attachResult)
  }
}

function registerTools(service: EntryService): ReadonlyMap<string, ToolDefinition> {
  const definitions = new Map<string, ToolDefinition>()
  const ctx = {
    loopx: service as unknown as LoopXServiceApi,
    tools: { register(value: ToolDefinition) { definitions.set(value.name, value) } },
  } as unknown as Context
  applyTools(ctx)
  return definitions
}

async function callTool(
  definitions: ReadonlyMap<string, ToolDefinition>,
  name: string,
  args: unknown,
  agent: Agent,
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

describe('semantic LoopX entry tools', () => {
  it('publishes closed schemas for all eleven tools and only typed entry inputs', () => {
    const tools = registerTools(new EntryService())
    expect(tools.size).toBe(11)
    for (const definition of tools.values()) {
      expect(definition.parameters).toMatchObject({
        type: 'object',
        additionalProperties: false,
      })
    }
    const start = tools.get('loopx_goal_start')
    const attach = tools.get('loopx_goal_attach')
    expect(start?.parameters).toMatchObject({
      type: 'object',
      required: ['goalText'],
      additionalProperties: false,
    })
    expect(attach?.parameters).toMatchObject({
      type: 'object',
      required: ['goalId'],
      additionalProperties: false,
    })
    expect(Object.keys(start?.parameters.properties ?? {})).toEqual([
      'goalText',
      'goalId',
      'agentId',
      'newPeer',
      'newIndependent',
      'switchConfirmation',
    ])
    expect(Object.keys(attach?.parameters.properties ?? {})).toEqual([
      'goalId',
      'agentId',
      'newPeer',
      'switchConfirmation',
    ])
    expect(start?.description).toContain('current DSH Session')
    expect(start?.description).toContain('never use Bash')
    expect(attach?.description).toContain('existing LoopX Goal')
    expect(attach?.description).toContain('never use Bash')
  })

  it('returns the planning checkpoint directly without queuing a command follow-up', async () => {
    const service = new EntryService()
    const current = stubAgent('session-exact', 777, 'SENSITIVE_EXACT_CWD')
    const result = await callTool(registerTools(service), 'loopx_goal_start', {
      goalText: 'Implement the bounded semantic entry',
      goalId: 'goal-a',
      agentId: 'agent-a',
      switchConfirmation: 'opaque-confirmation',
    }, current.agent)

    expect(result).toMatchObject({
      schemaVersion: 'dsh_loopx_tool_result_v0',
      ok: true,
      value: {
        kind: 'planning',
        binding: { goalId: 'goal-a', agentId: 'agent-a', phase: 'planning' },
        modelCheckpoint: '<loopx_planning>write the plan and Todos</loopx_planning>',
      },
    })
    expect(service.starts).toEqual([{
      session: {
        id: 'session-exact',
        identity: { createdAt: 777, cwd: 'SENSITIVE_EXACT_CWD' },
      },
      goalText: 'Implement the bounded semantic entry',
      options: {
        goalId: 'goal-a',
        agentId: 'agent-a',
        switchConfirmation: 'opaque-confirmation',
      },
    }])
    expect(current.followups).toEqual([])
    expect(JSON.stringify(result)).not.toContain('SENSITIVE_')
  })

  it('attaches only the current Session and returns a locator-free binding', async () => {
    const service = new EntryService()
    service.attachResult = success({
      kind: 'attached',
      binding: binding('active_armed', { goalId: 'goal-existing', agentId: 'fresh-peer' }),
    })
    const current = stubAgent('session-attach', 888, 'SENSITIVE_ATTACH_CWD')
    const result = await callTool(registerTools(service), 'loopx_goal_attach', {
      goalId: 'goal-existing',
      newPeer: true,
      switchConfirmation: 'opaque-attach-confirmation',
    }, current.agent)

    expect(result).toMatchObject({
      ok: true,
      value: {
        kind: 'attached',
        binding: { goalId: 'goal-existing', agentId: 'fresh-peer', phase: 'active_armed' },
      },
    })
    expect(service.attaches).toEqual([{
      session: {
        id: 'session-attach',
        identity: { createdAt: 888, cwd: 'SENSITIVE_ATTACH_CWD' },
      },
      request: {
        goalId: 'goal-existing',
        newPeer: true,
        switchConfirmation: 'opaque-attach-confirmation',
      },
    }])
    expect(JSON.stringify(result)).not.toContain('SENSITIVE_')
  })

  it('forwards typed independent-Goal and fresh-peer start intent without command inputs', async () => {
    const service = new EntryService()
    const tools = registerTools(service)
    const current = stubAgent().agent
    await callTool(tools, 'loopx_goal_start', {
      goalText: 'Start one independent Goal',
      newIndependent: true,
    }, current)
    await callTool(tools, 'loopx_goal_start', {
      goalText: 'Resume with a fresh peer',
      newPeer: true,
    }, current)
    expect(service.starts.map(call => call.options)).toEqual([
      { newIndependent: true },
      { newPeer: true },
    ])
  })

  it('projects exact selection and no-mutation switch results for model re-entry', async () => {
    const service = new EntryService()
    const tools = registerTools(service)
    const current = stubAgent().agent
    service.startResult = success({
      kind: 'selection_required',
      goalId: 'goal-a',
      selection: {
        kind: 'agent',
        defaultAction: 'select_agent_identity',
        reason: 'Choose one exact registered identity.',
        choices: [{ agentId: 'agent-a', label: 'Primary peer' }],
        freshAgentSuggestedId: 'agent-fresh',
      },
    })
    const selected = await callTool(tools, 'loopx_goal_start', {
      goalText: 'Continue the selected lane',
    }, current)
    expect(selected).toMatchObject({
      ok: true,
      value: {
        kind: 'selection_required',
        goalId: 'goal-a',
        selection: {
          choices: [{ agentId: 'agent-a', label: 'Primary peer' }],
          freshAgentSuggestedId: 'agent-fresh',
        },
      },
    })

    service.attachResult = success({
      kind: 'switch_required',
      confirmationToken: 'opaque-switch-token',
      requiresUserConfirmation: true,
      expiresAt: 9000,
      current: { goalId: 'goal-old', agentId: 'agent-old' },
      requested: { operation: 'attach', goalId: 'goal-new', agentId: 'agent-new' },
    })
    const switched = await callTool(tools, 'loopx_goal_attach', {
      goalId: 'goal-new',
      agentId: 'agent-new',
    }, current)
    expect(switched).toMatchObject({
      ok: true,
      value: {
        kind: 'switch_required',
        confirmationToken: 'opaque-switch-token',
        requiresUserConfirmation: true,
        current: { goalId: 'goal-old', agentId: 'agent-old' },
        requested: { operation: 'attach', goalId: 'goal-new', agentId: 'agent-new' },
      },
    })
  })

  it('preserves typed service failures and does not invent a successful binding', async () => {
    const service = new EntryService()
    service.startResult = failure('LOOPX_SCHEMA_UNSUPPORTED', 'start')
    const result = await callTool(registerTools(service), 'loopx_goal_start', {
      goalText: 'Start only through the supported contract',
    }, stubAgent().agent)
    expect(result).toMatchObject({
      schemaVersion: 'dsh_loopx_tool_result_v0',
      ok: false,
      error: {
        code: 'LOOPX_SCHEMA_UNSUPPORTED',
        operation: 'start',
        retryable: false,
        outcomeUncertain: false,
      },
    })
  })

  it('rejects alternate Sessions, locators, argv, and shell commands before service entry', async () => {
    const service = new EntryService()
    const tools = registerTools(service)
    const current = stubAgent().agent
    const cases: readonly [string, Record<string, unknown>][] = [
      ['loopx_goal_start', { goalText: 'start safely', sessionId: 'session-other' }],
      ['loopx_goal_start', { goalText: 'start safely', projectLocator: 'PRIVATE_LOCATOR' }],
      ['loopx_goal_start', { goalText: 'start safely', argv: ['bootstrap'] }],
      ['loopx_goal_start', { goalText: 'start safely', command: 'loopx bootstrap' }],
      ['loopx_goal_start', { goalText: 'start safely', shell: 'loopx bootstrap' }],
      ['loopx_goal_attach', { goalId: 'goal-a', session: { id: 'session-other' } }],
      ['loopx_goal_attach', { goalId: 'goal-a', registryPath: 'PRIVATE_LOCATOR' }],
      ['loopx_goal_attach', { goalId: 'goal-a', locator: 'PRIVATE_LOCATOR' }],
      ['loopx_goal_attach', { goalId: 'goal-a', argv: ['start-goal'] }],
      ['loopx_goal_attach', { goalId: 'goal-a', shellCommand: 'loopx start-goal' }],
    ]

    for (const [name, args] of cases) {
      const definition = tools.get(name)
      if (definition === undefined) throw new Error(`missing tool ${name}`)
      expect(validateJsonSchemaValue(definition.parameters, args, ''), name).not.toEqual([])
      const result = await callTool(tools, name, args, current)
      expect(errorCode(result), name).toBe('LOOPX_INVALID_REQUEST')
    }
    expect(service.starts).toEqual([])
    expect(service.attaches).toEqual([])
  })

  it('rejects a mismatched DSH Agent and Session lifecycle before service entry', async () => {
    const service = new EntryService()
    const mismatched = stubAgent('session-a')
    Object.defineProperty(mismatched.agent, 'id', { value: 'session-b' })
    const result = await callTool(registerTools(service), 'loopx_goal_start', {
      goalText: 'Must stay in this Session',
    }, mismatched.agent)
    expect(errorCode(result)).toBe('LOOPX_SESSION_LIFECYCLE_MISMATCH')
    expect(service.starts).toEqual([])
  })
})
