import { describe, expect, it } from 'vitest'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
import { CoordinatorRegistry, installCoordinator } from '../src/coordinator.ts'
import {
  LoopXContinuationDriver,
  type LoopXDriverClock,
} from '../src/driver.ts'
import type {
  LoopXBoundHostThreadBindingV1,
  LoopXFailure,
  LoopXQuotaDecision,
  LoopXResult,
  LoopXSessionRef,
  LoopXTaskBody,
} from '../src/types.ts'

function ok<T>(value: T, application: 'yes' | 'no' = 'no'): LoopXResult<T> {
  return { ok: true, value, application }
}

function failed(
  operation: string,
  application: 'yes' | 'no' | 'unknown' = 'no',
): LoopXResult<never> {
  const error: LoopXFailure = {
    code: application === 'unknown' ? 'LOOPX_CLI_TIMEOUT' : 'LOOPX_READBACK_FAILED',
    message: `safe ${operation} failure`,
    operation,
    retryable: application === 'no',
    outcomeUncertain: application === 'unknown',
  }
  return { ok: false, error, application }
}

function cancelled(
  operation: string,
  code: 'LOOPX_DRIVER_NOT_ARMED' | 'LOOPX_FOREIGN_COMMAND_ACTIVE',
): LoopXResult<never> {
  return {
    ok: false,
    application: 'no',
    error: {
      code,
      message: `safe ${operation} cancellation`,
      operation,
      retryable: false,
      outcomeUncertain: false,
    },
  }
}

function binding(revision = 1): LoopXBoundHostThreadBindingV1 {
  return {
    schemaVersion: 'loopx_host_thread_binding_v1',
    hostSurface: 'dsh',
    threadId: 'session-a',
    revision,
    state: 'bound',
    target: { goalId: 'goal-a', agentId: 'agent-a' },
  }
}

function ref(agent: Agent): LoopXSessionRef {
  return {
    id: String(agent.id),
    session: agent.session,
    identity: { createdAt: agent.session.header.createdAt, cwd: agent.session.header.cwd },
  }
}

function decision(current: LoopXBoundHostThreadBindingV1, turnInstanceId: string): LoopXQuotaDecision {
  return {
    binding: current,
    goalId: current.target.goalId,
    agentId: current.target.agentId,
    turnInstanceId,
    shouldRun: true,
    effectiveAction: 'run_now',
    schedulerHint: {
      action: 'run_now', cadenceClass: 'immediate', resetToken: 'reset-a',
      recommendedIntervalMinutes: 1, unchangedPollLimit: 2,
    },
    terminalNoFollowup: false,
    payload: {
      schemaVersion: 'loopx_quota_projection_v1',
      goalId: current.target.goalId,
      shouldRun: true,
      effectiveAction: 'run_now',
    },
  }
}

class FakeService {
  readonly coordinator = new CoordinatorRegistry()
  current = binding()
  resolveCalls = 0
  quotaCalls = 0
  taskCalls = 0
  disposeCalls = 0
  quotaResult?: LoopXResult<LoopXQuotaDecision>
  taskResult?: LoopXResult<LoopXTaskBody>
  resolvePromise?: Promise<LoopXResult<LoopXBoundHostThreadBindingV1>>
  quotaError?: Error

  constructor() { installCoordinator(this, this.coordinator) }

  resolveBinding(session: LoopXSessionRef) {
    this.resolveCalls += 1
    this.coordinator.observeBinding(session, {
      key: 'home-a', cwd: '/workspace', runtimeRoot: '/runtime',
    }, this.current)
    return this.resolvePromise ?? Promise.resolve(ok(this.current))
  }

  quotaShouldRun(_session: LoopXSessionRef, turnInstanceId: string) {
    this.quotaCalls += 1
    if (this.quotaError !== undefined) return Promise.reject(this.quotaError)
    return Promise.resolve(this.quotaResult ?? ok(decision(this.current, turnInstanceId), 'yes'))
  }

  taskBody() {
    this.taskCalls += 1
    return Promise.resolve(this.taskResult ?? ok({
      binding: this.current,
      body: `fresh task body ${this.taskCalls}`,
    }))
  }

