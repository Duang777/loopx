/** Quota-gated, same-session LoopX continuation for DeepSeek Harness. */

import { randomUUID } from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'
import { FiberState } from '@deepseek-ai/cordis'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent, AgentStatus, PreStepDecision } from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-commands'
import type { Session, SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
import type {
  LoopXBindingFence,
  LoopXBindingRow,
  LoopXFailure,
  LoopXQuotaDecision,
  LoopXResult,
  LoopXSchedulerHint,
  LoopXContinuationServiceApi,
  LoopXSessionRef,
} from './types.ts'

export const name = 'dsh-loopx-driver'
export const inject = ['agents', 'loopx']

const PLUGIN_ID = 'dsh-loopx-plugin'
const DRIVER_SOURCE_ID = `${PLUGIN_ID}/driver`
const FAIL_CLOSED_RETRY_MS = 3 * 60_000
const MAX_TIMER_DELAY_MS = 2_147_483_647
const MAX_QUOTA_ATTEMPTS = 2

type TimerHandle = unknown

export interface LoopXDriverClock {
  now(): number
  setTimeout(callback: () => void, delayMs: number): TimerHandle
  clearTimeout(handle: TimerHandle): void
}

export interface LoopXDriverOptions {
  readonly service: LoopXContinuationServiceApi
  readonly isLiveAgent: (agent: Agent) => boolean
  readonly clock?: LoopXDriverClock
  readonly makeTurnInstanceId?: () => string
  readonly runDetached?: <T>(operation: () => Promise<T>) => Promise<T>
  readonly warn?: (message: string) => void
}

interface FollowupAttempt {
  readonly messageId: UserMessage['id']
  readonly content: UserMessage['content']
  readonly fence: LoopXBindingFence
  readonly lane: 'planning' | 'delivery'
  readonly epoch: number
  readonly instanceEpoch: number
  phase: 'queued' | 'claimed' | 'admitted'
}

interface ScheduledEvaluation {
  readonly handle: TimerHandle
  readonly epoch: number
  readonly fence: LoopXBindingFence
}

interface DriverState {
  readonly agent: Agent
  epoch: number
  blocked: boolean
  blockedFence: LoopXBindingFence | undefined
  stopping: boolean
  requested: boolean
  evaluation: Promise<void> | undefined
  controller: AbortController | undefined
  timer: ScheduledEvaluation | undefined
  followup: FollowupAttempt | undefined
  competingQueued: boolean
  planningConsumedGeneration: number | undefined
}

const systemClock: LoopXDriverClock = Object.freeze({
  now: () => Date.now(),
  setTimeout(callback: () => void, delayMs: number) {
    return setTimeout(callback, delayMs)
  },
  clearTimeout(handle: TimerHandle) {
    clearTimeout(handle as ReturnType<typeof setTimeout>)
  },
})

function sessionRef(agent: Agent): LoopXSessionRef {
  const { createdAt, cwd } = agent.session.header
  return Object.freeze({
    id: String(agent.id),
    identity: Object.freeze({
      createdAt,
      ...(cwd === undefined ? {} : { cwd }),
    }),
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

function fenceFromBinding(agent: Agent, binding: LoopXBindingRow): LoopXBindingFence {
  return Object.freeze({
    sessionId: String(agent.id),
    session: Object.freeze({ ...binding.session }),
    goalId: binding.goalId,
    agentId: binding.agentId,
    generation: binding.generation,
  })
}

function isOwnedSource(message: UserMessage, attempt: FollowupAttempt): boolean {
  return message.id === attempt.messageId
    && isDriverSource(message)
    && isDeepStrictEqual(message.content, attempt.content)
}

function isDriverSource(message: UserMessage): boolean {
  return message.source.kind === 'plugin'
    && message.source.plugin === DRIVER_SOURCE_ID
}

function createFollowupMessage(body: string): UserMessage {
  const content: UserMessage['content'] = [Object.freeze({ type: 'text', text: body })]
  return Object.freeze({
    id: randomUUID() as UserMessage['id'],
    role: 'user' as const,
    content: Object.freeze(content) as UserMessage['content'],
    source: Object.freeze({ kind: 'plugin' as const, plugin: DRIVER_SOURCE_ID }),
  })
}

function retryableQuotaFailure(error: LoopXFailure): boolean {
  return error.retryable && !error.outcomeUncertain
}

function validDelay(minutes: number | undefined): number | undefined {
  if (minutes === undefined || !Number.isSafeInteger(minutes) || minutes < 1) return undefined
  const delay = minutes * 60_000
  return Number.isSafeInteger(delay) && delay <= MAX_TIMER_DELAY_MS ? delay : undefined
}

function waitPlan(
  row: LoopXBindingRow,
  hint: LoopXSchedulerHint,
): {
  readonly delayMs?: number
  readonly unchangedPollCount: number
} {
  const resetToken = typeof hint.resetToken === 'string' && hint.resetToken.length > 0
    ? hint.resetToken
    : undefined
  const sameReset = resetToken !== undefined && resetToken === row.schedulerResetToken
  const unchanged = sameReset ? row.unchangedPollCount : 0
  const limit = Number.isSafeInteger(hint.unchangedPollLimit)
    && (hint.unchangedPollLimit as number) >= 0
    ? hint.unchangedPollLimit
    : undefined
  const delayMs = validDelay(hint.recommendedIntervalMinutes)
  const validHint = resetToken !== undefined
    && delayMs !== undefined
    && typeof hint.action === 'string' && hint.action.length > 0
    && typeof hint.cadenceClass === 'string' && hint.cadenceClass.length > 0
    && typeof hint.afterLimit === 'string' && hint.afterLimit.length > 0

  // A valid unchanged-poll limit means "quiet until a material Host event".
  // It must not be promoted to LoopX terminal state or pause the binding.
  if (validHint && limit !== undefined && unchanged >= limit) {
    return { unchangedPollCount: unchanged }
  }
  return {
    delayMs: validHint ? delayMs : FAIL_CLOSED_RETRY_MS,
    unchangedPollCount: unchanged + 1,
  }
}

/**
 * Process-local driver. All Goal, Todo, quota, status, evidence, and terminal
 * facts are consumed through the frozen LoopX service contract.
 */
export class LoopXContinuationDriver {
  private readonly service: LoopXContinuationServiceApi
  private readonly isLiveAgent: (agent: Agent) => boolean
  private readonly clock: LoopXDriverClock
  private readonly makeTurnInstanceId: () => string
  private readonly runDetached: <T>(operation: () => Promise<T>) => Promise<T>
  private readonly warn: (message: string) => void
  private readonly states = new Map<Agent, DriverState>()
  private readonly operations = new Set<Promise<void>>()
  private disposed = false
  private instanceEpoch = 0

  constructor(options: LoopXDriverOptions) {
    this.service = options.service
    this.isLiveAgent = options.isLiveAgent
    this.clock = options.clock ?? systemClock
    this.makeTurnInstanceId = options.makeTurnInstanceId ?? (() => `dsh-loopx-${randomUUID()}`)
    this.runDetached = options.runDetached ?? (operation => operation())
    this.warn = options.warn ?? (() => {})
  }

  /** Begin tracking one exact live Agent lifecycle. */
  observeAgent(agent: Agent, inheritedAuthority = false): void {
    const state = this.stateFor(agent)
    if (!inheritedAuthority) return
    const binding = this.bindingFor(state)
    if (binding === undefined) return
    this.cancelLocal(state, true)
    state.blocked = true
    state.blockedFence = fenceFromBinding(agent, binding)
    const expectedFence = fenceFromBinding(agent, binding)
    this.trackPause(state, 'manual_resume_required', expectedFence)
  }

  /** React to the public DSH idle/running transition. */
  onAgentStatus(agent: Agent, status: AgentStatus): void {
    const state = this.stateFor(agent)
    if (status !== 'idle') return
    state.competingQueued = this.hasCompetingPending(state)
    state.followup = undefined
    this.requestEvaluation(state)
  }

  /** Ordinary input temporarily wins over queued automatic work. */
  onInboxInserted(agent: Agent, message: UserMessage): void {
    const state = this.stateFor(agent)
    if (this.currentFollowupFence(state, message) !== undefined) return
    this.yieldToHuman(state)
  }

  /** Track admission of the one current-generation driver follow-up. */
  onInboxClaimed(agent: Agent, message: UserMessage): void {
    const state = this.states.get(agent)
    const attempt = state?.followup
    if (state !== undefined && attempt !== undefined
      && this.currentFollowupFence(state, message) !== undefined) {
      attempt.phase = 'claimed'
    }
  }

  /** Fail closed if DSH discards the reserved automatic message. */
  onInboxDiscarded(agent: Agent, message: UserMessage): void {
    const state = this.states.get(agent)
    if (state === undefined) return
    const expectedFence = this.currentFollowupFence(state, message)
    if (expectedFence === undefined) {
      state.competingQueued = this.hasCompetingPending(state)
      if (!state.competingQueued && state.agent.status === 'idle') {
        this.requestEvaluation(state)
      }
      return
    }
    this.cancelLocal(state, false)
    state.blocked = true
    state.blockedFence = expectedFence
    this.trackPause(state, 'readback_failed', expectedFence)
  }

  /** Observe durable message admission and direct human command boundaries. */
  onSessionEvent(agent: Agent, event: SessionEvent): void {
    const state = this.stateFor(agent)
    if (event.type === 'user/message') {
      const attempt = state.followup
      if (attempt !== undefined && this.currentFollowupFence(state, event.data) !== undefined) {
        attempt.phase = 'admitted'
        return
      }
      state.competingQueued = true
      return
    }
    if (event.type === 'command/run') {
      this.strongBoundary(state)
      return
    }
    if (event.type === 'command/done') {
      state.blocked = false
      state.blockedFence = undefined
      state.competingQueued = this.hasCompetingPending(state)
      this.requestEvaluation(state)
    }
  }

  /** A fresh Session lifecycle never inherits process-local continuation authority. */
  onSessionStart(agent: Agent): void {
    const state = this.stateFor(agent)
    const binding = this.bindingFor(state)
    this.cancelLocal(state, true)
    if (binding === undefined) {
      state.blocked = false
      state.blockedFence = undefined
      return
    }
    state.blocked = true
    state.blockedFence = fenceFromBinding(agent, binding)
    this.trackPause(state, 'manual_resume_required', fenceFromBinding(agent, binding))
  }

  /** Fence one claimed automatic prompt immediately around model-step admission. */
  async onPreStep(
    agent: Agent,
    messages: UserMessage[],
    signal: AbortSignal,
    next: () => Promise<PreStepDecision>,
  ): Promise<PreStepDecision> {
    const state = this.stateFor(agent)
    const attempt = state.followup
    const automatic = messages.filter(isDriverSource)
    if (automatic.length === 0) return next()
    const submitted = automatic[0] as UserMessage
    if (automatic.length !== 1 || attempt === undefined || !isOwnedSource(submitted, attempt)) {
      state.followup = undefined
      this.restoreOtherClaimed(agent, messages)
      return { kind: 'reject' }
    }
    if (!this.validReservation(state, attempt, submitted)) {
      state.followup = undefined
      this.restoreOtherClaimed(agent, messages)
      return { kind: 'reject' }
    }
    let decision: PreStepDecision
    try {
      decision = await next()
    } catch (error: unknown) {
      state.followup = undefined
      state.blocked = true
      state.blockedFence = attempt.fence
      throw error
    }
    if (signal.aborted) {
      if (decision.kind === 'enter') {
        this.restoreOtherClaimed(agent, decision.messages)
      }
      return decision
    }
    if (decision.kind === 'reject') {
      state.followup = undefined
      state.blocked = true
      state.blockedFence = attempt.fence
      return decision
    }
    if (!this.validReservation(state, attempt, submitted)) {
      state.followup = undefined
      this.restoreOtherClaimed(agent, decision.messages)
      return { kind: 'reject' }
    }
    attempt.phase = 'admitted'
    if (attempt.lane === 'planning') {
      state.planningConsumedGeneration = attempt.fence.generation
    }
    return decision
  }

  /** Dispose only this Agent/Session lane and drain its accepted sidecar write. */
  onAgentDisposed(agent: Agent): void {
    const state = this.states.get(agent)
    if (state === undefined) return
    state.stopping = true
    this.cancelLocal(state, false)
    this.states.delete(agent)
    const operation = this.service.disposeSession(sessionRef(agent)).catch(() => {
      this.warn('dsh-loopx-driver: Session disposal failed')
    })
    this.track(operation)
  }

  /** Cover custom runtimes that announce Session disposal without Agent disposal first. */
  onSessionDisposed(session: Session): void {
    for (const state of this.states.values()) {
      if (state.agent.session === session) this.onAgentDisposed(state.agent)
    }
  }

  /** Await every currently accepted driver operation; timers are deliberately excluded. */
  async whenSettled(): Promise<void> {
    while (this.operations.size > 0) {
      await Promise.allSettled([...this.operations])
    }
  }

  /** Cancel all lanes, disarm inherited authority, and drain before unload. */
  async dispose(): Promise<void> {
    if (this.disposed) {
      await this.whenSettled()
      return
    }
    this.disposed = true
    this.instanceEpoch += 1
    for (const state of this.states.values()) {
      const binding = this.bindingFor(state)
      state.stopping = true
      this.cancelLocal(state, true)
      if (binding?.phase === 'active_armed' || binding?.phase === 'planning') {
        this.trackPause(
          state,
          'manual_resume_required',
          fenceFromBinding(state.agent, binding),
        )
      }
    }
    await this.whenSettled()
    this.states.clear()
  }

  private stateFor(agent: Agent): DriverState {
    const existing = this.states.get(agent)
    if (existing !== undefined) return existing
    const state: DriverState = {
      agent,
      epoch: 0,
      blocked: false,
      blockedFence: undefined,
      stopping: false,
      requested: false,
      evaluation: undefined,
      controller: undefined,
      timer: undefined,
      followup: undefined,
      competingQueued: false,
      planningConsumedGeneration: undefined,
    }
    this.states.set(agent, state)
    return state
  }

  private bindingFor(state: DriverState): LoopXBindingRow | undefined {
    const result = this.service.getBinding(sessionRef(state.agent))
    return result.ok ? result.value : undefined
  }

  private ready(state: DriverState): boolean {
    const binding = this.bindingFor(state)
    if (state.blocked && state.blockedFence !== undefined && binding !== undefined
      && !sameFence(fenceFromBinding(state.agent, binding), state.blockedFence)) {
      state.blocked = false
      state.blockedFence = undefined
    }
    if (this.disposed || state.stopping || state.blocked || state.competingQueued
      || !this.isLiveAgent(state.agent) || state.agent.status !== 'idle'
      || state.followup !== undefined) return false
    return binding?.phase === 'active_armed'
      || (binding?.phase === 'planning'
        && state.planningConsumedGeneration !== binding.generation)
  }

  private requestEvaluation(state: DriverState): void {
    if (this.disposed || state.stopping) return
    state.requested = true
    if (state.evaluation !== undefined || state.timer !== undefined) return
    if (!this.ready(state)) {
      state.requested = false
      return
    }
    const fenceResult = this.service.fence(sessionRef(state.agent))
    if (!fenceResult.ok) {
      state.requested = false
      return
    }
    state.requested = false
    const epoch = state.epoch
    const instanceEpoch = this.instanceEpoch
    const controller = new AbortController()
    state.controller = controller
    let evaluation: Promise<void>
    try {
      evaluation = this.runDetached(async () => {
        await this.evaluate(state, epoch, instanceEpoch, fenceResult.value, controller.signal)
      })
    } catch {
      state.controller = undefined
      this.warn('dsh-loopx-driver: evaluation could not start')
      if (this.current(state, epoch, instanceEpoch, fenceResult.value)) {
        this.failClosed(state, fenceResult.value, 'readback_failed')
      }
      return
    }
    state.evaluation = evaluation
    this.track(evaluation)
    const retire = (): void => {
      if (state.evaluation === evaluation) state.evaluation = undefined
      if (state.controller === controller) state.controller = undefined
      if (state.requested) this.requestEvaluation(state)
    }
    void evaluation.then(retire, () => {
      this.warn('dsh-loopx-driver: evaluation rejected')
      if (this.current(state, epoch, instanceEpoch, fenceResult.value)) {
        this.failClosed(state, fenceResult.value, 'readback_failed')
      }
      retire()
    })
  }

  private async evaluate(
    state: DriverState,
    epoch: number,
    instanceEpoch: number,
    fence: LoopXBindingFence,
    signal: AbortSignal,
  ): Promise<void> {
    const binding = this.bindingFor(state)
    const lane = binding?.phase === 'planning' ? 'planning' : 'delivery'
    if (!this.current(state, epoch, instanceEpoch, fence, lane)) return
    const session = sessionRef(state.agent)
    if (lane === 'planning') {
      const planning = this.service.planningContinuation(session, fence.generation)
      if (!planning.ok || planning.value.kind !== 'planning'
        || !sameFence(planning.value.fence, fence)
        || planning.value.body.trim().length === 0
        || !this.current(state, epoch, instanceEpoch, fence, lane)) return
      this.sendFollowup(state, fence, planning.value.body, lane)
      return
    }
    const turnInstanceId = this.makeTurnInstanceId()
    let quota: LoopXResult<LoopXQuotaDecision> | undefined

    for (let attempt = 0; attempt < MAX_QUOTA_ATTEMPTS; attempt += 1) {
      quota = await this.service.quotaShouldRun(session, turnInstanceId, signal)
      if (!this.current(state, epoch, instanceEpoch, fence, lane)) return
      if (quota.ok) break
      if (quota.error.outcomeUncertain) {
        this.failClosed(state, fence, 'uncertain_write', true)
        return
      }
      if (!retryableQuotaFailure(quota.error) || attempt + 1 >= MAX_QUOTA_ATTEMPTS) {
        this.failClosed(state, fence, 'readback_failed')
        return
      }
    }
    if (quota === undefined || !quota.ok) return
    const decision = quota.value
    if (decision.turnInstanceId !== turnInstanceId
      || decision.goalId !== fence.goalId || decision.agentId !== fence.agentId) {
      this.failClosed(state, fence, 'readback_failed')
      return
    }

    if (decision.terminalNoFollowup) {
      this.cancelLocal(state, false)
      state.blocked = true
      state.blockedFence = fence
      const terminalEpoch = state.epoch
      await this.service.pause(session, 'loopx_terminal_observed', fence)
      if (!this.epochIsCurrent(state, terminalEpoch, instanceEpoch)) return
      return
    }

    if (decision.shouldRun || decision.schedulerHint.action === 'run_now') {
      const reset = await this.service.updateScheduler(
        session,
        fence,
        decision.schedulerHint,
        0,
      )
      if (!this.current(state, epoch, instanceEpoch, fence, lane)) return
      if (!reset.ok) {
        this.failClosed(state, fence,
          reset.error.outcomeUncertain ? 'uncertain_write' : 'readback_failed',
          reset.error.outcomeUncertain)
        return
      }
      const task = await this.service.taskBody(session, fence.generation, false, signal)
      if (!this.current(state, epoch, instanceEpoch, fence, lane)) return
      if (!task.ok || !sameFence(task.value.fence, fence) || task.value.body.trim().length === 0) {
        this.failClosed(state, fence, task.ok ? 'readback_failed' : task.error.outcomeUncertain
          ? 'uncertain_write'
          : 'readback_failed', !task.ok && task.error.outcomeUncertain)
        return
      }
      this.sendFollowup(state, fence, task.value.body)
      return
    }

    const currentBinding = this.bindingFor(state)
    if (currentBinding === undefined || currentBinding.phase !== 'active_armed'
      || currentBinding.generation !== fence.generation) return
    const plan = waitPlan(currentBinding, decision.schedulerHint)
    const now = this.clock.now()
    const nextCheckAt = plan.delayMs === undefined ? undefined : now + plan.delayMs
    if (nextCheckAt !== undefined && !Number.isSafeInteger(nextCheckAt)) {
      this.failClosed(state, fence, 'readback_failed')
      return
    }
    const updated = await this.service.updateScheduler(
      session,
      fence,
      decision.schedulerHint,
      plan.unchangedPollCount,
      nextCheckAt,
    )
    if (!this.current(state, epoch, instanceEpoch, fence, lane)) return
    if (!updated.ok) {
      this.failClosed(state, fence,
        updated.error.outcomeUncertain ? 'uncertain_write' : 'readback_failed',
        updated.error.outcomeUncertain)
      return
    }
    if (plan.delayMs !== undefined) this.schedule(state, epoch, fence, plan.delayMs)
  }

  private sendFollowup(
    state: DriverState,
    fence: LoopXBindingFence,
    body: string,
    lane: FollowupAttempt['lane'] = 'delivery',
  ): void {
    if (!this.ready(state) || !this.service.fenceIsCurrent(fence)) return
    const message = createFollowupMessage(body)
    state.followup = {
      messageId: message.id,
      content: message.content,
      fence,
      lane,
      epoch: state.epoch,
      instanceEpoch: this.instanceEpoch,
      phase: 'queued',
    }
    try {
      state.agent.followup(message)
    } catch {
      state.followup = undefined
      this.warn('dsh-loopx-driver: follow-up admission failed')
      if (lane === 'planning') {
        state.blocked = true
        state.blockedFence = fence
      }
      else this.failClosed(state, fence, 'readback_failed')
    }
  }

  private schedule(
    state: DriverState,
    epoch: number,
    fence: LoopXBindingFence,
    delayMs: number,
  ): void {
    if (!this.current(state, epoch, this.instanceEpoch, fence, 'delivery')
      || state.timer !== undefined) return
    let scheduled: ScheduledEvaluation
    const handle = this.clock.setTimeout(() => {
      if (state.timer !== scheduled) return
      state.timer = undefined
      if (!this.current(
        state,
        scheduled.epoch,
        this.instanceEpoch,
        scheduled.fence,
        'delivery',
      )) return
      this.requestEvaluation(state)
    }, delayMs)
    scheduled = { handle, epoch, fence }
    state.timer = scheduled
  }

  private strongBoundary(state: DriverState): void {
    const binding = this.bindingFor(state)
    const active = binding?.phase === 'active_armed' || binding?.phase === 'planning'
      || state.evaluation !== undefined || state.timer !== undefined || state.followup !== undefined
    if (!active || state.blocked || state.stopping || this.disposed) return
    state.blocked = true
    state.blockedFence = binding === undefined ? undefined : fenceFromBinding(state.agent, binding)
    this.cancelLocal(state, true)
    if (binding?.phase === 'active_armed' || binding?.phase === 'planning') {
      this.trackPause(state, 'foreign_input', fenceFromBinding(state.agent, binding))
    }
  }

  private yieldToHuman(state: DriverState): void {
    if (state.stopping || this.disposed) return
    state.competingQueued = true
    const attempt = state.followup
    if (attempt?.phase === 'claimed' || attempt?.phase === 'admitted') return
    state.epoch += 1
    state.requested = false
    state.controller?.abort(new Error('LoopX continuation yielded to human input'))
    state.controller = undefined
    if (state.timer !== undefined) {
      this.clock.clearTimeout(state.timer.handle)
      state.timer = undefined
    }
    state.followup = undefined
    if (attempt?.phase === 'queued') state.agent.inbox.remove(attempt.messageId)
  }

  private hasCompetingPending(state: DriverState): boolean {
    const attempt = state.followup
    return [...state.agent.inbox.nextStep, ...state.agent.inbox.nextTurn]
      .some(message => attempt === undefined || !isOwnedSource(message, attempt))
  }

  private validReservation(
    state: DriverState,
    attempt: FollowupAttempt,
    message: UserMessage,
  ): boolean {
    if (this.disposed || state.stopping || state.followup !== attempt
      || attempt.phase !== 'claimed' || !isOwnedSource(message, attempt)
      || !this.isLiveAgent(state.agent)
      || state.epoch !== attempt.epoch || this.instanceEpoch !== attempt.instanceEpoch
      || !this.service.fenceIsCurrent(attempt.fence)) return false
    const binding = this.bindingFor(state)
    const phase = attempt.lane === 'planning' ? 'planning' : 'active_armed'
    return binding?.phase === phase
      && sameFence(fenceFromBinding(state.agent, binding), attempt.fence)
  }

  private restoreOtherClaimed(
    agent: Agent,
    messages: UserMessage[],
  ): void {
    const retained = messages.filter(message => !isDriverSource(message))
    for (const message of [...retained].reverse()) {
      if (agent.inbox.nextStep.some(candidate => candidate.id === message.id)
        || agent.inbox.nextTurn.some(candidate => candidate.id === message.id)) continue
      agent.inbox.prepend('next-step', message)
    }
  }

  private currentFollowupFence(
    state: DriverState,
    message: UserMessage,
  ): LoopXBindingFence | undefined {
    const attempt = state.followup
    if (attempt === undefined || !isOwnedSource(message, attempt)) return undefined
    const binding = this.bindingFor(state)
    const phase = attempt.lane === 'planning' ? 'planning' : 'active_armed'
    if (binding?.phase !== phase || !sameFence(fenceFromBinding(state.agent, binding), attempt.fence)) {
      return undefined
    }
    return attempt.fence
  }

  private failClosed(
    state: DriverState,
    expectedFence: LoopXBindingFence,
    reason: 'readback_failed' | 'uncertain_write',
    uncertain = false,
  ): void {
    if (state.stopping || this.disposed) return
    if (!this.service.fenceIsCurrent(expectedFence)) return
    this.cancelLocal(state, true)
    state.blocked = true
    state.blockedFence = expectedFence
    const session = sessionRef(state.agent)
    const operation = uncertain
      ? this.service.markUncertain(session, reason, expectedFence).then(() => undefined)
      : this.service.pause(session, reason, expectedFence).then(() => undefined)
    this.track(operation.catch(() => {
      this.warn('dsh-loopx-driver: fail-closed transition failed')
    }))
  }

  private trackPause(
    state: DriverState,
    reason: 'foreign_input' | 'manual_resume_required' | 'readback_failed',
    expectedFence: LoopXBindingFence,
  ): void {
    const operation = this.service.pause(
      sessionRef(state.agent),
      reason,
      expectedFence,
    ).then(() => undefined)
    this.track(operation.catch(() => {
      this.warn('dsh-loopx-driver: pause failed')
    }))
  }

  private cancelLocal(state: DriverState, cancelFollowup: boolean): void {
    state.epoch += 1
    state.requested = false
    state.controller?.abort(new Error('LoopX continuation cancelled'))
    state.controller = undefined
    if (state.timer !== undefined) {
      this.clock.clearTimeout(state.timer.handle)
      state.timer = undefined
    }
    const followup = state.followup
    state.followup = undefined
    if (!cancelFollowup || followup === undefined) return
    if (followup.phase === 'queued') {
      state.agent.inbox.remove(followup.messageId)
      return
    }
    if (state.agent.status === 'running') {
      state.agent.cancel(
        { kind: 'hook', reason: 'dsh-loopx-plugin foreign input' },
        { keepInbox: true },
      )
      const idle = state.agent.whenIdle().catch(() => {
        this.warn('dsh-loopx-driver: Agent quiescence wait failed')
      })
      this.track(idle)
    }
  }

  private current(
    state: DriverState,
    epoch: number,
    instanceEpoch: number,
    fence: LoopXBindingFence,
    lane?: FollowupAttempt['lane'],
  ): boolean {
    const binding = this.bindingFor(state)
    const phase = lane === 'planning' ? 'planning'
      : lane === 'delivery' ? 'active_armed'
      : binding?.phase
    return this.epochIsCurrent(state, epoch, instanceEpoch)
      && this.isLiveAgent(state.agent)
      && state.agent.status === 'idle'
      && this.service.fenceIsCurrent(fence)
      && (phase === 'planning' || phase === 'active_armed')
      && binding?.phase === phase
  }

  private epochIsCurrent(
    state: DriverState,
    epoch: number,
    instanceEpoch: number,
  ): boolean {
    return !this.disposed && !state.stopping
      && state.epoch === epoch && this.instanceEpoch === instanceEpoch
  }

  private track(operation: Promise<void>): void {
    this.operations.add(operation)
    void operation.then(
      () => { this.operations.delete(operation) },
      () => { this.operations.delete(operation) },
    )
  }

}

/** Install the Host-plane continuation listeners. */
export function apply(ctx: Context): void {
  const driver = new LoopXContinuationDriver({
    service: ctx.loopx,
    isLiveAgent: agent => ctx.fiber.state === FiberState.ACTIVE
      && ctx.agents.get(agent.id) === agent,
    runDetached: operation => ctx.agents.withoutInitiator(operation),
    warn: message => { ctx.logger.warn(message) },
  })

  ctx.effect(function* () {
    ctx.on('agent/created', ({ agent }) => { driver.observeAgent(agent) })
    ctx.on('agent/disposed', ({ agent }) => { driver.onAgentDisposed(agent) })
    ctx.on('agent/session-start', ({ agent }) => { driver.onSessionStart(agent) })
    ctx.on('agent/status', ({ agent, status }) => { driver.onAgentStatus(agent, status) })
    ctx.on('agent/inbox/inserted', ({ agent, message }) => {
      driver.onInboxInserted(agent, message)
    })
    ctx.on('agent/inbox/claimed', ({ agent, message }) => {
      driver.onInboxClaimed(agent, message)
    })
    ctx.on('agent/inbox/discarded', ({ agent, message }) => {
      driver.onInboxDiscarded(agent, message)
    })
    ctx.on('agent/pre-step', ({ agent, messages, signal }, next) =>
      driver.onPreStep(agent, messages, signal, next))
    ctx.on('session/event', (session, event) => {
      const agent = ctx.agents.get(session.id)
      if (agent?.session === session) driver.onSessionEvent(agent, event)
    })
    ctx.on('session/disposed', session => { driver.onSessionDisposed(session) })

    // Loading over a live Agent never inherits a previous driver's authority.
    for (const agent of ctx.agents.list()) driver.observeAgent(agent, true)

    yield () => driver.dispose()
  }, 'dsh-loopx-driver lifecycle')
}
