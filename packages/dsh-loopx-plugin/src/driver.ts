/** Quota-gated, exact-session automatic continuation for DeepSeek Harness. */

import { randomUUID } from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'
import { FiberState } from '@deepseek-ai/cordis'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent, AgentStatus, PreStepDecision } from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-commands'
import type { Session, SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
import {
  CoordinatorAdmissionCancelled,
  coordinatorFor,
  isCoordinatorCancellation,
} from './coordinator.ts'
import type {
  CoordinatorFence,
  CoordinatorRegistry,
  CoordinatorTopLevelOperation,
} from './coordinator.ts'
import type {
  LoopXBoundHostThreadBindingV1,
  LoopXQuotaDecision,
  LoopXResult,
  LoopXSchedulerHint,
  LoopXServiceApi,
  LoopXSessionRef,
} from './types.ts'

export const name = 'dsh-loopx-driver'
export const inject = ['agents', 'loopx']

const PLUGIN_ID = 'dsh-loopx-plugin'
const DRIVER_SOURCE_ID = `${PLUGIN_ID}/driver`
const FAIL_CLOSED_RETRY_MS = 3 * 60_000
const MAX_TIMER_DELAY_MS = 2_147_483_647

type TimerHandle = unknown

export interface LoopXDriverClock {
  now(): number
  setTimeout(callback: () => void, delayMs: number): TimerHandle
  clearTimeout(handle: TimerHandle): void
}

export interface LoopXDriverOptions {
  readonly service: LoopXServiceApi
  readonly isLiveAgent: (agent: Agent) => boolean
  readonly clock?: LoopXDriverClock
  readonly makeTurnInstanceId?: () => string
  readonly runDetached?: <T>(operation: () => Promise<T>) => Promise<T>
  readonly warn?: (message: string) => void
}

type ReservationPhase = 'reserved' | 'queued' | 'claimed' | 'entered' | 'retired'

interface AutomaticReservation {
  readonly messageId: UserMessage['id']
  readonly content: UserMessage['content']
  readonly fence: CoordinatorFence
  phase: ReservationPhase
}

interface ScheduledEvaluation {
  readonly handle: TimerHandle
  readonly fence: CoordinatorFence
}

interface DriverState {
  readonly agent: Agent
  stopping: boolean
  requested: boolean
  evaluation?: Promise<void> | undefined
  controller?: AbortController | undefined
  timer?: ScheduledEvaluation | undefined
  reservation?: AutomaticReservation | undefined
  schedulerResetToken?: string | undefined
  unchangedPollCount: number
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
    session: agent.session,
    identity: Object.freeze({ createdAt, ...(cwd === undefined ? {} : { cwd }) }),
  })
}

function sameBinding(binding: LoopXBoundHostThreadBindingV1, fence: CoordinatorFence): boolean {
  return binding.threadId === fence.threadId
    && binding.revision === fence.bindingRevision
    && binding.target.goalId === fence.goalId
    && binding.target.agentId === fence.agentId
}

function isDriverSource(message: UserMessage): boolean {
  return message.source.kind === 'plugin' && message.source.plugin === DRIVER_SOURCE_ID
}

function isReservationMessage(
  message: UserMessage,
  reservation: AutomaticReservation,
): boolean {
  return message.id === reservation.messageId
    && isDriverSource(message)
    && isDeepStrictEqual(message.content, reservation.content)
}

function createAutomaticMessage(body: string): UserMessage {
  const content: UserMessage['content'] = [Object.freeze({ type: 'text', text: body })]
  return Object.freeze({
    id: randomUUID() as UserMessage['id'],
    role: 'user' as const,
    content: Object.freeze(content) as UserMessage['content'],
    source: Object.freeze({ kind: 'plugin' as const, plugin: DRIVER_SOURCE_ID }),
  })
}

function validDelay(minutes: number | undefined): number | undefined {
  if (minutes === undefined || !Number.isSafeInteger(minutes) || minutes < 1) return undefined
  const delay = minutes * 60_000
  return Number.isSafeInteger(delay) && delay <= MAX_TIMER_DELAY_MS ? delay : undefined
}