  disposeSession() {
    this.disposeCalls += 1
    return Promise.resolve()
  }
}

interface AgentHarness {
  agent: Agent
  readonly followups: UserMessage[]
  readonly nextTurn: UserMessage[]
  readonly nextStep: UserMessage[]
  readonly removed: UserMessage['id'][]
  readonly restored: Array<{ readonly message: UserMessage; readonly wakeup: boolean }>
  maintenanceClaims: number
  maintenanceCollisions: number
  whenIdleCalls: number
  duringFollowup?: (() => void) | undefined
  setStatus(value: 'idle' | 'running'): void
  connect(driver: LoopXContinuationDriver): void
}

function fakeAgent(): AgentHarness {
  let status: 'idle' | 'running' = 'running'
  let driver: LoopXContinuationDriver | undefined
  const followups: UserMessage[] = []
  const nextTurn: UserMessage[] = []
  const nextStep: UserMessage[] = []
  const removed: UserMessage['id'][] = []
  const restored: Array<{ readonly message: UserMessage; readonly wakeup: boolean }> = []
  const harness: AgentHarness = {
    agent: undefined as unknown as Agent,
    followups,
    nextTurn,
    nextStep,
    removed,
    restored,
    maintenanceClaims: 0,
    maintenanceCollisions: 0,
    whenIdleCalls: 0,
    duringFollowup: undefined,
    setStatus(value) { status = value },
    connect(value) { driver = value },
  }
  const session = {
    id: 'session-a',
    header: { version: 0, id: 'session-a', createdAt: 42, cwd: '/workspace' },
  }
  harness.agent = {
    id: 'session-a',
    session,
    get status() { return status },
    inbox: {
      get nextTurn() { return nextTurn },
      get nextStep() { return nextStep },
      get hasPending() { return nextTurn.length > 0 || nextStep.length > 0 },
      remove(messageId: UserMessage['id']) {
        for (const list of [nextStep, nextTurn]) {
          const index = list.findIndex(message => message.id === messageId)
          if (index >= 0) {
            const [message] = list.splice(index, 1)
            removed.push(messageId)
            if (message !== undefined) driver?.onInboxDiscarded(harness.agent, message)
            return true
          }
        }
        return false
      },
    },
    runMaintenance<T>(task: (taskSignal: AbortSignal) => Promise<T>): Promise<T> {
      harness.maintenanceClaims += 1
      if (harness.maintenanceCollisions > 0) {
        harness.maintenanceCollisions -= 1
        throw new Error('maintenance collision')
      }
      return task(new AbortController().signal)
    },
    whenIdle() {
      harness.whenIdleCalls += 1
      return Promise.resolve()
    },
    followup(message: UserMessage) {
      followups.push(message)
      nextTurn.push(message)
      harness.duringFollowup?.()
      driver?.onInboxInserted(harness.agent, message)
    },
    send(message: UserMessage, target: 'next-turn' | 'next-step', wakeup: boolean) {
      ;(target === 'next-turn' ? nextTurn : nextStep).push(message)
      restored.push({ message, wakeup })
    },
    steer() {},
    cancel() {},
  } as unknown as Agent
  return harness
}

interface FakeTimer {
  readonly id: number
  readonly callback: () => void
}

class FakeClock implements LoopXDriverClock {
  private id = 0
  readonly timers = new Map<number, FakeTimer>()
  now() { return 1_000 }
  setTimeout(callback: () => void, _delayMs: number): number {
    const id = ++this.id
    this.timers.set(id, { id, callback })
    return id
  }
  clearTimeout(handle: unknown): void {
    if (typeof handle === 'number') this.timers.delete(handle)
  }
  fireNext(): void {
    const timer = this.timers.values().next().value as FakeTimer | undefined
    if (timer === undefined) throw new Error('no timer')
    this.timers.delete(timer.id)
    timer.callback()
  }
}

interface Harness {
  readonly service: FakeService
  readonly current: AgentHarness
  readonly driver: LoopXContinuationDriver
  readonly clock: FakeClock
  arm(): void
  idle(): Promise<void>
  claim(message: UserMessage): void
  human(id: string): UserMessage
}

