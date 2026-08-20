import { EventEmitter } from 'node:events'
import type { ChildProcess, ExecFileException } from 'node:child_process'
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import {
  LoopXCliClient,
  LoopXCliError,
  type ExecFileLike,
} from '../src/cli-client.ts'

const packetSchema = z.looseObject({
  schema_version: z.literal('fixture_v0'),
  ok: z.boolean(),
})

function childProcess(): ChildProcess {
  return new EventEmitter() as ChildProcess
}

function immediateExecutor(
  stdout: string,
  stderr = '',
  error: ExecFileException | null = null,
): ExecFileLike {
  return (_file, _args, _options, callback) => {
    queueMicrotask(() => callback(error, stdout, stderr))
    return childProcess()
  }
}

function request(kind: 'read' | 'idempotent-write' | 'write' = 'read') {
  return {
    operation: 'fixture',
    kind,
    args: ['status', '--goal-id', 'goal-a'],
    cwd: '/tmp',
    schema: packetSchema,
  } as const
}

describe('LoopXCliClient', () => {
  it('uses config then LOOPX_BIN then PATH and always executes an argv array without a shell', async () => {
    const calls: Parameters<ExecFileLike>[] = []
    const execFile: ExecFileLike = (file, args, options, callback) => {
      calls.push([file, args, options, callback])
      queueMicrotask(() => callback(null, JSON.stringify({
        schema_version: 'fixture_v0',
        ok: true,
        additive: 'accepted',
      }), ''))
      return childProcess()
    }
    const configured = new LoopXCliClient({
      loopxBin: '/opt/loopx/bin/loopx',
      environment: { LOOPX_TEST_MODE: '1' },
    }, {
      execFile,
      parentEnv: {
        LOOPX_BIN: '/env/loopx',
        PATH: '/usr/bin',
        PRIVATE_TOKEN: 'must-not-cross',
      },
    })

    await expect(configured.runJson(request())).resolves.toMatchObject({
      schema_version: 'fixture_v0',
      ok: true,
      additive: 'accepted',
    })
    expect(configured.binarySource).toBe('config')
    expect(calls[0]?.[0]).toBe('/opt/loopx/bin/loopx')
    expect(calls[0]?.[1]).toEqual([
      '--format', 'json', 'status', '--goal-id', 'goal-a',
    ])
    expect(calls[0]?.[2]).toMatchObject({ shell: false, encoding: 'utf8' })
    expect(calls[0]?.[2].env).toEqual({
      LOOPX_BIN: '/env/loopx',
      LOOPX_TEST_MODE: '1',
      PATH: '/usr/bin',
    })

    const environment = new LoopXCliClient({}, {
      execFile: immediateExecutor('{"schema_version":"fixture_v0","ok":true}'),
      parentEnv: { LOOPX_BIN: '/env/loopx' },
    })
    expect(environment.binarySource).toBe('environment')
    await environment.runJson(request())

    let pathFile = ''
    const path = new LoopXCliClient({}, {
      execFile: (file, _args, _options, callback) => {
        pathFile = file
        queueMicrotask(() => callback(null, '{"schema_version":"fixture_v0","ok":true}', ''))
        return childProcess()
      },
      parentEnv: { PATH: '/usr/bin' },
    })
    expect(path.binarySource).toBe('path')
    await path.runJson(request())
    expect(pathFile).toBe('loopx')
  })

  it('rejects unsupported schemas while accepting additive fields and valid JSON on nonzero exit', async () => {
    const old = new LoopXCliClient({}, {
      execFile: immediateExecutor('{"schema_version":"fixture_v1","ok":true}'),
      parentEnv: {},
    })
    await expect(old.runJson(request())).rejects.toMatchObject({
      failure: { code: 'LOOPX_SCHEMA_UNSUPPORTED', outcomeUncertain: false },
    })

    const exitError = Object.assign(new Error('private process detail'), { code: 1 })
    const validFailure = new LoopXCliClient({}, {
      execFile: immediateExecutor(
        '{"schema_version":"fixture_v0","ok":false,"new_field":1}',
        'private stderr',
        exitError,
      ),
      parentEnv: {},
    })
    await expect(validFailure.runJson(request())).resolves.toMatchObject({
      schema_version: 'fixture_v0',
      ok: false,
      new_field: 1,
    })
  })

  it('enforces independent output caps without returning raw output', async () => {
    const stdoutClient = new LoopXCliClient({ stdoutCapBytes: 32 }, {
      execFile: immediateExecutor(JSON.stringify({
        schema_version: 'fixture_v0',
        ok: true,
        raw: 'secret-output-that-is-too-large',
      })),
      parentEnv: {},
    })
    const stdoutError = await stdoutClient.runJson(request()).catch(error => error as LoopXCliError)
    expect(stdoutError.failure).toMatchObject({ code: 'LOOPX_CLI_OUTPUT_LIMIT' })
    expect(JSON.stringify(stdoutError.failure)).not.toContain('secret-output')

    const stderrClient = new LoopXCliClient({ stderrCapBytes: 8 }, {
      execFile: immediateExecutor(
        '{"schema_version":"fixture_v0","ok":true}',
        'private-stderr-value',
      ),
      parentEnv: {},
    })
    await expect(stderrClient.runJson(request())).rejects.toMatchObject({
      failure: { code: 'LOOPX_CLI_OUTPUT_LIMIT' },
    })
  })

  it('marks every admitted write timeout uncertain and never makes it blindly retryable', async () => {
    const hanging: ExecFileLike = (_file, _args, options, callback) => {
      const onAbort = (): void => callback(
        Object.assign(new Error('raw abort reason'), { code: 'ABORT_ERR' }),
        '',
        '',
      )
      options.signal?.addEventListener('abort', onAbort, { once: true })
      return childProcess()
    }
    const writes = new LoopXCliClient({ writeTimeoutMs: 5 }, {
      execFile: hanging,
      parentEnv: {},
    })
    await expect(writes.runJson(request('write'))).rejects.toMatchObject({
      failure: {
        code: 'LOOPX_CLI_TIMEOUT',
        retryable: false,
        outcomeUncertain: true,
      },
    })

    const idempotent = new LoopXCliClient({ writeTimeoutMs: 5 }, {
      execFile: hanging,
      parentEnv: {},
    })
    await expect(idempotent.runJson(request('idempotent-write'))).rejects.toMatchObject({
      failure: {
        code: 'LOOPX_CLI_TIMEOUT',
        retryable: false,
        outcomeUncertain: true,
      },
    })

    const controller = new AbortController()
    const reads = new LoopXCliClient({ readTimeoutMs: 1_000 }, {
      execFile: hanging,
      parentEnv: {},
    })
    const pending = reads.runJson({ ...request(), signal: controller.signal })
    controller.abort(new Error('private caller detail'))
    await expect(pending).rejects.toMatchObject({
      failure: { code: 'LOOPX_CLI_ABORTED', outcomeUncertain: false },
    })
  })

  it('pins each binding command to one exact DSH surface and process-local home', async () => {
    const calls: Parameters<ExecFileLike>[] = []
    const client = new LoopXCliClient({}, {
      execFile: (file, args, options, callback) => {
        calls.push([file, args, options, callback])
        queueMicrotask(() => callback(null, '{"schema_version":"fixture_v0","ok":true}', ''))
        return childProcess()
      },
      parentEnv: {},
    })
    const home = {
      key: 'runtime:private',
      cwd: '/private/process-cwd',
      runtimeRoot: '/private/runtime-root',
    }
    await client.runBindingJson({
      operation: 'resolve-agent-thread',
      kind: 'read',
      args: [
        'resolve-agent-thread',
        '--host-surface', 'dsh',
        '--thread-id', 'session-a',
      ],
      home,
      schema: packetSchema,
    })
    expect(calls[0]?.[1]).toEqual([
      '--format', 'json',
      '--runtime-root', '/private/runtime-root',
      'resolve-agent-thread',
      '--host-surface', 'dsh',
      '--thread-id', 'session-a',
    ])
    expect(calls[0]?.[2].cwd).toBe('/private/process-cwd')

    const invalid = await client.runBindingJson({
      operation: 'resolve-agent-thread',
      kind: 'read',
      args: [
        '--runtime-root', '/caller-selected',
        'resolve-agent-thread',
        '--host-surface', 'dsh',
        '--thread-id', 'session-a',
      ],
      home,
      schema: packetSchema,
    }).catch(error => error as LoopXCliError)
    expect(invalid.failure).toMatchObject({ code: 'LOOPX_INVALID_REQUEST' })
    expect(JSON.stringify(invalid.failure)).not.toContain('/private/')
    expect(JSON.stringify(invalid.failure)).not.toContain('/caller-selected')
  })

  it('distinguishes an internal scope fence while preserving uncertain write application', async () => {
    const hanging: ExecFileLike = (_file, _args, options, callback) => {
      options.signal?.addEventListener('abort', () => callback(
        Object.assign(new Error('private scope reason'), { code: 'ABORT_ERR' }),
        '',
        '',
      ), { once: true })
      return childProcess()
    }
    const client = new LoopXCliClient({ writeTimeoutMs: 1_000 }, {
      execFile: hanging,
      parentEnv: {},
    })
    const pending = client.runJson({ ...request('write'), scopeKey: 'scope-a' })
      .catch(error => error as LoopXCliError)
    client.abortScope('scope-a')
    await expect(pending).resolves.toMatchObject({
      failure: {
        code: 'LOOPX_DRIVER_NOT_ARMED',
        outcomeUncertain: true,
      },
    })
  })

  it('aborts and drains active children before closing', async () => {
    const callback = vi.fn()
    const hanging: ExecFileLike = (_file, _args, options, done) => {
      options.signal?.addEventListener('abort', () => {
        callback()
        done(Object.assign(new Error('closed'), { code: 'ABORT_ERR' }), '', '')
      }, { once: true })
      return childProcess()
    }
    const client = new LoopXCliClient({ readTimeoutMs: 1_000 }, {
      execFile: hanging,
      parentEnv: {},
    })
    const pending = client.runJson(request()).catch(error => error as LoopXCliError)
    await client.close()
    expect(callback).toHaveBeenCalledOnce()
    await expect(pending).resolves.toMatchObject({
      failure: { code: 'LOOPX_SERVICE_CLOSED' },
    })
    await expect(client.runJson(request())).rejects.toMatchObject({
      failure: { code: 'LOOPX_SERVICE_CLOSED' },
    })
  })
})
