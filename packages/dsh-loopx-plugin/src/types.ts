/** Public Host authority and receipt contracts shared by the plugin surfaces. */

export const LOOPX_HOST_SURFACE = 'dsh' as const

export interface LoopXSessionIdentity {
  readonly createdAt: number
  readonly cwd?: string | undefined
}

/** `session` is the exact live DSH Session object and is never serialized. */
export interface LoopXSessionRef {
  readonly id: string
  readonly session: object
  readonly identity: LoopXSessionIdentity
}

export interface LoopXGoalAgentRef {
  readonly goalId: string
  readonly agentId: string
}

interface LoopXHostThreadBindingBase {
  readonly schemaVersion: 'loopx_host_thread_binding_v1'
  readonly hostSurface: typeof LOOPX_HOST_SURFACE
  readonly threadId: string
  readonly revision: number
}

export interface LoopXBoundHostThreadBindingV1 extends LoopXHostThreadBindingBase {
  readonly state: 'bound'
  readonly target: LoopXGoalAgentRef
}

export interface LoopXUnboundHostThreadBindingV1 extends LoopXHostThreadBindingBase {
  readonly state: 'unbound'
}

export type LoopXHostThreadBindingV1 =
  | LoopXBoundHostThreadBindingV1
  | LoopXUnboundHostThreadBindingV1

export type LoopXFailureCode =
  | 'LOOPX_SESSION_NOT_BOUND'
  | 'LOOPX_SESSION_LIFECYCLE_MISMATCH'
  | 'LOOPX_IDENTITY_CONFLICT'
  | 'LOOPX_SELECTION_REQUIRED'
  | 'LOOPX_SWITCH_CONFIRMATION_INVALID'
  | 'LOOPX_INVALID_REQUEST'
  | 'LOOPX_INVALID_TARGET'
  | 'LOOPX_BINDING_NOT_FOUND'
  | 'LOOPX_REVISION_CONFLICT'
  | 'LOOPX_BINDING_HOME_UNINITIALIZED'
  | 'LOOPX_BINDING_HOME_UNAVAILABLE'
  | 'LOOPX_AUTHORITY_CORRUPT'
  | 'LOOPX_AUTHORITY_UNHEALTHY'
  | 'LOOPX_AUTHORITY_EXHAUSTED'
  | 'LOOPX_DRIVER_NOT_ARMED'
  | 'LOOPX_FOREIGN_COMMAND_ACTIVE'
  | 'LOOPX_AUTOMATION_SUPPRESSED'
  | 'LOOPX_SCHEMA_UNSUPPORTED'
  | 'LOOPX_CLI_NOT_FOUND'
  | 'LOOPX_CLI_TIMEOUT'
  | 'LOOPX_CLI_ABORTED'
  | 'LOOPX_CLI_OUTPUT_LIMIT'
  | 'LOOPX_CLI_FAILED'
  | 'LOOPX_READBACK_FAILED'
  | 'LOOPX_REGISTRY_INTEGRITY'
  | 'LOOPX_SERVICE_CLOSED'

export interface LoopXFailure {
  readonly code: LoopXFailureCode
  readonly message: string
  readonly operation?: string
  readonly retryable: boolean
  readonly outcomeUncertain: boolean
}

export interface LoopXAppliedSubEffect {
  readonly operation: string
  readonly application: 'yes'
  readonly target?: LoopXGoalAgentRef | undefined
}

export type LoopXResult<T> =
  | {
    readonly ok: true
    readonly value: T
    readonly application: LoopXApplication
    readonly subEffects?: readonly LoopXAppliedSubEffect[] | undefined
  }
  | {
    readonly ok: false
    readonly error: LoopXFailure
    readonly application: LoopXApplication
    readonly subEffects?: readonly LoopXAppliedSubEffect[] | undefined
  }

export type LoopXReceiptKind = 'typed_intent' | 'operation_result' | 'semantic_request'
export type LoopXExecution = 'succeeded' | 'rejected' | 'indeterminate' | 'not_attempted'
export type LoopXApplication = 'yes' | 'no' | 'unknown'
export type LoopXDelivery = 'steered' | 'followup_queued' | 'failed' | 'not_needed'
export type LoopXRecoveryAction =
  | 'none'
  | 'retry_same_tool'
  | 'read_authority_then_decide'
  | 'correct_request'
  | 'ask_user'
  | 'stop'

export interface LoopXOperationReceipt {
  readonly schemaVersion: 'dsh_loopx_operation_receipt_v1'
  readonly kind: LoopXReceiptKind
  readonly operation: string
  readonly request?: string | undefined
  readonly arguments?: Readonly<Record<string, unknown>> | undefined
  readonly execution: LoopXExecution
  readonly application: LoopXApplication
  readonly delivery: LoopXDelivery
  readonly recovery: LoopXRecoveryAction
  readonly value?: Readonly<Record<string, unknown>> | undefined
  readonly error?: LoopXFailure | undefined
  readonly subEffects?: readonly LoopXAppliedSubEffect[] | undefined
}