function waitDelay(
  state: DriverState,
  hint: LoopXSchedulerHint,
): number | undefined {
  const resetToken = typeof hint.resetToken === 'string' && hint.resetToken.length > 0
    ? hint.resetToken
    : undefined
  const sameReset = resetToken !== undefined && resetToken === state.schedulerResetToken
  const unchanged = sameReset ? state.unchangedPollCount : 0
  const limit = Number.isSafeInteger(hint.unchangedPollLimit)
    && (hint.unchangedPollLimit as number) >= 0
    ? hint.unchangedPollLimit
    : undefined
  const delay = validDelay(hint.recommendedIntervalMinutes)
  const valid = resetToken !== undefined && delay !== undefined
    && hint.action.length > 0 && hint.cadenceClass.length > 0
  state.schedulerResetToken = resetToken
  state.unchangedPollCount = unchanged + 1
  if (valid && limit !== undefined && unchanged >= limit) return undefined
  return valid ? delay : FAIL_CLOSED_RETRY_MS
}

/** Driver-local reservation/timer mechanics over the one shared coordinator. */
export class LoopXContinuationDriver {
  private readonly service: LoopXServiceApi
  private readonly coordinators: CoordinatorRegistry
  private readonly isLiveAgent: (agent: Agent) => boolean
  private readonly clock: LoopXDriverClock
  private readonly makeTurnInstanceId: () => string
  private readonly runDetached: <T>(operation: () => Promise<T>) => Promise<T>
  private readonly warn: (message: string) => void
  private readonly states = new Map<Agent, DriverState>()
  private readonly operations = new Set<Promise<void>>()
  private readonly stopCoordinatorEvents: () => void
  private disposed = false

  constructor(options: LoopXDriverOptions) {
    this.service = options.service
    this.coordinators = coordinatorFor(options.service)
    this.isLiveAgent = options.isLiveAgent
    this.clock = options.clock ?? systemClock
    this.makeTurnInstanceId = options.makeTurnInstanceId ?? (() => `dsh-loopx-${randomUUID()}`)
    this.runDetached = options.runDetached ?? (operation => operation())
    this.warn = options.warn ?? (() => {})
    this.stopCoordinatorEvents = this.coordinators.onInvalidated(event => {
      const state = [...this.states.values()].find(candidate =>
        candidate.agent.session === event.sessionObject)
      if (state === undefined) return
      if (event.kind === 'armed' || event.kind === 'barrier_released'
        || event.kind === 'recovered') {
        this.requestEvaluation(state)
        return
      }
      this.cancelUnadmitted(state)
    })
  }

  /** A newly observed exact Session never inherits activation. */
  observeAgent(agent: Agent): void {
    this.stateFor(agent)
    this.coordinators.observe(sessionRef(agent))
  }

  onAgentStatus(agent: Agent, status: AgentStatus): void {
    const state = this.stateFor(agent)
    if (status !== 'idle') return
    if (state.reservation?.phase === 'claimed' || state.reservation?.phase === 'entered') {
      this.retireReservation(state)
    }
    this.requestEvaluation(state)
  }

  /** Ordinary input owns the queue until claim; a claimed automatic batch is committed. */
  onInboxInserted(agent: Agent, message: UserMessage): void {
    const state = this.stateFor(agent)
    const reservation = state.reservation
    if (reservation !== undefined && isReservationMessage(message, reservation)) return
    if (reservation?.phase === 'claimed' || reservation?.phase === 'entered') return
    this.coordinators.advanceEpoch(sessionRef(agent))
    this.cancelUnadmitted(state)
  }

  onInboxClaimed(agent: Agent, message: UserMessage): void {
    const reservation = this.states.get(agent)?.reservation
    if (reservation !== undefined && isReservationMessage(message, reservation)
      && (reservation.phase === 'queued' || reservation.phase === 'reserved')) {
      reservation.phase = 'claimed'
    }
  }

  onInboxDiscarded(agent: Agent, message: UserMessage): void {
    const state = this.states.get(agent)
    if (state === undefined) return
    const reservation = state.reservation
    if (reservation !== undefined && isReservationMessage(message, reservation)) {
      this.retireReservation(state)
    }
    if (agent.status === 'idle') this.requestEvaluation(state)
  }

