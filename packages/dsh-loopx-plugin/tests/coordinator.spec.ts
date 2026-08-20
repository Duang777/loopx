import { describe, expect, it, vi } from 'vitest'
import type { Agent } from '@deepseek-ai/dsh-agent'
import {
  CoordinatorAdmissionCancelled,
  CoordinatorRegistry,
  LOOPX_FAILURE_SUPPRESSION_THRESHOLD,
  isCoordinatorCancellation,
} from '../src/coordinator.ts'
import type {
  LoopXBoundHostThreadBindingV1,
  LoopXResult,
  LoopXSessionRef,
} from '../src/types.ts'

const home = Object.freeze({ key: 'runtime:fixture', cwd: '/fixture', runtimeRoot: '/fixture' })

function session(object: object = {}): LoopXSessionRef {
  return Object.freeze({
    id: 'session-a',
    session: object,
    identity: Object.freeze({ createdAt: 1, cwd: '/fixture' }),
  })
}

function binding(revision = 1): LoopXBoundHostThreadBindingV1 {
  return Object.freeze({
    schemaVersion: 'loopx_host_thread_binding_v1',
    hostSurface: 'dsh',
    threadId: 'session-a',
    revision,
    state: 'bound',
    target: Object.freeze({ goalId: 'goal-a', agentId: 'agent-a' }),
  })
}

