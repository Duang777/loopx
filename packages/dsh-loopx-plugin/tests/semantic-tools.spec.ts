import { describe, expect, it } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { validateJsonSchemaValue } from '@deepseek-ai/dsh-tools'
import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'
import { CoordinatorRegistry, installCoordinator } from '../src/coordinator.ts'
import { apply as applyTools } from '../src/tools.ts'
import type {
  LoopXAttachRequest,
  LoopXAttachValue,
  LoopXBoundHostThreadBindingV1,
  LoopXFailure,
  LoopXResult,
  LoopXSessionRef,
  LoopXStartOptions,
  LoopXStartValue,
  LoopXStatusValue,
} from '../src/types.ts'

const signal = new AbortController().signal

function ok<T>(value: T, application: 'yes' | 'no' = 'no'): LoopXResult<T> {
  return { ok: true, value, application }
}

function rejected(operation: string): LoopXResult<never> {
  const error: LoopXFailure = {
    code: 'LOOPX_AUTHORITY_UNHEALTHY',
    message: `safe ${operation} failure`,
    operation,
    retryable: false,
    outcomeUncertain: false,
  }
  return { ok: false, error, application: 'no' }
}

function binding(): LoopXBoundHostThreadBindingV1 {
  return {
    schemaVersion: 'loopx_host_thread_binding_v1',
    hostSurface: 'dsh',
    threadId: 'session-a',
    revision: 1,
    state: 'bound',
    target: { goalId: 'goal-a', agentId: 'agent-a' },
  }
}

function planning(): LoopXStartValue {
  return {
    kind: 'planning',
    binding: binding(),
    planning: {
      schemaVersion: 'dsh_loopx_planning_checkpoint_v1',
      goalId: 'goal-a',
      agentId: 'agent-a',
      goalText: 'bounded objective',
      planner: {
        defaultProfile: 'clear_bounded_problem', profileSelection: 'select',
        openEndedProductDirection: { suggestedItemsMin: 2, suggestedItemsMax: 5, intent: 'rank' },
        clearBoundedProblem: {
          itemCountPolicy: 'planner_sized',
          mayReuseCurrentTodoWhenItAlreadyRepresentsThePlan: true,
          intent: 'plan',
        },
        allowedPriorities: ['P0', 'P1', 'P2'], defaultRole: 'agent',
        defaultTaskClass: 'advancement_task', requiredFields: ['text'],
        publicSafeOnly: true, budgetPolicy: 'minimum',
      },
      writeback: {
        todoTool: 'loopx_todo_add', minimumTodos: 1, maximumTodos: 5,
        ordering: 'priority_then_tool_call_order', activationTool: 'loopx_goal_activate',
        activationArguments: { goalId: 'goal-a', agentId: 'agent-a' },
      },
      stopConditions: ['user gate'],
      forbidden: ['shell_or_bash', 'raw_loopx_cli', 'registry_edit', 'ctx.goals'],
    },
    modelCheckpoint: '<loopx_planning>plan</loopx_planning>',
  }
}

function agent(id = 'session-a'): Agent {
  return {
    id,
    session: { id, header: { version: 0, id, createdAt: 77, cwd: '/SENSITIVE/CWD' } },
  } as unknown as Agent
}

class EntryService {
  readonly coordinator = new CoordinatorRegistry()
  readonly starts: Array<{
    readonly session: LoopXSessionRef
    readonly objective: string
    readonly options?: LoopXStartOptions
  }> = []
  readonly attaches: Array<{ readonly session: LoopXSessionRef; readonly request: LoopXAttachRequest }> = []
  startResult: LoopXResult<LoopXStartValue> = ok(planning(), 'yes')
  attachResult: LoopXResult<LoopXAttachValue> = ok({ kind: 'attached', binding: binding() }, 'yes')
  statusResult: LoopXResult<LoopXStatusValue> = ok({
    host: {
      binarySource: 'path', binding: binding(), activation: 'disarmed',
      automaticFollowupSuppressed: false,
    },
  })

  constructor() { installCoordinator(this, this.coordinator) }

  start(
    session: LoopXSessionRef,
    objective: string,
    _signal?: AbortSignal,
    options?: LoopXStartOptions,
  ) {
    this.starts.push({ session, objective, ...(options === undefined ? {} : { options }) })
    return Promise.resolve(this.startResult)
  }

  attach(session: LoopXSessionRef, request: LoopXAttachRequest) {
    this.attaches.push({ session, request })
    if (this.attachResult.ok && this.attachResult.value.kind === 'attached') {
      const home = { key: 'home-a', cwd: '/SENSITIVE/CWD', runtimeRoot: '/SENSITIVE/RUNTIME' }
      this.coordinator.observeBinding(session, home, this.attachResult.value.binding)
      this.coordinator.arm(session, home, this.attachResult.value.binding)
    }
    return Promise.resolve(this.attachResult)
  }

  status() { return Promise.resolve(this.statusResult) }
}

function tools(service: EntryService): ReadonlyMap<string, ToolDefinition> {
  const found = new Map<string, ToolDefinition>()
  applyTools({
    loopx: service,
    tools: { register(definition: ToolDefinition) { found.set(definition.name, definition) } },
  } as unknown as Context)
  return found
}

