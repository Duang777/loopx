import { randomUUID } from 'node:crypto'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type {
  LoopXBoundHostThreadBindingV1,
  LoopXHostThreadBindingV1,
  LoopXResult,
  LoopXSessionRef,
} from './types.ts'

export const LOOPX_FAILURE_SUPPRESSION_THRESHOLD = 8

export interface LoopXBindingHome {
  /** Canonical process-local identity. Never include this value in a receipt. */
  readonly key: string
  readonly cwd: string
  readonly runtimeRoot?: string | undefined
}

export interface CoordinatorFence {
  readonly sessionObject: object
  readonly pluginInstanceIdentity: object
  readonly bindingHome: string
  readonly threadId: string
  readonly bindingRevision: number
  readonly goalId: string
  readonly agentId: string
  readonly activationEpoch: number
}

export interface CoordinatorSnapshot {
  readonly activation: 'armed' | 'disarmed'
  readonly activationEpoch: number
  readonly barred: boolean
  readonly foreignLatched: boolean
  readonly failureCount: number
  readonly automaticFollowupSuppressed: boolean
  readonly observedBinding?: LoopXHostThreadBindingV1 | undefined
  readonly bindingHome?: LoopXBindingHome | undefined
  readonly planningBody?: string | undefined
  readonly taskBody?: string | undefined
}

export type CoordinatorEventKind =
  | 'armed'
  | 'invalidated'
  | 'barrier_opened'
  | 'barrier_released'
  | 'foreign_command'
  | 'suppressed'
  | 'recovered'
  | 'disposed'

export interface CoordinatorEvent {
  readonly kind: CoordinatorEventKind
  readonly sessionObject: object
  readonly snapshot: CoordinatorSnapshot
}

export interface CoordinatorArmOptions {
  readonly planningBody?: string | undefined
  readonly taskBody?: string | undefined
}

export type CoordinatorOutcome = 'success' | 'failure' | 'cancelled'

export interface CoordinatorTopLevelOperation {
  succeed(): void
  fail(): void
  cancel(): void
}

export type IdleAdmission<T> =
  | { readonly route: 'running' }
  | { readonly route: 'idle'; readonly value: T }

/** Internal failure-counter filter shared by command, tools, and Driver. */
export function isCoordinatorCancellation(result: LoopXResult<unknown>): boolean {
  if (result.ok) return false
  return result.error.code === 'LOOPX_DRIVER_NOT_ARMED'
    || result.error.code === 'LOOPX_FOREIGN_COMMAND_ACTIVE'
    || result.error.code === 'LOOPX_AUTOMATION_SUPPRESSED'
    || result.error.code === 'LOOPX_REVISION_CONFLICT'
    || result.error.code === 'LOOPX_SESSION_LIFECYCLE_MISMATCH'
    || result.error.code === 'LOOPX_CLI_ABORTED'
    || result.error.code === 'LOOPX_SERVICE_CLOSED'
}

interface CoordinatorState {
  readonly sessionObject: object
  readonly scopeKey: string
  home?: LoopXBindingHome | undefined
  observed?: LoopXHostThreadBindingV1 | undefined
  activation: 'armed' | 'disarmed'
  activationEpoch: number
  planningBody?: string | undefined
  taskBody?: string | undefined
  failureCount: number
  suppressed: boolean
  foreignLatched: boolean
  closed: boolean
  operationTail: Promise<void>
  confirmation?: unknown
}

interface CommandOperation {
  readonly commandId: string
  readonly sessionObject: object
  readonly agentObject: object
  phase: 'provisional' | 'owned' | 'foreign'
  commandDone: boolean
}

export class CoordinatorAdmissionCancelled extends Error {
  constructor() {
    super('LoopX idle admission was fenced')
    this.name = 'CoordinatorAdmissionCancelled'
  }
}

function sameTarget(
  left: LoopXHostThreadBindingV1 | undefined,
  right: LoopXHostThreadBindingV1,
): boolean {
  if (left === undefined || left.state !== right.state) return false
  if (left.threadId !== right.threadId || left.revision !== right.revision) return false
  if (left.state === 'unbound' || right.state === 'unbound') return true
  return left.target.goalId === right.target.goalId
    && left.target.agentId === right.target.agentId
}