export interface LoopXIdentitySelectionChoice {
  readonly agentId?: string | undefined
  readonly goalId?: string | undefined
}

export interface LoopXIdentitySelection {
  readonly kind: 'agent' | 'goal'
  readonly defaultAction: string
  readonly choices: readonly LoopXIdentitySelectionChoice[]
  readonly freshAgentSuggestedId?: string | undefined
}

export interface LoopXStartOptions {
  readonly switchConfirmation?: string | undefined
}

export interface LoopXPlanningCheckpoint {
  readonly schemaVersion: 'dsh_loopx_planning_checkpoint_v1'
  readonly goalId: string
  readonly agentId: string
  readonly goalText: string
  readonly planner: {
    readonly defaultProfile: string
    readonly profileSelection: string
    readonly openEndedProductDirection: {
      readonly suggestedItemsMin: number
      readonly suggestedItemsMax: number
      readonly intent: string
    }
    readonly clearBoundedProblem: {
      readonly itemCountPolicy: string
      readonly mayReuseCurrentTodoWhenItAlreadyRepresentsThePlan: boolean
      readonly intent: string
    }
    readonly allowedPriorities: readonly ['P0', 'P1', 'P2']
    readonly defaultRole: 'agent'
    readonly defaultTaskClass: 'advancement_task'
    readonly requiredFields: readonly string[]
    readonly publicSafeOnly: true
    readonly budgetPolicy: string
    readonly fineGrainedPlanHorizon?: string | undefined
  }
  readonly writeback: {
    readonly todoTool: 'loopx_todo_add'
    readonly minimumTodos: 1
    readonly maximumTodos: number
    readonly ordering: 'priority_then_tool_call_order'
    readonly activationTool: 'loopx_goal_activate'
    readonly activationArguments: LoopXGoalAgentRef
  }
  readonly stopConditions: readonly string[]
  readonly forbidden: readonly [
    'shell_or_bash',
    'raw_loopx_cli',
    'registry_edit',
    'ctx.goals',
  ]
}

export interface LoopXSwitchRequired {
  readonly kind: 'switch_required'
  readonly confirmationToken: string
  readonly requiresUserConfirmation: true
  readonly expiresAt: number
  readonly expectedRevision: number
  readonly current: LoopXGoalAgentRef
  readonly requested: {
    readonly operation: 'start' | 'attach'
    readonly goalId?: string | undefined
    readonly agentId?: string | undefined
    readonly newPeer?: true | undefined
  }
}

export type LoopXStartValue =
  | {
    readonly kind: 'planning'
    readonly binding: LoopXBoundHostThreadBindingV1
    readonly planning: LoopXPlanningCheckpoint
    readonly modelCheckpoint: string
  }
  | LoopXSwitchRequired

export interface LoopXAttachRequest {
  readonly goalId: string
  readonly agentId?: string | undefined
  readonly newPeer?: boolean | undefined
  readonly switchConfirmation?: string | undefined
}

export type LoopXAttachValue =
  | {
    readonly kind: 'selection_required'
    readonly goalId: string
    readonly selection: LoopXIdentitySelection
  }
  | { readonly kind: 'attached'; readonly binding: LoopXBoundHostThreadBindingV1 }
  | LoopXSwitchRequired

export interface LoopXHostStatus {
  readonly binarySource: 'config' | 'environment' | 'path'
  readonly binding?: LoopXHostThreadBindingV1 | undefined
  readonly activation: 'armed' | 'disarmed'
  readonly automaticFollowupSuppressed: boolean
}

export interface LoopXStatusAttentionItem {
  readonly goalId: string
  readonly status?: string | undefined
  readonly severity?: string | undefined
  readonly lifecyclePhase?: string | undefined
}

export interface LoopXStatusAuthority {
  readonly schemaVersion: 'loopx_status_projection_v1'
  readonly ok: true
  readonly goalId: string
  readonly attention: readonly LoopXStatusAttentionItem[]
}

export interface LoopXStatusValue {
  readonly host: LoopXHostStatus
  readonly authority?: LoopXStatusAuthority | undefined
}

export interface LoopXTodoClaimRequest {
  readonly todoId: string
  readonly role?: 'user' | 'agent' | undefined
}

export interface LoopXTodoAddRequest {
  readonly text: string
  readonly priority: 'P0' | 'P1' | 'P2'
  readonly role?: 'user' | 'agent' | undefined
  readonly actionKind?: string | undefined
  readonly targetKey?: string | undefined
}

export interface LoopXTodoAddValue {
  readonly todoId: string
  readonly status: 'open'
  readonly priority: 'P0' | 'P1' | 'P2'
  readonly role: 'user' | 'agent'
  readonly payload: LoopXTodoAddAuthority
}

export interface LoopXTodoAddAuthority {
  readonly schemaVersion: 'loopx_todo_projection_v1'
  readonly goalId: string
  readonly todoId: string
  readonly status: 'open'
  readonly role: 'user' | 'agent'
  readonly taskClass: string
  readonly actionKind: string
  readonly added: boolean
  readonly alreadyExists: boolean
}