async function call(
  service: EntryService,
  name: string,
  args: unknown,
  current = agent(),
): Promise<Record<string, unknown>> {
  const definition = tools(service).get(name)
  if (definition === undefined) throw new Error(`missing ${name}`)
  const value = await definition.execute(args, {
    name,
    arguments: args,
    agent: current,
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

describe('semantic entry tools', () => {
  it('publishes a closed fresh-start surface without obsolete identity selectors', () => {
    const definitions = tools(new EntryService())
    const start = definitions.get('loopx_goal_start')
    expect(start?.parameters).toMatchObject({
      type: 'object', required: ['goalText'], additionalProperties: false,
    })
    expect(Object.keys(start?.parameters.properties ?? {})).toEqual([
      'goalText', 'switchConfirmation',
    ])
    expect(definitions.get('loopx_status')?.parameters).toMatchObject({
      type: 'object', additionalProperties: false,
    })
  })

  it('passes the exact live Session object and leaves fresh start disarmed', async () => {
    const service = new EntryService()
    const current = agent()
    const result = await call(service, 'loopx_goal_start', {
      goalText: 'implement the bounded change',
      switchConfirmation: 'confirmed-revision-token',
    }, current)
    expect(result).toMatchObject({
      kind: 'operation_result', execution: 'succeeded', application: 'yes',
      value: { kind: 'planning', binding: { hostSurface: 'dsh', revision: 1 } },
    })
    expect(service.starts[0]).toMatchObject({
      objective: 'implement the bounded change',
      options: { switchConfirmation: 'confirmed-revision-token' },
    })
    expect(service.starts[0]?.session.session).toBe(current.session)
    expect(service.coordinator.snapshot(current.session)?.activation).toBe('disarmed')
    expect(JSON.stringify(result)).not.toContain('/SENSITIVE/CWD')
  })

  it('forwards exact attach and fresh-peer intent only', async () => {
    const service = new EntryService()
    await call(service, 'loopx_goal_attach', {
      goalId: 'goal-a', agentId: 'agent-a', switchConfirmation: 'token-a',
    })
    await call(service, 'loopx_goal_attach', { goalId: 'goal-a', newPeer: true })
    expect(service.attaches.map(entry => entry.request)).toEqual([
      { goalId: 'goal-a', agentId: 'agent-a', switchConfirmation: 'token-a' },
      { goalId: 'goal-a', newPeer: true },
    ])
  })

  it('projects selection and confirmed-switch readback as no application', async () => {
    const service = new EntryService()
    service.attachResult = ok({
      kind: 'selection_required',
      goalId: 'goal-a',
      selection: {
        kind: 'agent', defaultAction: 'select_agent',
        choices: [{ agentId: 'agent-a' }],
      },
    }, 'no')
    expect(await call(service, 'loopx_goal_attach', { goalId: 'goal-a' })).toMatchObject({
      application: 'no', value: { kind: 'selection_required' },
    })

    service.attachResult = ok({
      kind: 'switch_required', confirmationToken: 'opaque', requiresUserConfirmation: true,
      expiresAt: 9000, expectedRevision: 7,
      current: { goalId: 'goal-old', agentId: 'agent-old' },
      requested: { operation: 'attach', goalId: 'goal-new', agentId: 'agent-new' },
    }, 'no')
    expect(await call(service, 'loopx_goal_attach', {
      goalId: 'goal-new', agentId: 'agent-new',
    })).toMatchObject({
      application: 'no',
      value: { kind: 'switch_required', expectedRevision: 7 },
    })
  })

  it('rejects alternate Session/locator/shell arguments before Service entry', async () => {
    const service = new EntryService()
    for (const args of [
      { goalText: 'safe', goalId: 'old-goal' },
      { goalText: 'safe', sessionId: 'other' },
      { goalText: 'safe', runtimeRoot: '/SENSITIVE/RUNTIME' },
      { goalText: 'safe', shell: 'loopx start-goal' },
    ]) {
      expect(await call(service, 'loopx_goal_start', args)).toMatchObject({
        execution: 'rejected', application: 'no',
        error: { code: 'LOOPX_INVALID_REQUEST' },
      })
    }
    expect(service.starts).toEqual([])
  })

  it('rejects mismatched Agent/Session identity before Service entry', async () => {
    const service = new EntryService()
    const mismatched = agent('session-a')
    Object.defineProperty(mismatched, 'id', { value: 'session-b' })
    expect(await call(service, 'loopx_goal_start', { goalText: 'safe' }, mismatched)).toMatchObject({
      error: { code: 'LOOPX_SESSION_LIFECYCLE_MISMATCH' }, application: 'no',
    })
    expect(service.starts).toEqual([])
  })

  it('lets successful explicit attach arm and clear eighth-failure suppression', async () => {
    const service = new EntryService()
    const current = agent()
    service.startResult = rejected('goal-start')
    for (let count = 1; count <= 8; count += 1) {
      await call(service, 'loopx_goal_start', { goalText: 'safe' }, current)
      expect(service.coordinator.snapshot(current.session)?.failureCount).toBe(count)
    }
    expect(service.coordinator.snapshot(current.session)?.automaticFollowupSuppressed).toBe(true)
    await call(service, 'loopx_goal_attach', { goalId: 'goal-a', agentId: 'agent-a' }, current)
    expect(service.coordinator.snapshot(current.session)).toMatchObject({
      activation: 'armed', failureCount: 0, automaticFollowupSuppressed: false,
    })
  })
})