function frozenBinding(binding: LoopXHostThreadBindingV1): LoopXHostThreadBindingV1 {
  const base = {
    schemaVersion: 'loopx_host_thread_binding_v1' as const,
    hostSurface: 'dsh' as const,
    threadId: binding.threadId,
    revision: binding.revision,
  }
  return binding.state === 'bound'
    ? Object.freeze({
        ...base,
        state: 'bound' as const,
        target: Object.freeze({ ...binding.target }),
      })
    : Object.freeze({ ...base, state: 'unbound' as const })
}

function abortable(promise: Promise<void>, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signal.reason)
  return new Promise<void>((resolve, reject) => {
    const aborted = (): void => reject(signal.reason)
    signal.addEventListener('abort', aborted, { once: true })
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', aborted))
  })
}

/**
 * The sole process-local owner for Session activation and operation fences.
 * It is constructed once by LoopXService and is intentionally not exported by
 * the package entry point or registered as a Cordis component.
 */
export class CoordinatorRegistry {
  private readonly pluginInstanceIdentity = Object.freeze({})
  private readonly states = new WeakMap<object, CoordinatorState>()
  private readonly liveStates = new Set<CoordinatorState>()
  private readonly commands = new Map<object, Map<string, CommandOperation>>()
  private readonly listeners = new Set<(event: CoordinatorEvent) => void>()
  private closed = false

  constructor(private readonly abortScope: (scopeKey: string) => void = () => {}) {}

  observe(session: LoopXSessionRef, home?: LoopXBindingHome): CoordinatorSnapshot {
    const state = this.stateFor(session.session)
    if (home !== undefined) this.observeHome(state, home)
    return this.snapshotState(state)
  }

  snapshot(session: LoopXSessionRef | object): CoordinatorSnapshot | undefined {
    const object = 'session' in session ? session.session : session
    const state = this.states.get(object)
    return state === undefined ? undefined : this.snapshotState(state)
  }

  observeBinding(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    binding: LoopXHostThreadBindingV1,
  ): CoordinatorSnapshot {
    const state = this.stateFor(session.session)
    const homeChanged = state.home !== undefined && state.home.key !== home.key
    const bindingChanged = !sameTarget(state.observed, binding)
    this.observeHome(state, home)
    state.observed = frozenBinding(binding)
    if (!homeChanged && bindingChanged) this.invalidateState(state, true)
    if (binding.state === 'unbound') {
      state.activation = 'disarmed'
      state.planningBody = undefined
      state.taskBody = undefined
    }
    return this.snapshotState(state)
  }

  arm(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    binding: LoopXBoundHostThreadBindingV1,
    options: CoordinatorArmOptions = {},
  ): CoordinatorFence | undefined {
    const state = this.stateFor(session.session)
    this.observeHome(state, home)
    if (this.hasForeignBarrier(session.session) || state.closed) return undefined
    state.observed = frozenBinding(binding)
    state.activation = 'armed'
    state.foreignLatched = false
    state.activationEpoch += 1
    state.planningBody = options.planningBody
    state.taskBody = options.taskBody
    this.emit(state, 'armed')
    return this.fence(session)
  }

  pause(session: LoopXSessionRef): CoordinatorSnapshot {
    const state = this.stateFor(session.session)
    this.invalidateState(state, true)
    return this.snapshotState(state)
  }

  invalidate(
    session: LoopXSessionRef,
    options: { readonly foreign?: boolean; readonly clearCaches?: boolean } = {},
  ): CoordinatorSnapshot {
    const state = this.stateFor(session.session)
    if (options.foreign === true) state.foreignLatched = true
    this.invalidateState(state, options.clearCaches ?? true)
    return this.snapshotState(state)
  }

  /** Retire unclaimed automatic work without changing explicit activation. */
  advanceEpoch(session: LoopXSessionRef): CoordinatorSnapshot {
    const state = this.stateFor(session.session)
    state.activationEpoch += 1
    this.abortScope(state.scopeKey)
    this.emit(state, 'invalidated')
    return this.snapshotState(state)
  }