  /** Open a neutral barrier, then classify unclaimed handlers in the next microtask. */
  onSessionEvent(agent: Agent, event: SessionEvent): void {
    const state = this.stateFor(agent)
    if (event.type === 'command/run') {
      const commandId = String(event.data.commandId)
      this.coordinators.commandRun(commandId, agent.session, agent)
      this.cancelUnadmitted(state)
      queueMicrotask(() => {
        if (this.coordinators.classifyUnclaimed(commandId, agent.session) === 'foreign') {
          this.cancelUnadmitted(state)
        }
      })
      return
    }
    if (event.type === 'command/done') {
      this.coordinators.commandDone(String(event.data.commandId), agent.session)
    }
  }

  onSessionStart(agent: Agent): void {
    const state = this.stateFor(agent)
    this.coordinators.invalidate(sessionRef(agent), { clearCaches: true })
    this.cancelUnadmitted(state)
  }

  /** Claimed identity is the cancellation cutoff; later authority/input never rejects it. */
  async onPreStep(
    agent: Agent,
    messages: UserMessage[],
    _signal: AbortSignal,
    next: () => Promise<PreStepDecision>,
  ): Promise<PreStepDecision> {
    const state = this.stateFor(agent)
    const automatic = messages.filter(isDriverSource)
    if (automatic.length === 0) return next()
    const reservation = state.reservation
    const submitted = automatic[0]
    if (automatic.length !== 1 || submitted === undefined || reservation === undefined
      || reservation.phase !== 'claimed' || !isReservationMessage(submitted, reservation)) {
      this.restoreAndWake(agent, messages)
      this.retireReservation(state)
      return { kind: 'reject' }
    }
    let decision: PreStepDecision
    try {
      decision = await next()
    } catch (error: unknown) {
      this.restoreAndWake(agent, messages)
      this.retireReservation(state)
      throw error
    }
    if (decision.kind === 'reject') {
      this.restoreAndWake(agent, messages)
      this.retireReservation(state)
      return decision
    }
    reservation.phase = 'entered'
    return decision
  }

  onAgentDisposed(agent: Agent): void {
    const state = this.states.get(agent)
    if (state === undefined) return
    state.stopping = true
    this.cancelUnadmitted(state)
    this.states.delete(agent)
    const session = sessionRef(agent)
    const operation = this.service.disposeSession(session)
      .catch(() => { this.warn('dsh-loopx-driver: Session disposal failed') })
      .finally(() => this.coordinators.drop(session))
    this.track(operation)
  }

  onSessionDisposed(session: Session): void {
    for (const state of this.states.values()) {
      if (state.agent.session === session) this.onAgentDisposed(state.agent)
    }
  }

  async whenSettled(): Promise<void> {
    while (this.operations.size > 0) await Promise.allSettled([...this.operations])
  }

  async dispose(): Promise<void> {
    if (this.disposed) return this.whenSettled()
    this.disposed = true
    this.stopCoordinatorEvents()
    for (const state of [...this.states.values()]) this.onAgentDisposed(state.agent)
    await this.whenSettled()
  }

  private stateFor(agent: Agent): DriverState {
    const found = this.states.get(agent)
    if (found !== undefined) return found
    const state: DriverState = {
      agent,
      stopping: false,
      requested: false,
      unchangedPollCount: 0,
    }
    this.states.set(agent, state)
    return state
  }

  private hasOrdinaryPending(state: DriverState): boolean {
    const reservation = state.reservation
    return [...state.agent.inbox.nextStep, ...state.agent.inbox.nextTurn].some(message =>
      reservation === undefined || !isReservationMessage(message, reservation))
  }

  private eligible(state: DriverState, fence: CoordinatorFence): boolean {
    return !this.disposed && !state.stopping && this.isLiveAgent(state.agent)
      && this.coordinators.isCurrent(fence) && !this.hasOrdinaryPending(state)
      && state.reservation === undefined
  }

  private ready(state: DriverState): CoordinatorFence | undefined {
    if (this.disposed || state.stopping || state.agent.status !== 'idle'
      || state.evaluation !== undefined || state.timer !== undefined
      || state.reservation !== undefined || this.hasOrdinaryPending(state)) return undefined
    return this.coordinators.fence(sessionRef(state.agent))
  }

