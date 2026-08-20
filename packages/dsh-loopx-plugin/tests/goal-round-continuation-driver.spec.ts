import { describe, expect, it } from 'vitest'
import type { Agent, PreStepDecision } from '@deepseek-ai/dsh-agent'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import { CoordinatorRegistry, installCoordinator } from '../src/coordinator.ts'
import { LoopXContinuationDriver } from '../src/driver.ts'
import type {
  LoopXBoundHostThreadBindingV1,
  LoopXQuotaDecision,
  LoopXResult,
  LoopXSessionRef,
  LoopXTaskBody,
} from '../src/types.ts'

const DRIVER_SOURCE = 'dsh-loopx-plugin/driver'

function ok<T>(value: T): LoopXResult<T> {
  return { ok: true, value, application: 'no' }
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

function sessionRef(agent: Agent): LoopXSessionRef {
  return {
    id: String(agent.id),
    session: agent.session,
    identity: {
      createdAt: agent.session.header.createdAt,
      ...(agent.session.header.cwd === undefined ? {} : { cwd: agent.session.header.cwd }),
    },
  }
}

function human(id: string): UserMessage {
  return {
    id: id as UserMessage['id'],
    role: 'user',
    content: [{ type: 'text', text: id }],
    source: { kind: 'user' },
  }
}

function pluginMessage(id: string, plugin: string): UserMessage {
  return {
    id: id as UserMessage['id'],
    role: 'user',
    content: [{ type: 'text', text: id }],
    source: { kind: 'plugin', plugin },
  }
}

function quota(
  current: LoopXBoundHostThreadBindingV1,
  turnInstanceId: string,
): LoopXQuotaDecision {
  return {
    binding: current,
    goalId: current.target.goalId,
    agentId: current.target.agentId,
    turnInstanceId,
    shouldRun: true,
    effectiveAction: 'run_now',
    schedulerHint: {
      action: 'run_now', cadenceClass: 'immediate', resetToken: 'round-reset',
      recommendedIntervalMinutes: 1, unchangedPollLimit: 1,
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

class RoundService {
  readonly coordinator = new CoordinatorRegistry()
  readonly home = { key: 'home-a', cwd: '/workspace', runtimeRoot: '/runtime' }
  current = binding()
  resolveCalls = 0
  quotaCalls = 0
  taskCalls = 0

  constructor() { installCoordinator(this, this.coordinator) }

  resolveBinding(session: LoopXSessionRef) {
    this.resolveCalls += 1
    this.coordinator.observeBinding(session, this.home, this.current)
    return Promise.resolve(ok(this.current))
  }

  quotaShouldRun(_session: LoopXSessionRef, turnInstanceId: string) {
    this.quotaCalls += 1
    return Promise.resolve(ok(quota(this.current, turnInstanceId)))
  }

  taskBody(): Promise<LoopXResult<LoopXTaskBody>> {
    this.taskCalls += 1
    return Promise.resolve(ok({ binding: this.current, body: `active round ${this.taskCalls}` }))
  }

  disposeSession() { return Promise.resolve() }
}

interface RoundHarness {
  agent: Agent
  readonly service: RoundService
  readonly driver: LoopXContinuationDriver
  readonly followups: UserMessage[]
  readonly nextTurn: UserMessage[]
  readonly nextStep: UserMessage[]
  readonly removed: UserMessage['id'][]
  readonly restored: Array<{ readonly message: UserMessage; readonly wakeup: boolean }>
  setStatus(status: 'idle' | 'running'): void
  arm(): void
  idle(): Promise<void>
  claim(message: UserMessage): void
  discard(message: UserMessage): void
}

function roundHarness(): RoundHarness {
  const service = new RoundService()
  let status: 'idle' | 'running' = 'running'
  let driver: LoopXContinuationDriver | undefined
  const followups: UserMessage[] = []
  const nextTurn: UserMessage[] = []
  const nextStep: UserMessage[] = []
  const removed: UserMessage['id'][] = []
  const restored: Array<{ readonly message: UserMessage; readonly wakeup: boolean }> = []
  const harness = {} as RoundHarness
  const session = {
    id: 'session-a',
    header: { version: 0, id: 'session-a', createdAt: 42, cwd: '/workspace' },
  }
  const agent = {
    id: 'session-a',
    session,
    get status() { return status },
    inbox: {
      get nextTurn() { return nextTurn },
      get nextStep() { return nextStep },
      get hasPending() { return nextTurn.length > 0 || nextStep.length > 0 },
      remove(messageId: UserMessage['id']) {
        for (const queue of [nextStep, nextTurn]) {
          const index = queue.findIndex(message => message.id === messageId)
          if (index < 0) continue
          const [message] = queue.splice(index, 1)
          removed.push(messageId)
          if (message !== undefined) driver?.onInboxDiscarded(agent as unknown as Agent, message)
          return true
        }
        return false
      },
    },
    runMaintenance<T>(task: (signal: AbortSignal) => Promise<T>) {
      return task(new AbortController().signal)
    },
    whenIdle() { return Promise.resolve() },
    followup(message: UserMessage) {
      followups.push(message)
      nextTurn.push(message)
      driver?.onInboxInserted(agent as unknown as Agent, message)
    },
    send(message: UserMessage, target: 'next-turn' | 'next-step', wakeup: boolean) {
      ;(target === 'next-turn' ? nextTurn : nextStep).push(message)
      restored.push({ message, wakeup })
    },
    steer() {},
    cancel() {},
  } as unknown as Agent
  driver = new LoopXContinuationDriver({
    service: service as unknown as import('../src/types.ts').LoopXServiceApi,
    isLiveAgent: candidate => candidate === agent,
    makeTurnInstanceId: () => `turn-${service.quotaCalls + 1}`,
  })
  driver.observeAgent(agent)
  Object.assign(harness, {
    agent, service, driver, followups, nextTurn, nextStep, removed, restored,
    setStatus(value: 'idle' | 'running') { status = value },
    arm() {
      const ref = sessionRef(agent)
      service.coordinator.observeBinding(ref, service.home, service.current)
      service.coordinator.arm(ref, service.home, service.current)
    },
    async idle() {
      status = 'idle'
      driver?.onAgentStatus(agent, 'idle')
      await driver?.whenSettled()
    },
    claim(message: UserMessage) {
      const index = nextTurn.findIndex(candidate => candidate.id === message.id)
      if (index >= 0) nextTurn.splice(index, 1)
      status = 'running'
      driver?.onInboxClaimed(agent, message)
    },
    discard(message: UserMessage) {
      for (const queue of [nextStep, nextTurn]) {
        const index = queue.findIndex(candidate => candidate.id === message.id)
        if (index >= 0) queue.splice(index, 1)
      }
      driver?.onInboxDiscarded(agent, message)
    },
  })
  return harness
}

function preStep(
  test: RoundHarness,
  messages: UserMessage[],
  next: () => Promise<PreStepDecision>,
): Promise<PreStepDecision> {
  return test.driver.onPreStep(test.agent, messages, new AbortController().signal, next)
}

describe('Goal-round continuation lifecycle', () => {
  it('keeps cached planning disarmed and uses only the fresh active lane after explicit arm', async () => {
    const test = roundHarness()
    const ref = sessionRef(test.agent)
    test.service.coordinator.observeBinding(ref, test.service.home, test.service.current)
    test.service.coordinator.cachePlanningBody(ref, 'planning checkpoint must not auto-run')
    await test.idle()
    expect(test.service.resolveCalls).toBe(0)
    expect(test.followups).toEqual([])

    test.setStatus('running')
    test.arm()
    await test.idle()
    expect(test.service.quotaCalls).toBe(1)
    expect(test.service.taskCalls).toBe(1)
    expect(test.followups[0]?.content).toEqual([{ type: 'text', text: 'active round 1' }])
    expect(JSON.stringify(test.followups)).not.toContain('planning checkpoint')
    await test.driver.dispose()
  })

  it('passes non-driver plugin input but rejects orphan driver work and wakes human input', async () => {
    const test = roundHarness()
    const command = pluginMessage('command-result', 'dsh-loopx-plugin/command')
    expect(await preStep(test, [command], () => Promise.resolve({
      kind: 'enter', messages: [command],
    }))).toEqual({ kind: 'enter', messages: [command] })

    const orphan = pluginMessage('orphan-driver', DRIVER_SOURCE)
    const person = human('retained-human')
    let reachedDownstream = false
    expect(await preStep(test, [person, orphan], () => {
      reachedDownstream = true
      return Promise.resolve({ kind: 'enter', messages: [person, orphan] })
    })).toEqual({ kind: 'reject' })
    expect(reachedDownstream).toBe(false)
    expect(test.restored).toEqual([{ message: person, wakeup: true }])
    expect(test.nextStep).toEqual([person])
    await test.driver.dispose()
  })

  it('treats exact claim as irrevocable across downstream input and authority races', async () => {
    const test = roundHarness()
    test.arm()
    await test.idle()
    const automatic = test.followups[0] as UserMessage
    test.claim(automatic)
    const person = human('human-after-claim')
    test.nextTurn.push(person)
    test.driver.onInboxInserted(test.agent, person)
    const decision = await preStep(test, [automatic, person], async () => {
      const ref = sessionRef(test.agent)
      test.service.coordinator.advanceEpoch(ref)
      test.service.coordinator.pause(ref)
      return { kind: 'enter', messages: [automatic, person] }
    })
    expect(decision).toEqual({ kind: 'enter', messages: [automatic, person] })
    expect(test.removed).toEqual([])
    expect(test.restored).toEqual([])
    await test.driver.dispose()
  })

  it('restores human input when downstream rejects and retires the exact reservation', async () => {
    const test = roundHarness()
    test.arm()
    await test.idle()
    const automatic = test.followups[0] as UserMessage
    test.claim(automatic)
    const person = human('human-in-rejected-batch')
    expect(await preStep(test, [automatic, person], () => Promise.resolve({
      kind: 'reject', reason: 'downstream gate',
    }))).toMatchObject({ kind: 'reject' })
    expect(test.restored).toEqual([{ message: person, wakeup: true }])

    let reachedDownstream = false
    expect(await preStep(test, [automatic], () => {
      reachedDownstream = true
      return Promise.resolve({ kind: 'enter', messages: [automatic] })
    })).toEqual({ kind: 'reject' })
    expect(reachedDownstream).toBe(false)
    await test.driver.dispose()
  })

  it('settles automatic work before fresh quota and gives queued human work priority', async () => {
    const test = roundHarness()
    test.arm()
    await test.idle()
    const automatic = test.followups[0] as UserMessage
    test.claim(automatic)
    expect((await preStep(test, [automatic], () => Promise.resolve({
      kind: 'enter', messages: [automatic],
    }))).kind).toBe('enter')

    const person = human('human-next-round')
    test.nextTurn.push(person)
    test.driver.onInboxInserted(test.agent, person)
    await test.idle()
    expect(test.service.quotaCalls).toBe(1)

    test.discard(person)
    await test.driver.whenSettled()
    expect(test.service.quotaCalls).toBe(2)
    expect(test.followups[1]?.content).toEqual([{ type: 'text', text: 'active round 2' }])
    await test.driver.dispose()
  })
})