  cachePlanningBody(session: LoopXSessionRef, body: string): void {
    const state = this.stateFor(session.session)
    state.planningBody = body
  }

  cacheTaskBody(session: LoopXSessionRef, body: string): void {
    const state = this.stateFor(session.session)
    state.taskBody = body
  }

  scopeKey(session: LoopXSessionRef): string {
    return this.stateFor(session.session).scopeKey
  }

  isClosed(session: LoopXSessionRef): boolean {
    return this.states.get(session.session)?.closed ?? false
  }

  serialize<T>(session: LoopXSessionRef, operation: () => Promise<T>): Promise<T> {
    const state = this.stateFor(session.session)
    if (state.closed || this.closed) return Promise.reject(new CoordinatorAdmissionCancelled())
    const result = state.operationTail.then(() => {
      if (state.closed || this.closed) throw new CoordinatorAdmissionCancelled()
      return operation()
    })
    state.operationTail = result.then(() => undefined, () => undefined)
    return result
  }

  drain(session: LoopXSessionRef): Promise<void> {
    return this.states.get(session.session)?.operationTail ?? Promise.resolve()
  }

  async drainAll(): Promise<void> {
    await Promise.all([...this.liveStates].map(state => state.operationTail))
  }

  setConfirmation(session: LoopXSessionRef, value: unknown): void {
    this.stateFor(session.session).confirmation = value
  }

  confirmation<T>(session: LoopXSessionRef): T | undefined {
    return this.states.get(session.session)?.confirmation as T | undefined
  }

  clearConfirmation(session: LoopXSessionRef): void {
    const state = this.states.get(session.session)
    if (state !== undefined) state.confirmation = undefined
  }

  fence(session: LoopXSessionRef): CoordinatorFence | undefined {
    const state = this.states.get(session.session)
    const binding = state?.observed
    if (state === undefined || state.activation !== 'armed' || state.home === undefined
      || binding?.state !== 'bound' || state.closed) return undefined
    return Object.freeze({
      sessionObject: session.session,
      pluginInstanceIdentity: this.pluginInstanceIdentity,
      bindingHome: state.home.key,
      threadId: binding.threadId,
      bindingRevision: binding.revision,
      goalId: binding.target.goalId,
      agentId: binding.target.agentId,
      activationEpoch: state.activationEpoch,
    })
  }

  isCurrent(fence: CoordinatorFence): boolean {
    const state = this.states.get(fence.sessionObject)
    const binding = state?.observed
    return state !== undefined && !state.closed && state.activation === 'armed'
      && !state.suppressed && !state.foreignLatched && !this.hasBarrier(fence.sessionObject)
      && fence.pluginInstanceIdentity === this.pluginInstanceIdentity
      && state.home?.key === fence.bindingHome
      && state.activationEpoch === fence.activationEpoch
      && binding?.state === 'bound'
      && binding.threadId === fence.threadId
      && binding.revision === fence.bindingRevision
      && binding.target.goalId === fence.goalId
      && binding.target.agentId === fence.agentId
  }

  commandRun(commandId: string, sessionObject: object, agentObject: object): void {
    const bucket = this.commands.get(sessionObject) ?? new Map<string, CommandOperation>()
    if (this.closed || bucket.has(commandId)) return
    const state = this.stateFor(sessionObject)
    if (state.closed) return
    bucket.set(commandId, {
      commandId,
      sessionObject,
      agentObject,
      phase: 'provisional',
      commandDone: false,
    })
    this.commands.set(sessionObject, bucket)
    this.emit(state, 'barrier_opened')
  }

  claimCommand(commandId: string, sessionObject: object, agentObject: object): boolean {
    const operation = this.commands.get(sessionObject)?.get(commandId)
    if (operation === undefined || operation.phase !== 'provisional'
      || operation.sessionObject !== sessionObject || operation.agentObject !== agentObject) return false
    operation.phase = 'owned'
    return true
  }