function harness(): Harness {
  const service = new FakeService()
  const current = fakeAgent()
  const clock = new FakeClock()
  const driver = new LoopXContinuationDriver({
    service: service as unknown as import('../src/types.ts').LoopXServiceApi,
    isLiveAgent: candidate => candidate === current.agent,
    clock,
    makeTurnInstanceId: () => `turn-${service.quotaCalls + 1}`,
  })
  current.connect(driver)
  driver.observeAgent(current.agent)
  return {
    service,
    current,
    driver,
    clock,
    arm() {
      const session = ref(current.agent)
      const home = { key: 'home-a', cwd: '/workspace', runtimeRoot: '/runtime' }
      service.coordinator.observeBinding(session, home, service.current)
      service.coordinator.arm(session, home, service.current)
    },
    async idle() {
      current.setStatus('idle')
      driver.onAgentStatus(current.agent, 'idle')
      await driver.whenSettled()
    },
    claim(message) {
      const index = current.nextTurn.findIndex(candidate => candidate.id === message.id)
      if (index >= 0) current.nextTurn.splice(index, 1)
      current.setStatus('running')
      driver.onInboxClaimed(current.agent, message)
    },
    human(id) {
      return {
        id: id as UserMessage['id'], role: 'user',
        content: [{ type: 'text', text: id }], source: { kind: 'user' },
      }
    },
  }
}

function commandEvent(type: 'command/run' | 'command/done', id: string): SessionEvent {
  return {
    type, seq: 0, time: 1,
    data: type === 'command/run'
      ? { commandId: id, name: 'anything', source: { kind: 'user' } }
      : { commandId: id, kind: 'success' },
  } as SessionEvent
}

