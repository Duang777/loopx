import type {
  LoopXApplication,
  LoopXAppliedSubEffect,
  LoopXFailure,
  LoopXFailureCode,
  LoopXResult,
} from './types.ts'

export interface LoopXFailureOptions {
  readonly operation?: string
  readonly retryable?: boolean
  readonly outcomeUncertain?: boolean
}

/** Stable failure boundary that never carries CLI output, argv, environment, or locators. */
export function failure(
  code: LoopXFailureCode,
  message: string,
  options: LoopXFailureOptions = {},
): LoopXFailure {
  return Object.freeze({
    code,
    message,
    ...(options.operation === undefined ? {} : { operation: options.operation }),
    retryable: options.retryable ?? false,
    outcomeUncertain: options.outcomeUncertain ?? false,
  })
}

export function rejected<T>(
  error: LoopXFailure,
  application: LoopXApplication = error.outcomeUncertain ? 'unknown' : 'no',
  subEffects?: readonly LoopXAppliedSubEffect[],
): LoopXResult<T> {
  return Object.freeze({
    ok: false,
    error,
    application,
    ...(subEffects === undefined ? {} : { subEffects: Object.freeze([...subEffects]) }),
  })
}

export function success<T>(
  value: T,
  application: LoopXApplication = 'no',
  subEffects?: readonly LoopXAppliedSubEffect[],
): LoopXResult<T> {
  return Object.freeze({
    ok: true,
    value,
    application,
    ...(subEffects === undefined ? {} : { subEffects: Object.freeze([...subEffects]) }),
  })
}

/** Render a locator only as a non-reversible presence label. */
export function locatorLabel(value: string | undefined): 'configured' | 'session' | 'unavailable' {
  if (value === undefined) return 'unavailable'
  return value.length > 0 ? 'configured' : 'session'
}