  private requestEvaluation(state: DriverState): void {
    if (this.disposed || state.stopping) return
    state.requested = true
    const fence = this.ready(state)
    if (fence === undefined) {
      state.requested = false
      return
    }
    state.requested = false
    const controller = new AbortController()
    state.controller = controller
    let operation: Promise<void>
    try {
      operation = this.runDetached(() => this.admitEvaluation(state, fence, controller.signal))
    } catch {
      state.controller = undefined
      this.warn('dsh-loopx-driver: evaluation could not start')
      return
    }
    state.evaluation = operation
    this.track(operation)
    const finalize = (): void => {
      if (state.evaluation === operation) state.evaluation = undefined
      if (state.controller === controller) state.controller = undefined
      if (state.requested) this.requestEvaluation(state)
    }
    void operation.then(finalize, finalize)
  }

  private async admitEvaluation(
    state: DriverState,
    fence: CoordinatorFence,
    signal: AbortSignal,
  ): Promise<void> {
    try {
      const admitted = await this.coordinators.admitWhenIdle(
        state.agent,
        signal,
        () => this.eligible(state, fence),
        maintenanceSignal => this.evaluate(
          state,
          fence,
          AbortSignal.any([signal, maintenanceSignal]),
        ),
      )
      if (admitted.route === 'running') return
    } catch (error: unknown) {
      if (signal.aborted || error instanceof CoordinatorAdmissionCancelled) return
      this.warn('dsh-loopx-driver: automatic evaluation rejected')
    }
  }

  private async evaluate(
    state: DriverState,
    fence: CoordinatorFence,
    signal: AbortSignal,
  ): Promise<void> {
    const session = sessionRef(state.agent)
    const topLevel = this.coordinators.beginTopLevel(session)
    try {
      await this.evaluateAttempt(state, fence, signal, session, topLevel)
    } catch {
      if (signal.aborted || !this.coordinators.isCurrent(fence)) topLevel.cancel()
      else {
        topLevel.fail()
        this.warn('dsh-loopx-driver: automatic Service attempt failed unexpectedly')
      }
    }
  }

  private async evaluateAttempt(
    state: DriverState,
    fence: CoordinatorFence,
    signal: AbortSignal,
    session: LoopXSessionRef,
    topLevel: CoordinatorTopLevelOperation,
  ): Promise<void> {
    const binding = await this.service.resolveBinding(session, signal)
    if (!binding.ok) {
      this.failAttempt(state, fence, signal, topLevel, binding, binding.application)
      return
    }
    if (binding.value.state !== 'bound' || !sameBinding(binding.value, fence)
      || !this.eligible(state, fence)) {
      topLevel.cancel()
      return
    }

    const turnInstanceId = this.makeTurnInstanceId()
    const quota = await this.service.quotaShouldRun(session, turnInstanceId, signal)
    if (!quota.ok) {
      this.failAttempt(state, fence, signal, topLevel, quota, quota.application)
      return
    }
    if (!this.validDecision(quota.value, fence, turnInstanceId)
      || !this.eligible(state, fence)) {
      topLevel.cancel()
      return
    }
    if (quota.value.terminalNoFollowup) {
      topLevel.succeed()
      this.coordinators.pause(session)
      return
    }
    if (!quota.value.shouldRun && quota.value.schedulerHint.action !== 'run_now') {
      topLevel.succeed()
      const delay = waitDelay(state, quota.value.schedulerHint)
      if (delay !== undefined && this.eligible(state, fence)) this.schedule(state, fence, delay)
      return
    }

    const task = await this.service.taskBody(session, true, signal)
    if (!task.ok) {
      this.failAttempt(state, fence, signal, topLevel, task, task.application)
      return
    }
    if (!sameBinding(task.value.binding, fence) || task.value.body.trim().length === 0
      || !this.eligible(state, fence)) {
      topLevel.cancel()
      return
    }
    topLevel.succeed()
    this.queueAutomatic(state, fence, task.value.body)
  }

  private validDecision(
    decision: LoopXQuotaDecision,
    fence: CoordinatorFence,
    turnInstanceId: string,
  ): boolean {
    return decision.turnInstanceId === turnInstanceId
      && decision.goalId === fence.goalId
      && decision.agentId === fence.agentId
      && sameBinding(decision.binding, fence)
  }