export interface LoopXTodoUpdateRequest {
  readonly todoId: string
  readonly status?: 'open' | 'done' | 'blocked' | 'deferred' | undefined
  readonly note?: string | undefined
  readonly evidence?: string | undefined
  readonly reason?: string | undefined
  readonly taskClass?: 'advancement_task' | 'continuous_monitor' | 'user_gate' | 'user_action' | 'blocker' | undefined
  readonly clearClaim?: boolean | undefined
}

export interface LoopXTodoCompleteRequest {
  readonly todoId: string
  readonly note?: string | undefined
  readonly evidence?: string | undefined
  readonly noFollowUp?: boolean | undefined
  readonly turnInstanceId?: string | undefined
  readonly taskLeaseIdempotencyKey?: string | undefined
  readonly taskLeaseExpectedVersion?: number | undefined
}

export interface LoopXTodoMutationValue {
  readonly todoId: string
  readonly status?: string | undefined
  readonly payload: LoopXTodoMutationAuthority
}

export interface LoopXTodoMutationAuthority {
  readonly schemaVersion: 'loopx_todo_projection_v1'
  readonly goalId: string
  readonly todoId: string
  readonly status?: string | undefined
  readonly changed?: boolean | undefined
  readonly claimedBy?: string | undefined
  readonly taskClass?: string | undefined
  readonly settlementResult?: string | undefined
}

export interface LoopXSchedulerHint {
  readonly action: string
  readonly cadenceClass: string
  readonly resetToken?: string | undefined
  readonly recommendedIntervalMinutes?: number | undefined
  readonly unchangedPollLimit?: number | undefined
}

export interface LoopXQuotaDecision {
  readonly binding: LoopXBoundHostThreadBindingV1
  readonly goalId: string
  readonly agentId: string
  readonly turnInstanceId: string
  readonly shouldRun: boolean
  readonly effectiveAction: string
  readonly schedulerHint: LoopXSchedulerHint
  readonly terminalNoFollowup: boolean
  readonly payload: LoopXQuotaAuthority
}

export interface LoopXQuotaAuthority {
  readonly schemaVersion: 'loopx_quota_projection_v1'
  readonly goalId: string
  readonly shouldRun: boolean
  readonly effectiveAction: string
  readonly decision?: string | undefined
  readonly state?: string | undefined
}

export interface LoopXTaskBody {
  readonly binding: LoopXBoundHostThreadBindingV1
  readonly body: string
}

export interface LoopXPauseValue {
  readonly paused: true
  readonly binding?: LoopXHostThreadBindingV1 | undefined
}

export interface LoopXDetachValue {
  readonly detached: true
  readonly binding: LoopXUnboundHostThreadBindingV1
}

export interface LoopXServiceApi {
  resolveBinding(session: LoopXSessionRef, signal?: AbortSignal): Promise<LoopXResult<LoopXHostThreadBindingV1>>
  start(session: LoopXSessionRef, goalText: string, signal?: AbortSignal, options?: LoopXStartOptions): Promise<LoopXResult<LoopXStartValue>>
  attach(session: LoopXSessionRef, request: LoopXAttachRequest, signal?: AbortSignal): Promise<LoopXResult<LoopXAttachValue>>
  activate(session: LoopXSessionRef, goalId: string, agentId?: string, signal?: AbortSignal): Promise<LoopXResult<LoopXBoundHostThreadBindingV1>>
  status(session: LoopXSessionRef, signal?: AbortSignal): Promise<LoopXResult<LoopXStatusValue>>
  pause(session: LoopXSessionRef): Promise<LoopXResult<LoopXPauseValue>>
  resume(session: LoopXSessionRef, signal?: AbortSignal): Promise<LoopXResult<LoopXBoundHostThreadBindingV1>>
  detach(session: LoopXSessionRef, signal?: AbortSignal): Promise<LoopXResult<LoopXDetachValue>>
  todoAdd(session: LoopXSessionRef, request: LoopXTodoAddRequest, signal?: AbortSignal): Promise<LoopXResult<LoopXTodoAddValue>>
  todoClaim(session: LoopXSessionRef, request: LoopXTodoClaimRequest, signal?: AbortSignal): Promise<LoopXResult<LoopXTodoMutationValue>>
  todoUpdate(session: LoopXSessionRef, request: LoopXTodoUpdateRequest, signal?: AbortSignal): Promise<LoopXResult<LoopXTodoMutationValue>>
  todoComplete(session: LoopXSessionRef, request: LoopXTodoCompleteRequest, signal?: AbortSignal): Promise<LoopXResult<LoopXTodoMutationValue>>
  quotaShouldRun(session: LoopXSessionRef, turnInstanceId: string, signal?: AbortSignal): Promise<LoopXResult<LoopXQuotaDecision>>
  taskBody(session: LoopXSessionRef, refresh?: boolean, signal?: AbortSignal): Promise<LoopXResult<LoopXTaskBody>>
  disposeSession(session: LoopXSessionRef): Promise<void>
}
