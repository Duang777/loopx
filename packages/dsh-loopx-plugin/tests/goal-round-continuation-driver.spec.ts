import type { Agent, PreStepDecision } from '@deepseek-ai/dsh-agent'
import type { SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
import { describe, expect, it } from 'vitest'
import { LoopXContinuationDriver } from '../src/driver.ts'
import type {
  LoopXBindingFence,
  LoopXBindingRow,
  LoopXContinuationServiceApi,
  LoopXResult,
  LoopXSessionRef,
} from '../src/types.ts'

function ok<T>(value: T): LoopXResult<T> {
  return { ok: true, value }
}

function unavailable(operation: string): LoopXResult<never> {
  return {
    ok: false,
    error: {
      code: 'LOOPX_DRIVER_NOT_ARMED',
      message: `safe ${operation} failure`,
      operation,
      retryable: false,
      outcomeUncertain: false,
    },
  }
}

function binding(phase: LoopXBindingRow['phase'], generation = 1): LoopXBindingRow {
  return Object.freeze({
    schemaVersion: 'loopx_dsh_binding_row_v0',
    session: Object.freeze({ createdAt: 42, cwd: '/workspace' }),
    hostSurface: 'deepseek-harness-native',
    goalId: 'goal-a',
    agentId: 'agent-a',
    projectLocator: '/workspace',
    phase,
    generation,
    unchangedPollCount: 0,
    bindingCreatedAt: 40,
    updatedAt: 42,
  })
}

function bindingFence(row: LoopXBindingRow): LoopXBindingFence {
  return Object.freeze({
    sessionId: 'session-a',
    session: row.session,
    goalId: row.goalId,
    agentId: row.agentId,
    generation: row.generation,
  })
}

function sameFence(left: LoopXBindingFence, right: LoopXBindingFence): boolean {
  return left.sessionId === right.sessionId
    && left.session.createdAt === right.session.createdAt
    && left.session.cwd === right.session.cwd
    && left.goalId === right.goalId
    && left.agentId === right.agentId
    && left.generation === right.generation
}

function human(id: string): UserMessage {
  return {
    id: id as UserMessage['id'],
    role: 'user',
    content: [{ type: 'text', text: id }],
    source: { kind: 'user' },
  }
}

function commandPluginMessage(id: string): UserMessage {
  return {
    id: id as UserMessage['id'],
    role: 'user',
    content: [{ type: 'text', text: id }],
    source: { kind: 'plugin', plugin: 'dsh-loopx-plugin' },
  }
}

function admitted(message: UserMessage): SessionEvent {
  return { type: 'user/message', seq: 0, time: 1, data: message } as SessionEvent
}

function command(type: 'command/run' | 'command/done'): SessionEvent {
  return {
    type,
    seq: 0,
    time: 1,
    data: type === 'command/run'
      ? { commandId: 'cmd-test', name: 'loopx' }
      : { commandId: 'cmd-test', kind: 'success' },
  } as SessionEvent
}

interface TestHarness {
  readonly agent: Agent
  readonly driver: LoopXContinuationDriver
  readonly followups: UserMessage[]
  readonly nextTurn: UserMessage[]
  readonly nextStep: UserMessage[]
  readonly removed: UserMessage['id'][]
  readonly cancels: unknown[]
  readonly calls: { planning: number; quota: number; task: number; spend: number }
  setBinding(row: LoopXBindingRow): void
  setPlanningBody(body: string | undefined): void
  setStatus(status: 'idle' | 'running'): void
  idle(): Promise<void>
  claim(message: UserMessage): void
}

function harness(initial: LoopXBindingRow, planningBody = 'planning checkpoint'): TestHarness {
  let row = initial
  let body: string | undefined = planningBody
  let status: 'idle' | 'running' = 'idle'
  const followups: UserMessage[] = []
  const nextTurn: UserMessage[] = []
  const nextStep: UserMessage[] = []
  const removed: UserMessage['id'][] = []
  const cancels: unknown[] = []
  const calls = { planning: 0, quota: 0, task: 0, spend: 0 }
  let driver: LoopXContinuationDriver
  let agent: Agent
  const service = {
    getBinding: () => ok(row),
    fence: () => ok(bindingFence(row)),
    fenceIsCurrent: (expected: LoopXBindingFence) => sameFence(expected, bindingFence(row)),
    planningContinuation: (_session: LoopXSessionRef, generation: number) => {
      calls.planning += 1
      return row.phase === 'planning' && row.generation === generation && body !== undefined
        ? ok({ kind: 'planning' as const, fence: bindingFence(row), body })
        : unavailable('planning-continuation')
    },
    quotaShouldRun: (_session: LoopXSessionRef, turnInstanceId: string) => {
      calls.quota += 1
      return Promise.resolve(ok({
        goalId: row.goalId,
        agentId: row.agentId,
        turnInstanceId,
        shouldRun: true,
        effectiveAction: 'run_now',
        schedulerHint: {
          action: 'run_now', cadenceClass: 'immediate', resetToken: 'reset',
          recommendedIntervalMinutes: 1, unchangedPollLimit: 1, afterLimit: 'quiet',
        },
        terminalNoFollowup: false,
        payload: { schema_version: 'loopx_quota_should_run_v0', ok: true },
      }))
    },
    updateScheduler: () => Promise.resolve(ok(row)),
    taskBody: () => {
      calls.task += 1
      return Promise.resolve(ok({ fence: bindingFence(row), body: 'delivery body' }))
    },
    pause: (
      _session: LoopXSessionRef,
      _reason: unknown,
      expected?: LoopXBindingFence,
    ) => {
      if (expected !== undefined && !sameFence(expected, bindingFence(row))) {
        return Promise.resolve(unavailable('pause'))
      }
      body = undefined
      row = binding(row.phase === 'active_armed' ? 'active_paused' : row.phase, row.generation + 1)
      return Promise.resolve(ok(row))
    },
    markUncertain: () => Promise.resolve(ok(row)),
    disposeSession: () => Promise.resolve(),
  } as unknown as LoopXContinuationServiceApi
  agent = {
    id: 'session-a',
    session: {
      id: 'session-a',
      header: { version: 0, id: 'session-a', createdAt: 42, cwd: '/workspace' },
    },
    get status() { return status },
    inbox: {
      get nextTurn() { return nextTurn },
      get nextStep() { return nextStep },
      get hasPending() { return nextTurn.length > 0 || nextStep.length > 0 },
      remove(id: UserMessage['id']) {
        const index = nextTurn.findIndex(message => message.id === id)
        if (index < 0) return false
        nextTurn.splice(index, 1)
        removed.push(id)
        return true
      },
      prepend(target: 'next-turn' | 'next-step', message: UserMessage) {
        (target === 'next-turn' ? nextTurn : nextStep).unshift(message)
      },
    },
    followup(message: UserMessage) {
      followups.push(message)
      nextTurn.push(message)
      driver.onInboxInserted(agent, message)
      status = 'running'
      driver.onAgentStatus(agent, 'running')
    },
    cancel(cause: unknown) { cancels.push(cause) },
    whenIdle: () => Promise.resolve(),
  } as unknown as Agent
  driver = new LoopXContinuationDriver({
    service,
    isLiveAgent: candidate => candidate === agent,
    makeTurnInstanceId: () => `turn-${calls.quota + 1}`,
  })
  driver.observeAgent(agent)
  return {
    agent,
    driver,
    followups,
    nextTurn,
    nextStep,
    removed,
    cancels,
    calls,
    setBinding(value) { row = value },
    setPlanningBody(value) { body = value },
    setStatus(value) { status = value },
    async idle() {
      status = 'idle'
      driver.onAgentStatus(agent, 'idle')
      await driver.whenSettled()
    },
    claim(message) {
      const index = nextTurn.findIndex(candidate => candidate.id === message.id)
      if (index >= 0) nextTurn.splice(index, 1)
      status = 'running'
      driver.onInboxClaimed(agent, message)
    },
  }
}

async function admit(
  test: TestHarness,
  automatic: UserMessage,
  messages: UserMessage[] = [automatic],
): Promise<PreStepDecision> {
  test.claim(automatic)
  return test.driver.onPreStep(
    test.agent,
    messages,
    new AbortController().signal,
    () => Promise.resolve({ kind: 'enter', messages }),
  )
}

describe('Goal-round continuation admission', () => {
  it('queues one planning-only recovery and consumes it only at model admission', async () => {
    const test = harness(binding('planning'))
    await test.idle()
    expect(test.followups[0]?.content).toEqual([{ type: 'text', text: 'planning checkpoint' }])
    expect(test.calls).toEqual({ planning: 1, quota: 0, task: 0, spend: 0 })

    const automatic = test.followups[0] as UserMessage
    expect((await admit(test, automatic)).kind).toBe('enter')
    test.driver.onSessionEvent(test.agent, admitted(automatic))
    await test.idle()
    expect(test.followups).toHaveLength(1)
    expect(test.calls).toEqual({ planning: 1, quota: 0, task: 0, spend: 0 })
    await test.driver.dispose()
  })

  it('skips planning recovery after activation and uses the delivery quota lane', async () => {
    const test = harness(binding('active_armed', 2))
    await test.idle()
    expect(test.calls).toEqual({ planning: 0, quota: 1, task: 1, spend: 0 })
    expect(test.followups[0]?.content).toEqual([{ type: 'text', text: 'delivery body' }])
    await test.driver.dispose()
  })

  it('lets human input remove a queued recovery without consuming the opportunity', async () => {
    const test = harness(binding('planning'))
    await test.idle()
    const first = test.followups[0] as UserMessage
    const message = human('human-first')
    test.nextTurn.push(message)
    test.driver.onInboxInserted(test.agent, message)
    expect(test.removed).toEqual([first.id])
    expect(test.cancels).toEqual([])

    test.claim(message)
    test.driver.onSessionEvent(test.agent, admitted(message))
    await test.idle()
    expect(test.followups).toHaveLength(2)
    expect(test.calls).toEqual({ planning: 2, quota: 0, task: 0, spend: 0 })
    await test.driver.dispose()
  })

  it('stays quiet when process-local planning content is absent or lifecycle authority is reset', async () => {
    const missing = harness(binding('planning'))
    missing.setPlanningBody(undefined)
    await missing.idle()
    expect(missing.followups).toEqual([])
    expect(missing.calls).toEqual({ planning: 1, quota: 0, task: 0, spend: 0 })
    await missing.driver.dispose()

    const restored = harness(binding('planning'))
    restored.driver.onSessionStart(restored.agent)
    await restored.idle()
    expect(restored.followups).toEqual([])
    expect(restored.calls).toEqual({ planning: 1, quota: 0, task: 0, spend: 0 })
    await restored.driver.dispose()
  })

  it('invalidates planning authority across a strong command boundary', async () => {
    const test = harness(binding('planning'))
    await test.idle()
    expect(test.followups).toHaveLength(1)

    test.driver.onSessionEvent(test.agent, command('command/run'))
    await test.driver.whenSettled()
    test.driver.onSessionEvent(test.agent, command('command/done'))
    await test.idle()
    expect(test.followups).toHaveLength(1)
    expect(test.calls).toEqual({ planning: 2, quota: 0, task: 0, spend: 0 })
    await test.driver.dispose()
  })

  it('releases a discarded human competitor without consuming planning recovery', async () => {
    const test = harness(binding('planning'))
    await test.idle()
    const first = test.followups[0] as UserMessage
    const message = human('discarded-human')
    test.nextTurn.push(message)
    test.driver.onInboxInserted(test.agent, message)
    expect(test.removed).toEqual([first.id])

    test.nextTurn.splice(test.nextTurn.indexOf(message), 1)
    test.setStatus('idle')
    test.driver.onInboxDiscarded(test.agent, message)
    await test.driver.whenSettled()
    expect(test.followups).toHaveLength(2)
    expect(test.calls).toEqual({ planning: 2, quota: 0, task: 0, spend: 0 })
    await test.driver.dispose()
  })

  it('rejects driver-source work after its reservation is gone but passes command-source work', async () => {
    const stale = harness(binding('planning'))
    await stale.idle()
    const automatic = stale.followups[0] as UserMessage
    stale.driver.onSessionEvent(stale.agent, command('command/run'))
    await stale.driver.whenSettled()
    const other = human('retained-human')
    expect(await stale.driver.onPreStep(
      stale.agent,
      [other, automatic],
      new AbortController().signal,
      () => Promise.reject(new Error('stale driver message reached downstream')),
    )).toEqual({ kind: 'reject' })
    expect(stale.nextStep).toEqual([other])
    await stale.driver.dispose()

    const commandSource = harness(binding('planning'))
    const semantic = commandPluginMessage('semantic-command')
    let delegated = false
    expect(await commandSource.driver.onPreStep(
      commandSource.agent,
      [semantic],
      new AbortController().signal,
      () => {
        delegated = true
        return Promise.resolve({ kind: 'enter', messages: [semantic] })
      },
    )).toEqual({ kind: 'enter', messages: [semantic] })
    expect(delegated).toBe(true)
    await commandSource.driver.dispose()
  })

  it('rejects stale planning and delivery reservations and restores other claimed input', async () => {
    for (const phase of ['planning', 'active_armed'] as const) {
      const test = harness(binding(phase))
      await test.idle()
      const automatic = test.followups[0] as UserMessage
      const before = human(`before-${phase}`)
      const after = human(`after-${phase}`)
      test.claim(automatic)
      test.setBinding(binding(phase, 2))
      const decision = await test.driver.onPreStep(
        test.agent,
        [before, automatic, after],
        new AbortController().signal,
        () => Promise.resolve({ kind: 'enter', messages: [before, automatic, after] }),
      )
      expect(decision).toEqual({ kind: 'reject' })
      expect(test.nextStep).toEqual([before, after])
      await test.driver.dispose()
    }
  })

  it('revalidates after downstream hooks and does not retry a rejected exact generation', async () => {
    const stale = harness(binding('planning'))
    await stale.idle()
    const automatic = stale.followups[0] as UserMessage
    const other = human('other-after-hook')
    stale.claim(automatic)
    const postHook = await stale.driver.onPreStep(
      stale.agent,
      [other, automatic],
      new AbortController().signal,
      () => {
        stale.setBinding(binding('planning', 2))
        return Promise.resolve({ kind: 'enter', messages: [other, automatic] })
      },
    )
    expect(postHook).toEqual({ kind: 'reject' })
    expect(stale.nextStep).toEqual([other])
    await stale.driver.dispose()

    const rejected = harness(binding('planning'))
    await rejected.idle()
    const rejectedMessage = rejected.followups[0] as UserMessage
    rejected.claim(rejectedMessage)
    expect(await rejected.driver.onPreStep(
      rejected.agent,
      [rejectedMessage],
      new AbortController().signal,
      () => Promise.resolve({ kind: 'reject' }),
    )).toEqual({ kind: 'reject' })
    await rejected.idle()
    expect(rejected.followups).toHaveLength(1)
    await rejected.driver.dispose()
  })

  it('lets admitted automatic work settle, then runs queued human work before fresh quota', async () => {
    const test = harness(binding('active_armed'))
    await test.idle()
    const automatic = test.followups[0] as UserMessage
    await admit(test, automatic)
    const message = human('human-next')
    test.nextTurn.push(message)
    test.driver.onInboxInserted(test.agent, message)
    expect(test.cancels).toEqual([])

    await test.idle()
    expect(test.calls.quota).toBe(1)
    test.claim(message)
    test.driver.onSessionEvent(test.agent, admitted(message))
    await test.idle()
    expect(test.calls.quota).toBe(2)
    expect(test.followups).toHaveLength(2)
    await test.driver.dispose()
  })
})