  private failAttempt(
    state: DriverState,
    fence: CoordinatorFence,
    signal: AbortSignal,
    topLevel: CoordinatorTopLevelOperation,
    result: Extract<LoopXResult<unknown>, { readonly ok: false }>,
    application: 'yes' | 'no' | 'unknown',
  ): void {
    if (signal.aborted || isCoordinatorCancellation(result)
      || !this.coordinators.isCurrent(fence)) {
      topLevel.cancel()
      return
    }
    topLevel.fail()
    const session = sessionRef(state.agent)
    const snapshot = this.coordinators.snapshot(session)
    if (application !== 'no' || result.error.outcomeUncertain
      || !result.error.retryable || snapshot?.automaticFollowupSuppressed === true) return
    const retryFence = this.coordinators.fence(session)
    if (retryFence !== undefined) this.schedule(state, retryFence, FAIL_CLOSED_RETRY_MS)
  }

  private queueAutomatic(state: DriverState, fence: CoordinatorFence, body: string): void {
    if (!this.eligible(state, fence)) return
    const message = createAutomaticMessage(body)
    const reservation: AutomaticReservation = {
      messageId: message.id,
      content: message.content,
      fence,
      phase: 'reserved',
    }
    state.reservation = reservation
    try {
      state.agent.followup(message)
      if (state.reservation === reservation && reservation.phase === 'reserved') {
        reservation.phase = 'queued'
      }
    } catch {
      this.retireReservation(state)
      this.warn('dsh-loopx-driver: automatic follow-up admission failed')
    }
  }

  private schedule(state: DriverState, fence: CoordinatorFence, delayMs: number): void {
    if (!this.eligible(state, fence) || state.timer !== undefined) return
    let scheduled: ScheduledEvaluation
    const handle = this.clock.setTimeout(() => {
      if (state.timer !== scheduled) return
      state.timer = undefined
      if (this.coordinators.isCurrent(scheduled.fence)) this.requestEvaluation(state)
    }, delayMs)
    scheduled = { handle, fence }
    state.timer = scheduled
  }

  private cancelUnadmitted(state: DriverState): void {
    state.requested = false
    state.controller?.abort(new Error('LoopX automatic attempt fenced'))
    state.controller = undefined
    if (state.timer !== undefined) {
      this.clock.clearTimeout(state.timer.handle)
      state.timer = undefined
    }
    const reservation = state.reservation
    if (reservation === undefined
      || reservation.phase === 'claimed' || reservation.phase === 'entered') return
    state.agent.inbox.remove(reservation.messageId)
    this.retireReservation(state)
  }

  private retireReservation(state: DriverState): void {
    const reservation = state.reservation
    if (reservation === undefined) return
    reservation.phase = 'retired'
    state.reservation = undefined
  }

  /** Requeue non-plugin claimed input through a waking boundary before rejection. */
  private restoreAndWake(agent: Agent, messages: UserMessage[]): void {
    for (const message of messages) {
      if (isDriverSource(message)) continue
      if (agent.inbox.nextStep.some(candidate => candidate.id === message.id)
        || agent.inbox.nextTurn.some(candidate => candidate.id === message.id)) continue
      agent.send(message, 'next-step', true)
    }
  }

  private track(operation: Promise<void>): void {
    this.operations.add(operation)
    void operation.then(
      () => { this.operations.delete(operation) },
      () => { this.operations.delete(operation) },
    )
  }
}

/** Install the Host-plane continuation and command-boundary listeners. */
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
    ctx.on('agent/inbox/inserted', ({ agent, message }) => driver.onInboxInserted(agent, message))
    ctx.on('agent/inbox/claimed', ({ agent, message }) => driver.onInboxClaimed(agent, message))
    ctx.on('agent/inbox/discarded', ({ agent, message }) => driver.onInboxDiscarded(agent, message))
    ctx.on('agent/pre-step', ({ agent, messages, signal }, next) =>
      driver.onPreStep(agent, messages, signal, next))
    ctx.on('session/event', (session, event) => {
      const agent = ctx.agents.get(session.id)
      if (agent?.session === session) driver.onSessionEvent(agent, event)
    })
    ctx.on('session/disposed', session => { driver.onSessionDisposed(session) })

    for (const agent of ctx.agents.list()) driver.observeAgent(agent)
    yield () => driver.dispose()
  }, 'dsh-loopx-driver lifecycle')
}