describe('automatic continuation driver', () => {
  it('starts disarmed and queues only after an explicit arm plus idle admission', async () => {
    const test = harness()
    await test.idle()
    expect(test.service.resolveCalls).toBe(0)
    expect(test.current.followups).toEqual([])

    test.current.setStatus('running')
    test.arm()
    await test.idle()
    expect(test.service.resolveCalls).toBe(1)
    expect(test.service.quotaCalls).toBe(1)
    expect(test.service.taskCalls).toBe(1)
    expect(test.current.followups[0]?.content).toEqual([
      { type: 'text', text: 'fresh task body 1' },
    ])
    await test.driver.dispose()
  })

  it('freshly resolves binding, quota, and task body on every admitted round', async () => {
    const test = harness()
    test.arm()
    await test.idle()
    const first = test.current.followups[0] as UserMessage
    test.claim(first)
    expect(await test.driver.onPreStep(
      test.current.agent, [first], new AbortController().signal,
      () => Promise.resolve({ kind: 'enter', messages: [first] }),
    )).toMatchObject({ kind: 'enter' })
    await test.idle()
    expect(test.service.resolveCalls).toBe(2)
    expect(test.service.quotaCalls).toBe(2)
    expect(test.service.taskCalls).toBe(2)
    expect(test.current.followups[1]?.content).toEqual([
      { type: 'text', text: 'fresh task body 2' },
    ])
    await test.driver.dispose()
  })

  it('fences a stale cached binding revision before quota or queue admission', async () => {
    const test = harness()
    test.arm()
    test.service.current = binding(2)
    await test.idle()
    expect(test.service.resolveCalls).toBe(1)
    expect(test.service.quotaCalls).toBe(0)
    expect(test.current.followups).toEqual([])
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.activation).toBe('disarmed')
    await test.driver.dispose()
  })

  it('lets human input remove queued automatic work before claim without disarming', async () => {
    const test = harness()
    test.arm()
    await test.idle()
    const automatic = test.current.followups[0] as UserMessage
    const human = test.human('human-first')
    test.current.nextTurn.push(human)
    test.driver.onInboxInserted(test.current.agent, human)
    expect(test.current.removed).toEqual([automatic.id])
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.activation).toBe('armed')

    test.current.nextTurn.splice(test.current.nextTurn.indexOf(human), 1)
    await test.idle()
    expect(test.current.followups).toHaveLength(2)
    expect(test.service.quotaCalls).toBe(2)
    await test.driver.dispose()
  })

  it('removes exact reserved work when ordinary input reenters synchronous followup', async () => {
    const test = harness()
    const human = test.human('human-during-followup')
    test.current.duringFollowup = () => {
      test.current.duringFollowup = undefined
      test.current.nextTurn.push(human)
      test.driver.onInboxInserted(test.current.agent, human)
    }
    test.arm()
    await test.idle()
    const automatic = test.current.followups[0] as UserMessage
    expect(test.current.removed).toEqual([automatic.id])
    expect(test.current.nextTurn).toEqual([human])
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.activation).toBe('armed')
    await test.driver.dispose()
  })

  it('honors claim as the cutoff across later human input and authority invalidation', async () => {
    const test = harness()
    test.arm()
    await test.idle()
    const automatic = test.current.followups[0] as UserMessage
    test.claim(automatic)
    const human = test.human('human-after-claim')
    test.current.nextTurn.push(human)
    test.driver.onInboxInserted(test.current.agent, human)
    test.service.coordinator.pause(ref(test.current.agent))
    let downstream = false
    const decision = await test.driver.onPreStep(
      test.current.agent,
      [automatic, human],
      new AbortController().signal,
      () => {
        downstream = true
        return Promise.resolve({ kind: 'enter', messages: [automatic, human] })
      },
    )
    expect(decision).toEqual({ kind: 'enter', messages: [automatic, human] })
    expect(downstream).toBe(true)
    expect(test.current.removed).toEqual([])
    await test.driver.dispose()
  })

  it('restores and wakes non-plugin messages on an exceptional identity mismatch', async () => {
    const test = harness()
    const stale: UserMessage = {
      id: 'stale-auto' as UserMessage['id'], role: 'user',
      content: [{ type: 'text', text: 'stale' }],
      source: { kind: 'plugin', plugin: 'dsh-loopx-plugin/driver' },
    }
    const human = test.human('retained-human')
    const result = await test.driver.onPreStep(
      test.current.agent,
      [human, stale],
      new AbortController().signal,
      () => Promise.reject(new Error('stale work reached downstream')),
    )
    expect(result).toEqual({ kind: 'reject' })
    expect(test.current.restored).toEqual([{ message: human, wakeup: true }])
    expect(test.current.nextStep).toEqual([human])
    await test.driver.dispose()
  })

  it('rejects same-id automatic content tampering before the claim cutoff', async () => {
    const test = harness()
    test.arm()
    await test.idle()
    const automatic = test.current.followups[0] as UserMessage
    const tampered: UserMessage = {
      ...automatic,
      content: [{ type: 'text', text: 'tampered automatic body' }],
    }
    test.claim(tampered)
    const human = test.human('human-with-tamper')
    let downstream = false
    expect(await test.driver.onPreStep(
      test.current.agent,
      [tampered, human],
      new AbortController().signal,
      () => {
        downstream = true
        return Promise.resolve({ kind: 'enter', messages: [tampered, human] })
      },
    )).toEqual({ kind: 'reject' })
    expect(downstream).toBe(false)
    expect(test.current.restored).toEqual([{ message: human, wakeup: true }])
    await test.driver.dispose()
  })

  it('waits and retries a true-idle maintenance collision', async () => {
    const test = harness()
    test.current.maintenanceCollisions = 1
    test.arm()
    await test.idle()
    expect(test.current.maintenanceClaims).toBe(2)
    expect(test.current.whenIdleCalls).toBe(1)
    expect(test.service.quotaCalls).toBe(1)
    await test.driver.dispose()
  })

  it('counts one terminal outcome per attempt and suppresses the eighth failure', async () => {
    const test = harness()
    test.service.quotaResult = failed('quota')
    test.arm()
    await test.idle()
    for (let count = 1; count < 8; count += 1) {
      expect(test.service.coordinator.snapshot(ref(test.current.agent))?.failureCount).toBe(count)
      expect(test.clock.timers.size).toBe(1)
      test.clock.fireNext()
      await test.driver.whenSettled()
    }
    expect(test.service.resolveCalls).toBe(8)
    expect(test.service.quotaCalls).toBe(8)
    expect(test.service.taskCalls).toBe(0)
    expect(test.service.coordinator.snapshot(ref(test.current.agent))).toMatchObject({
      activation: 'armed', failureCount: 8, automaticFollowupSuppressed: true,
    })
    expect(test.clock.timers.size).toBe(0)
    await test.driver.dispose()
  })

  it('does not count an ordinary-input scope abort as an automatic failure', async () => {
    const test = harness()
    const pending = Promise.withResolvers<LoopXResult<LoopXBoundHostThreadBindingV1>>()
    test.service.resolvePromise = pending.promise
    test.arm()
    const idle = test.idle()
    await Promise.resolve()
    expect(test.service.resolveCalls).toBe(1)
    const human = test.human('human-cancels-scope')
    test.current.nextTurn.push(human)
    test.driver.onInboxInserted(test.current.agent, human)
    pending.resolve(cancelled('binding-resolve', 'LOOPX_DRIVER_NOT_ARMED'))
    await idle
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.failureCount).toBe(0)
    await test.driver.dispose()
  })

  it('does not count a foreign-command scope abort as an automatic failure', async () => {
    const test = harness()
    const pending = Promise.withResolvers<LoopXResult<LoopXBoundHostThreadBindingV1>>()
    test.service.resolvePromise = pending.promise
    test.arm()
    const idle = test.idle()
    await Promise.resolve()
    expect(test.service.resolveCalls).toBe(1)
    test.driver.onSessionEvent(test.current.agent, commandEvent('command/run', 'foreign-pending'))
    await Promise.resolve()
    pending.resolve(cancelled('binding-resolve', 'LOOPX_FOREIGN_COMMAND_ACTIVE'))
    await idle
    expect(test.service.coordinator.snapshot(ref(test.current.agent))).toMatchObject({
      failureCount: 0, foreignLatched: true,
    })
    test.driver.onSessionEvent(test.current.agent, commandEvent('command/done', 'foreign-pending'))
    await test.driver.dispose()
  })

  it('never schedules a blind retry after an applied or indeterminate failure', async () => {
    for (const application of ['yes', 'unknown'] as const) {
      const test = harness()
      test.service.quotaResult = failed('quota', application)
      test.arm()
      await test.idle()
      expect(test.service.coordinator.snapshot(ref(test.current.agent))?.failureCount).toBe(1)
      expect(test.clock.timers.size).toBe(0)
      await test.driver.dispose()
    }
  })

  it('counts one unexpected terminal Service rejection without retrying it', async () => {
    const test = harness()
    test.service.quotaError = new Error('terminal Service rejection')
    test.arm()
    await test.idle()
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.failureCount).toBe(1)
    expect(test.clock.timers.size).toBe(0)
    await test.driver.dispose()
  })

  it('classifies an unclaimed resolved command as foreign and latches disarm', async () => {
    const test = harness()
    test.arm()
    await test.idle()
    const automatic = test.current.followups[0] as UserMessage
    test.driver.onSessionEvent(test.current.agent, commandEvent('command/run', 'foreign-a'))
    await Promise.resolve()
    expect(test.current.removed).toEqual([automatic.id])
    expect(test.service.coordinator.snapshot(ref(test.current.agent))).toMatchObject({
      activation: 'disarmed', foreignLatched: true,
    })
    test.driver.onSessionEvent(test.current.agent, commandEvent('command/done', 'foreign-a'))
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.foreignLatched).toBe(true)
    await test.driver.dispose()
  })

  it('keeps an owned barrier through early command/done until raw settlement', async () => {
    const test = harness()
    test.arm()
    test.driver.onSessionEvent(test.current.agent, commandEvent('command/run', 'owned-a'))
    expect(test.service.coordinator.claimCommand(
      'owned-a', test.current.agent.session, test.current.agent,
    )).toBe(true)
    await Promise.resolve()
    test.driver.onSessionEvent(test.current.agent, commandEvent('command/done', 'owned-a'))
    expect(test.service.coordinator.hasBarrier(test.current.agent.session)).toBe(true)
    expect(test.service.coordinator.snapshot(ref(test.current.agent))?.activation).toBe('armed')
    test.service.coordinator.settleOwned('owned-a', test.current.agent.session)
    expect(test.service.coordinator.hasBarrier(test.current.agent.session)).toBe(false)
    await test.driver.dispose()
  })
})