  classifyUnclaimed(
    commandId: string,
    sessionObject: object,
  ): 'missing' | 'owned' | 'foreign' {
    const operation = this.commands.get(sessionObject)?.get(commandId)
    if (operation === undefined) return 'missing'
    if (operation.phase === 'owned') return 'owned'
    if (operation.phase === 'provisional') {
      operation.phase = 'foreign'
      const state = this.stateFor(operation.sessionObject)
      state.foreignLatched = true
      this.invalidateState(state, true, 'foreign_command')
    }
    return 'foreign'
  }

  commandDone(commandId: string, sessionObject: object): void {
    const operation = this.commands.get(sessionObject)?.get(commandId)
    if (operation === undefined) return
    operation.commandDone = true
    if (operation.phase === 'provisional') this.classifyUnclaimed(commandId, sessionObject)
    if (operation.phase === 'foreign') this.releaseCommand(operation)
  }

  settleOwned(commandId: string, sessionObject: object): void {
    const operation = this.commands.get(sessionObject)?.get(commandId)
    if (operation?.phase !== 'owned') return
    this.releaseCommand(operation)
  }

  hasBarrier(session: LoopXSessionRef | object): boolean {
    const sessionObject = 'session' in session ? session.session : session
    return (this.commands.get(sessionObject)?.size ?? 0) !== 0
  }

  recordOutcome(session: LoopXSessionRef, outcome: CoordinatorOutcome): CoordinatorSnapshot {
    const state = this.stateFor(session.session)
    if (outcome === 'cancelled') return this.snapshotState(state)
    if (outcome === 'success') {
      const recovered = state.failureCount !== 0 || state.suppressed
      state.failureCount = 0
      state.suppressed = false
      if (recovered) this.emit(state, 'recovered')
      return this.snapshotState(state)
    }
    state.failureCount = Math.min(
      LOOPX_FAILURE_SUPPRESSION_THRESHOLD,
      state.failureCount + 1,
    )
    state.activationEpoch += 1
    this.abortScope(state.scopeKey)
    if (state.failureCount === LOOPX_FAILURE_SUPPRESSION_THRESHOLD && !state.suppressed) {
      state.suppressed = true
      this.emit(state, 'suppressed')
    } else {
      this.emit(state, 'invalidated')
    }
    return this.snapshotState(state)
  }

  beginTopLevel(session: LoopXSessionRef): CoordinatorTopLevelOperation {
    let settled = false
    const settle = (outcome: CoordinatorOutcome): void => {
      if (settled) return
      settled = true
      this.recordOutcome(session, outcome)
    }
    return Object.freeze({
      succeed: () => settle('success'),
      fail: () => settle('failure'),
      cancel: () => settle('cancelled'),
    })
  }

