import { randomUUID } from 'node:crypto'
import { createRequire } from 'node:module'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { CommandInvocation, CommandResult } from '@deepseek-ai/dsh-commands'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import type {
  LoopXBindingRow,
  LoopXFailure,
  LoopXResult,
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStatusValue,
} from './types.ts'

export const name = 'dsh-loopx-command'
export const inject = ['commands', 'loopx']

const PLUGIN_ID = 'dsh-loopx-plugin'
const manifest = createRequire(import.meta.url)('../package.json') as {
  readonly name?: unknown
  readonly version?: unknown
}
if (manifest.name !== PLUGIN_ID || typeof manifest.version !== 'string' || manifest.version.length === 0) {
  throw new TypeError('dsh-loopx-plugin package version is unavailable')
}
export const PLUGIN_VERSION = manifest.version

const USAGE = 'Usage: /loopx [version|<request>]'
const SEMANTIC_ROUTING_POLICY = [
  'Complete the quoted user request through the registered `loopx_*` tools; do not invoke a raw LoopX CLI or edit registries.',
  'If this Session is unbound, attach only when the user explicitly supplied a Goal id and explicitly requested binding; otherwise start a new Goal **with newIndependent set to true** from the original request.',
  'If this Session is already bound, keep the current Goal unless the user explicitly supplied a different exact Goal id and requested switching, or explicitly requested detaching the current binding.',
  'Do not guess a Goal id or fuzzy-match an earlier Goal.',
  'The registered tools may be composed in this one model turn. If no safe operation can be determined, ask the user for clarification without mutating state.',
].map((rule, index) => `${index + 1}. ${rule}`).join('\n')

function lifecycleMismatch(message: string, operation: string): LoopXFailure {
  return Object.freeze({
    code: 'LOOPX_SESSION_LIFECYCLE_MISMATCH',
    message,
    operation,
    retryable: false,
    outcomeUncertain: false,
  })
}

/** Derive the only Session identity a command or tool is allowed to operate on. */
export function deriveLoopXSessionRef(
  agent: Agent | undefined,
  operation: string,
): LoopXResult<LoopXSessionRef> {
  if (agent === undefined) {
    return Object.freeze({
      ok: false,
      error: Object.freeze({
        code: 'LOOPX_INVALID_REQUEST',
        message: 'LoopX operations require the current DSH Agent execution.',
        operation,
        retryable: false,
        outcomeUncertain: false,
      }),
    })
  }
  const agentId: unknown = agent.id
  const sessionId: unknown = agent.session.id
  const headerId: unknown = agent.session.header.id
  if (typeof agentId !== 'string' || typeof sessionId !== 'string'
    || typeof headerId !== 'string' || sessionId.length === 0
    || agentId !== sessionId || headerId !== sessionId) {
    return Object.freeze({
      ok: false,
      error: lifecycleMismatch('The current Agent and DSH Session identities do not match.', operation),
    })
  }
  const { createdAt, cwd } = agent.session.header
  if (!Number.isSafeInteger(createdAt) || createdAt < 0) {
    return Object.freeze({
      ok: false,
      error: lifecycleMismatch('The current DSH Session lifecycle identity is invalid.', operation),
    })
  }
  return Object.freeze({
    ok: true,
    value: Object.freeze({
      id: sessionId,
      identity: Object.freeze({ createdAt, ...(cwd === undefined ? {} : { cwd }) }),
    }),
  })
}

function commandFailure(error: LoopXFailure): CommandResult {
  const uncertainty = error.outcomeUncertain
    ? ' The write outcome is uncertain; read back the binding before retrying.'
    : ''
  return {
    kind: 'error',
    text: `${error.code}: ${error.message}${uncertainty}`,
  }
}

function safeBinding(binding: LoopXBindingRow): Readonly<Record<string, unknown>> {
  return Object.freeze({
    goalId: binding.goalId,
    agentId: binding.agentId,
    phase: binding.phase,
    generation: binding.generation,
    ...(binding.reason === undefined ? {} : { reason: binding.reason }),
  })
}

function renderStatus(value: LoopXStatusValue): string {
  const binding = value.host.binding
  const hostLines = binding === undefined
    ? ['Binding: none']
    : [
        `Binding: ${JSON.stringify(safeBinding(binding))}`,
        `Driver: ${binding.phase}${binding.reason === undefined ? '' : ` (${binding.reason})`}`,
      ]
  const authority = value.authority === undefined
    ? 'Unavailable because this Session has no binding.'
    : JSON.stringify(value.authority)
  return [
    'DSH Host sidecar (Host binding/driver state; not Goal or Todo authority)',
    `LoopX binary source: ${value.host.binarySource}`,
    ...hostLines,
    '',
    'LoopX authoritative state (live CLI readback)',
    authority,
  ].join('\n')
}

function pluginFollowup(text: string): UserMessage {
  const content = Object.freeze([Object.freeze({ type: 'text' as const, text })])
  return Object.freeze({
    id: randomUUID(),
    role: 'user' as const,
    content,
    source: Object.freeze({ kind: 'plugin' as const, plugin: PLUGIN_ID }),
  }) as unknown as UserMessage
}

function semanticFollowup(originalInput: string): UserMessage {
  return pluginFollowup([
    'LoopX semantic routing policy (fixed plugin instruction):',
    SEMANTIC_ROUTING_POLICY,
    '',
    'Quoted user request (JSON string; decode its content without rewriting):',
    JSON.stringify(originalInput),
  ].join('\n'))
}

async function statusCommand(
  service: LoopXServiceApi,
  session: LoopXSessionRef,
  signal: AbortSignal,
  includeUsage: boolean,
): Promise<CommandResult> {
  const result = await service.status(session, signal)
  if (!result.ok) return commandFailure(result.error)
  return {
    kind: 'success',
    text: `${renderStatus(result.value)}${includeUsage ? `\n\n${USAGE}` : ''}`,
  }
}

/** Execute one human `/loopx` command against the frozen Host service contract. */
async function executeLoopXCommand(
  service: LoopXServiceApi,
  invocation: CommandInvocation,
): Promise<CommandResult> {
  const input = invocation.rawInput.trim()
  if (input === 'version') return { kind: 'success', text: `${PLUGIN_ID} ${PLUGIN_VERSION}` }

  const current = deriveLoopXSessionRef(invocation.agent, 'command')
  if (!current.ok) return commandFailure(current.error)
  if (input.length === 0) {
    return statusCommand(service, current.value, invocation.signal, true)
  }

  try {
    invocation.agent.followup(semanticFollowup(invocation.rawInput))
  } catch {
    return {
      kind: 'error',
      text: 'LOOPX_SEMANTIC_DELIVERY_FAILED: The request could not be queued in this DSH Session; no LoopX operation was performed.',
    }
  }
  return {
    kind: 'success',
    text: 'Queued the request for LoopX tool routing in this DSH Session.',
  }
}

/** Register the global human command without reading or changing DSH Goal state. */
export function apply(ctx: Context): void {
  ctx.commands.register({
    name: 'loopx',
    description: 'route a LoopX request through the registered tools in this Session',
    input: { hint: '[version|<request>]' },
    handler: invocation => executeLoopXCommand(ctx.loopx, invocation),
  })
}