describe('CoordinatorRegistry', () => {
  it('keys lifecycle and fences by exact Session object rather than structural identity', () => {
    const registry = new CoordinatorRegistry()
    const first = session({})
    const second = session({})
    const firstFence = registry.arm(first, home, binding())
    const secondFence = registry.arm(second, home, binding())
    expect(firstFence).toBeDefined()
    expect(secondFence).toBeDefined()
    expect(registry.isCurrent(firstFence!)).toBe(true)
    expect(registry.isCurrent(secondFence!)).toBe(true)

    registry.advanceEpoch(second)
    expect(registry.isCurrent(firstFence!)).toBe(true)
    expect(registry.isCurrent(secondFence!)).toBe(false)

    registry.drop(first)
    expect(registry.isClosed(first)).toBe(true)
    expect(registry.snapshot(first)?.activation).toBe('disarmed')
  })

  it('keeps equal command ids independent across exact Sessions', () => {
    const registry = new CoordinatorRegistry()
    const first = session({})
    const second = session({})
    const firstAgent = {}
    const secondAgent = {}
    registry.commandRun('same-command', first.session, firstAgent)
    registry.commandRun('same-command', second.session, secondAgent)

    expect(registry.claimCommand('same-command', first.session, firstAgent)).toBe(true)
    expect(registry.classifyUnclaimed('same-command', second.session)).toBe('foreign')
    expect(registry.hasBarrier(first)).toBe(true)
    expect(registry.hasBarrier(second)).toBe(true)

    registry.commandDone('same-command', first.session)
    expect(registry.hasBarrier(first)).toBe(true)
    registry.settleOwned('same-command', first.session)
    expect(registry.hasBarrier(first)).toBe(false)
    expect(registry.hasBarrier(second)).toBe(true)

    registry.commandDone('same-command', second.session)
    expect(registry.hasBarrier(second)).toBe(false)
    expect(registry.snapshot(second)).toMatchObject({
      activation: 'disarmed',
      foreignLatched: true,
    })
  })

  it('invalidates each failed attempt without disarming and suppresses only automation at eight', () => {
    const abort = vi.fn()
    const registry = new CoordinatorRegistry(abort)
    const current = session()
    expect(registry.arm(current, home, binding())).toBeDefined()
    const initialEpoch = registry.snapshot(current)?.activationEpoch ?? 0

    for (let count = 1; count < LOOPX_FAILURE_SUPPRESSION_THRESHOLD; count += 1) {
      expect(registry.recordOutcome(current, 'failure')).toMatchObject({
        activation: 'armed',
        failureCount: count,
        automaticFollowupSuppressed: false,
        activationEpoch: initialEpoch + count,
      })
    }
    expect(registry.recordOutcome(current, 'failure')).toMatchObject({
      activation: 'armed',
      failureCount: LOOPX_FAILURE_SUPPRESSION_THRESHOLD,
      automaticFollowupSuppressed: true,
      activationEpoch: initialEpoch + LOOPX_FAILURE_SUPPRESSION_THRESHOLD,
    })
    expect(abort).toHaveBeenCalledTimes(LOOPX_FAILURE_SUPPRESSION_THRESHOLD)

    const recoveryFence = registry.arm(current, home, binding())
    expect(recoveryFence).toBeDefined()
    expect(registry.isCurrent(recoveryFence!)).toBe(false)
    expect(registry.recordOutcome(current, 'success')).toMatchObject({
      activation: 'armed',
      failureCount: 0,
      automaticFollowupSuppressed: false,
    })
    expect(registry.isCurrent(recoveryFence!)).toBe(true)
  })

  it('fences home and revision changes and never restores activation from observation', () => {
    const registry = new CoordinatorRegistry()
    const current = session()
    const fence = registry.arm(current, home, binding())
    expect(registry.isCurrent(fence!)).toBe(true)

    registry.observeBinding(current, home, binding(2))
    expect(registry.snapshot(current)).toMatchObject({ activation: 'disarmed' })
    expect(registry.isCurrent(fence!)).toBe(false)

    const changedHome = Object.freeze({ key: 'runtime:other', cwd: '/other', runtimeRoot: '/other' })
    registry.observe(current, changedHome)
    expect(registry.snapshot(current)).toMatchObject({
      activation: 'disarmed',
      bindingHome: { key: 'runtime:other' },
    })
  })

  it('classifies local fencing and lifecycle cancellation as non-countable', () => {
    const cancelled = (code: 'LOOPX_DRIVER_NOT_ARMED' | 'LOOPX_SERVICE_CLOSED') => ({
      ok: false,
      application: 'unknown',
      error: {
        code,
        message: 'bounded',
        retryable: false,
        outcomeUncertain: true,
      },
    }) satisfies LoopXResult<never>
    expect(isCoordinatorCancellation(cancelled('LOOPX_DRIVER_NOT_ARMED'))).toBe(true)
    expect(isCoordinatorCancellation(cancelled('LOOPX_SERVICE_CLOSED'))).toBe(true)
    expect(isCoordinatorCancellation({ ok: true, value: undefined, application: 'no' })).toBe(false)
  })

  it('waits and retries an asynchronous hidden-maintenance collision without busy looping', async () => {
    const registry = new CoordinatorRegistry()
    const whenIdle = vi.fn(() => Promise.resolve())
    let attempts = 0
    const agent = {
      status: 'idle',
      whenIdle,
      runMaintenance<T>(task: (signal: AbortSignal) => Promise<T>): Promise<T> {
        attempts += 1
        if (attempts === 1) return Promise.reject(new Error('hidden maintenance owns idle'))
        return task(new AbortController().signal)
      },
    } as unknown as Agent

    await expect(registry.admitWhenIdle(
      agent,
      new AbortController().signal,
      () => true,
      async () => 'admitted',
    )).resolves.toEqual({ route: 'idle', value: 'admitted' })
    expect(attempts).toBe(2)
    expect(whenIdle).toHaveBeenCalledOnce()
  })

  it('cancels a hidden-maintenance wait when the caller aborts', async () => {
    const registry = new CoordinatorRegistry()
    let waitStarted: (() => void) | undefined
    const waiting = new Promise<void>((resolve) => { waitStarted = resolve })
    const whenIdle = vi.fn(() => {
      waitStarted?.()
      return new Promise<void>(() => {})
    })
    const task = vi.fn(async () => 'must-not-run')
    const agent = {
      status: 'idle',
      whenIdle,
      runMaintenance: vi.fn(() => Promise.reject(new Error('maintenance collision'))),
    } as unknown as Agent
    const controller = new AbortController()
    const admission = registry.admitWhenIdle(agent, controller.signal, () => true, task)

    await waiting
    const reason = new Error('caller aborted')
    const rejected = expect(admission).rejects.toBe(reason)
    controller.abort(reason)
    await rejected
    expect(whenIdle).toHaveBeenCalledOnce()
    expect(task).not.toHaveBeenCalled()
  })

  it('routes running when the Agent starts running during a maintenance-collision wait', async () => {
    const registry = new CoordinatorRegistry()
    let status: 'idle' | 'running' = 'idle'
    let waitStarted: (() => void) | undefined
    let releaseIdle: (() => void) | undefined
    const waiting = new Promise<void>((resolve) => { waitStarted = resolve })
    const whenIdle = vi.fn(() => new Promise<void>((resolve) => {
      releaseIdle = resolve
      waitStarted?.()
    }))
    const task = vi.fn(async () => 'must-not-run')
    const agent = {
      get status() { return status },
      whenIdle,
      runMaintenance: vi.fn(() => Promise.reject(new Error('maintenance collision'))),
    } as unknown as Agent
    const admission = registry.admitWhenIdle(
      agent,
      new AbortController().signal,
      () => true,
      task,
    )

    await waiting
    status = 'running'
    releaseIdle?.()
    await expect(admission).resolves.toEqual({ route: 'running' })
    expect(agent.runMaintenance).toHaveBeenCalledOnce()
    expect(task).not.toHaveBeenCalled()
  })

  it('retires serialized work that had not entered before exact Session disposal', async () => {
    const registry = new CoordinatorRegistry()
    const current = session()
    let release: (() => void) | undefined
    const gate = new Promise<void>((resolve) => { release = resolve })
    const first = registry.serialize(current, () => gate)
    let entered = false
    const second = registry.serialize(current, async () => { entered = true })
    await Promise.resolve()

    registry.drop(current)
    release?.()
    await first
    await expect(second).rejects.toBeInstanceOf(CoordinatorAdmissionCancelled)
    expect(entered).toBe(false)
  })
})