  onInvalidated(listener: (event: CoordinatorEvent) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  async admitWhenIdle<T>(
    agent: Agent,
    signal: AbortSignal,
    revalidate: () => boolean | Promise<boolean>,
    task: (signal: AbortSignal) => Promise<T>,
  ): Promise<IdleAdmission<T>> {
    while (true) {
      if (signal.aborted) throw signal.reason
      if (agent.status === 'running') return Object.freeze({ route: 'running' as const })
      let entered = false
      try {
        const value = await agent.runMaintenance(async maintenanceSignal => {
          entered = true
          if (!await revalidate()) throw new CoordinatorAdmissionCancelled()
          return task(maintenanceSignal)
        })
        return Object.freeze({ route: 'idle' as const, value })
      } catch (error) {
        if (entered) throw error
        if (this.agentIsRunning(agent)) return Object.freeze({ route: 'running' as const })
        await abortable(agent.whenIdle(), signal)
        if (!await revalidate()) throw new CoordinatorAdmissionCancelled()
        continue
      }
    }
  }

  drop(session: LoopXSessionRef | object): void {
    const sessionObject = 'session' in session ? session.session : session
    const state = this.states.get(sessionObject)
    if (state === undefined) return
    state.closed = true
    state.activation = 'disarmed'
    state.activationEpoch += 1
    state.planningBody = undefined
    state.taskBody = undefined
    state.confirmation = undefined
    this.commands.delete(sessionObject)
    this.abortScope(state.scopeKey)
    this.emit(state, 'disposed')
    this.liveStates.delete(state)
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    for (const state of [...this.liveStates]) this.drop(state.sessionObject)
    this.commands.clear()
    this.listeners.clear()
  }

  private stateFor(sessionObject: object): CoordinatorState {
    const found = this.states.get(sessionObject)
    if (found !== undefined) return found
    if (this.closed) throw new Error('LoopX coordinator is closed')
    const created: CoordinatorState = {
      sessionObject,
      scopeKey: `dsh-loopx-scope-${randomUUID()}`,
      activation: 'disarmed',
      activationEpoch: 1,
      failureCount: 0,
      suppressed: false,
      foreignLatched: false,
      closed: false,
      operationTail: Promise.resolve(),
    }
    this.states.set(sessionObject, created)
    this.liveStates.add(created)
    return created
  }

  private observeHome(state: CoordinatorState, home: LoopXBindingHome): void {
    if (state.home?.key === home.key) return
    const changed = state.home !== undefined
    state.home = Object.freeze({ ...home })
    if (changed) this.invalidateState(state, true)
  }

  private invalidateState(
    state: CoordinatorState,
    clearCaches: boolean,
    kind: CoordinatorEventKind = 'invalidated',
  ): void {
    state.activation = 'disarmed'
    state.activationEpoch += 1
    if (clearCaches) {
      state.planningBody = undefined
      state.taskBody = undefined
    }
    this.abortScope(state.scopeKey)
    this.emit(state, kind)
  }

  private releaseCommand(operation: CommandOperation): void {
    const bucket = this.commands.get(operation.sessionObject)
    bucket?.delete(operation.commandId)
    if (bucket?.size === 0) this.commands.delete(operation.sessionObject)
    const state = this.states.get(operation.sessionObject)
    if (state !== undefined && !this.hasBarrier(operation.sessionObject)) {
      this.emit(state, 'barrier_released')
    }
  }

  private hasForeignBarrier(sessionObject: object): boolean {
    for (const operation of this.commands.get(sessionObject)?.values() ?? []) {
      if (operation.phase === 'foreign') return true
    }
    return false
  }

  private snapshotState(state: CoordinatorState): CoordinatorSnapshot {
    return Object.freeze({
      activation: state.activation,
      activationEpoch: state.activationEpoch,
      barred: this.hasBarrier(state.sessionObject),
      foreignLatched: state.foreignLatched,
      failureCount: state.failureCount,
      automaticFollowupSuppressed: state.suppressed,
      ...(state.observed === undefined ? {} : { observedBinding: state.observed }),
      ...(state.home === undefined ? {} : { bindingHome: state.home }),
      ...(state.planningBody === undefined ? {} : { planningBody: state.planningBody }),
      ...(state.taskBody === undefined ? {} : { taskBody: state.taskBody }),
    })
  }

  private emit(state: CoordinatorState, kind: CoordinatorEventKind): void {
    const event = Object.freeze({
      kind,
      sessionObject: state.sessionObject,
      snapshot: this.snapshotState(state),
    })
    for (const listener of this.listeners) listener(event)
  }

  private agentIsRunning(agent: Agent): boolean {
    return agent.status === 'running'
  }
}

const serviceCoordinator = Symbol.for('dsh-loopx-plugin.coordinator.v1')

/** Package-internal attachment; the public Service API does not expose it. */
export function installCoordinator(service: object, coordinator: CoordinatorRegistry): void {
  Object.defineProperty(service, serviceCoordinator, {
    value: coordinator,
    configurable: false,
    enumerable: false,
    writable: false,
  })
}

/** Package-internal lookup used by command, tools, and Driver composition. */
export function coordinatorFor(service: object): CoordinatorRegistry {
  const coordinator = (service as Record<symbol, unknown>)[serviceCoordinator]
  if (typeof coordinator !== 'object' || coordinator === null
    || !('snapshot' in coordinator) || !('commandRun' in coordinator)) {
    throw new Error('LoopX coordinator has an incompatible package identity')
  }
  return coordinator as CoordinatorRegistry
}
