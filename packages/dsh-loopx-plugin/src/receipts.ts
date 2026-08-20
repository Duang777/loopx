import { coordinatorFor, isCoordinatorCancellation } from './coordinator.ts'
import type {
  LoopXAttachValue,
  LoopXAppliedSubEffect,
  LoopXFailure,
  LoopXHostThreadBindingV1,
  LoopXOperationReceipt,
  LoopXResult,
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStartValue,
  LoopXStatusValue,
} from './types.ts'

export type ReceiptValue = Readonly<Record<string, unknown>>

function recoveryFor(error: LoopXFailure): LoopXOperationReceipt['recovery'] {
  if (error.outcomeUncertain) return 'read_authority_then_decide'
  if (error.code === 'LOOPX_CLI_ABORTED' || error.code === 'LOOPX_SERVICE_CLOSED') return 'stop'
  if (error.code === 'LOOPX_INVALID_REQUEST'
    || error.code === 'LOOPX_INVALID_TARGET'
    || error.code === 'LOOPX_IDENTITY_CONFLICT'
    || error.code === 'LOOPX_SWITCH_CONFIRMATION_INVALID'
    || error.code === 'LOOPX_REVISION_CONFLICT') return 'correct_request'
  return error.retryable ? 'retry_same_tool' : 'ask_user'
}

function safeSubEffects(
  effects: readonly LoopXAppliedSubEffect[],
): readonly LoopXAppliedSubEffect[] {
  return Object.freeze(effects.map(effect => Object.freeze({
    operation: effect.operation,
    application: effect.application,
    ...(effect.target === undefined ? {} : { target: Object.freeze({ ...effect.target }) }),
  })))
}

export function unexpectedFailure(operation: string): LoopXFailure {
  return Object.freeze({
    code: 'LOOPX_CLI_FAILED',
    message: 'The LoopX operation could not be completed.',
    operation,
    retryable: false,
    outcomeUncertain: false,
  })
}

export function failureReceipt(
  operation: string,
  error: LoopXFailure,
  application: LoopXOperationReceipt['application'] = error.outcomeUncertain ? 'unknown' : 'no',
  subEffects?: readonly LoopXAppliedSubEffect[],
): LoopXOperationReceipt {
  return Object.freeze({
    schemaVersion: 'dsh_loopx_operation_receipt_v1',
    kind: 'operation_result',
    operation,
    execution: error.outcomeUncertain || application === 'unknown' ? 'indeterminate' : 'rejected',
    application,
    delivery: 'not_needed',
    recovery: application === 'yes' ? 'read_authority_then_decide' : recoveryFor(error),
    error: Object.freeze({ ...error }),
    ...(subEffects === undefined || subEffects.length === 0
      ? {}
      : { subEffects: safeSubEffects(subEffects) }),
  })
}

export function successReceipt(
  operation: string,
  application: LoopXOperationReceipt['application'],
  value: ReceiptValue,
  subEffects?: readonly LoopXAppliedSubEffect[],
): LoopXOperationReceipt {
  return Object.freeze({
    schemaVersion: 'dsh_loopx_operation_receipt_v1',
    kind: 'operation_result',
    operation,
    execution: 'succeeded',
    application,
    delivery: 'not_needed',
    recovery: 'none',
    value: Object.freeze(value),
    ...(subEffects === undefined || subEffects.length === 0
      ? {}
      : { subEffects: safeSubEffects(subEffects) }),
  })
}

export async function serviceOperationReceipt<T>(
  service: LoopXServiceApi,
  session: LoopXSessionRef,
  signal: AbortSignal,
  operation: string,
  invoke: () => Promise<LoopXResult<T>>,
  project: (value: T) => ReceiptValue,
): Promise<LoopXOperationReceipt> {
  const topLevel = coordinatorFor(service).beginTopLevel(session)
  let result: LoopXResult<T>
  try {
    result = await invoke()
  } catch {
    if (signal.aborted) topLevel.cancel()
    else topLevel.fail()
    return failureReceipt(operation, unexpectedFailure(operation))
  }
  if (!result.ok) {
    if (signal.aborted || isCoordinatorCancellation(result)) topLevel.cancel()
    else topLevel.fail()
    return failureReceipt(operation, result.error, result.application, result.subEffects)
  }
  topLevel.succeed()
  return successReceipt(operation, result.application, project(result.value), result.subEffects)
}

export function safeBinding(binding: LoopXHostThreadBindingV1): ReceiptValue {
  const base = {
    schemaVersion: binding.schemaVersion,
    hostSurface: binding.hostSurface,
    threadId: binding.threadId,
    revision: binding.revision,
    state: binding.state,
  }
  return binding.state === 'bound' ? { ...base, target: { ...binding.target } } : base
}

export function safeStatus(status: LoopXStatusValue): ReceiptValue {
  const authority = status.authority
  return {
    host: {
      binarySource: status.host.binarySource,
      activation: status.host.activation,
      automaticFollowupSuppressed: status.host.automaticFollowupSuppressed,
      binding: status.host.binding === undefined ? null : safeBinding(status.host.binding),
    },
    authority: authority === undefined ? null : {
      schemaVersion: authority.schemaVersion,
      ok: authority.ok,
      goalId: authority.goalId,
      attention: authority.attention.map(item => ({
        goalId: item.goalId,
        ...(item.status === undefined ? {} : { status: item.status }),
        ...(item.severity === undefined ? {} : { severity: item.severity }),
        ...(item.lifecyclePhase === undefined ? {} : { lifecyclePhase: item.lifecyclePhase }),
      })),
    },
  }
}

function safeSwitch(
  value: Extract<LoopXAttachValue | LoopXStartValue, { kind: 'switch_required' }>,
): ReceiptValue {
  const requested = value.requested
  return {
    kind: value.kind,
    confirmationToken: value.confirmationToken,
    requiresUserConfirmation: value.requiresUserConfirmation,
    expiresAt: value.expiresAt,
    expectedRevision: value.expectedRevision,
    current: { ...value.current },
    requested: {
      operation: requested.operation,
      ...(requested.goalId === undefined ? {} : { goalId: requested.goalId }),
      ...(requested.agentId === undefined ? {} : { agentId: requested.agentId }),
      ...(requested.newPeer === true ? { newPeer: true } : {}),
    },
  }
}

export function safeStart(value: LoopXStartValue): ReceiptValue {
  return value.kind === 'planning'
    ? {
        kind: value.kind,
        binding: safeBinding(value.binding),
        planning: value.planning,
        modelCheckpoint: value.modelCheckpoint,
      }
    : safeSwitch(value)
}

export function safeAttach(value: LoopXAttachValue): ReceiptValue {
  if (value.kind === 'attached') return { kind: value.kind, binding: safeBinding(value.binding) }
  if (value.kind === 'switch_required') return safeSwitch(value)
  return {
    kind: value.kind,
    goalId: value.goalId,
    selection: {
      kind: value.selection.kind,
      defaultAction: value.selection.defaultAction,
      choices: value.selection.choices.map(choice => ({
        ...(choice.goalId === undefined ? {} : { goalId: choice.goalId }),
        ...(choice.agentId === undefined ? {} : { agentId: choice.agentId }),
      })),
      ...(value.selection.freshAgentSuggestedId === undefined
        ? {}
        : { freshAgentSuggestedId: value.selection.freshAgentSuggestedId }),
    },
  }
}
