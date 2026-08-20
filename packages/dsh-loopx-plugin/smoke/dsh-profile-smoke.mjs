#!/usr/bin/env node

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chmod, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dshBin = process.env.DSH_BIN || join(packageRoot, 'node_modules', '.bin', 'dsh')
const profileName = 'web'
const bundleRows = [
  ['loopx-service', 'dsh-loopx-plugin/service'],
  ['loopx-command', 'dsh-loopx-plugin/command'],
  ['loopx-tools', 'dsh-loopx-plugin/tools'],
  ['loopx-driver', 'dsh-loopx-plugin/driver'],
]
const hostProvidedPeers = [
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-agent',
  '@deepseek-ai/dsh-commands',
  '@deepseek-ai/dsh-session',
  '@deepseek-ai/dsh-tools',
]

function parseSpecs(argv) {
  const specs = []
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index]
    if (flag === '--') continue
    if (flag !== '--package-path' && flag !== '--tarball') {
      throw new Error(`unsupported argument: ${flag}`)
    }
    const value = argv[index + 1]
    if (!value) throw new Error(`${flag} requires a path`)
    specs.push({ kind: flag === '--tarball' ? 'tarball' : 'path', value: resolve(value) })
    index += 1
  }
  if (specs.length === 0) throw new Error('pass --package-path and/or --tarball')
  return specs
}

function run(file, args, options = {}) {
  const result = spawnSync(file, args, {
    cwd: options.cwd ?? packageRoot,
    env: options.env ?? process.env,
    encoding: 'utf8',
    maxBuffer: 8 * 1024 * 1024,
    shell: false,
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error([
      `${file} ${args.join(' ')} failed with ${String(result.status)}`,
      result.stdout,
      result.stderr,
    ].filter(Boolean).join('\n'))
  }
  return result.stdout
}

function assertPackedFiles(tarball) {
  const entries = run('tar', ['-tf', tarball]).trim().split('\n').filter(Boolean)
  assert(entries.length > 0, 'tarball is empty')
  for (const entry of entries) {
    assert.match(entry, /^package\/(?:package\.json|README\.md|LICENSE|NOTICE|cordis\.patch\.yml|lib\/[^/]+\.js|lib\/types\/[^/]+\.d\.ts)$/u)
  }
  for (const required of [
    'package/package.json',
    'package/README.md',
    'package/LICENSE',
    'package/NOTICE',
    'package/cordis.patch.yml',
    'package/lib/service.js',
    'package/lib/command.js',
    'package/lib/tools.js',
    'package/lib/driver.js',
    'package/lib/types/service.d.ts',
  ]) {
    assert(entries.includes(required), `tarball is missing ${required}`)
  }
  assert(!entries.includes('package/lib/binding.js'), 'obsolete sidecar runtime was packed')
  assert(!entries.includes('package/lib/types/binding.d.ts'), 'obsolete sidecar declarations were packed')
}

function assertInstalledConfig(dump) {
  let previous = -1
  for (const [id, name] of bundleRows) {
    const position = dump.indexOf(`id: ${id}`)
    assert(position > previous, `missing or unordered bundle row ${id}`)
    assert(dump.includes(`name: ${name}`), `missing bundle module ${name}`)
    previous = position
  }
  assert.deepEqual(
    [...dump.matchAll(/^\s*(?:-\s+)?id:\s+(loopx-[^\s]+)\s*$/gmu)].map(match => match[1]),
    bundleRows.map(([id]) => id),
    'profile must contain exactly the four LoopX bundle rows',
  )
  assert.deepEqual(
    [...dump.matchAll(/^\s*(?:-\s+)?name:\s+(dsh-loopx-plugin\/[^\s]+)\s*$/gmu)].map(match => match[1]),
    bundleRows.map(([, module]) => module),
    'profile must not expose a fifth dsh-loopx-plugin face',
  )
  assert(!dump.includes('dsh.client: dsh-loopx-plugin'), 'v1 must not add a Client-plane row')
}

const mockLoopXSource = String.raw`#!/usr/bin/env node
import { appendFile, readFile } from 'node:fs/promises'

const args = process.argv.slice(2)
const modeFile = process.env.LOOPX_SMOKE_MODE
const callsFile = process.env.LOOPX_SMOKE_CALLS
const sentinel = process.env.LOOPX_SMOKE_SENTINEL
if (!modeFile || !callsFile || !sentinel) throw new Error('smoke environment is incomplete')
const value = flag => {
  const index = args.indexOf(flag)
  return index < 0 ? undefined : args[index + 1]
}
if (value('--format') !== 'json') throw new Error('JSON format is required')
const commands = new Set([
  'resolve-agent-thread', 'status', 'bootstrap-command-pack', 'heartbeat-prompt',
])
const command = args.find(arg => commands.has(arg))
if (!command) throw new Error('unsupported smoke command')
await appendFile(callsFile, command + '\n')

const mode = (await readFile(modeFile, 'utf8')).trim()
const goalId = value('--goal-id') ?? 'goal-smoke'
const agentId = value('--agent-id') ?? 'agent-smoke'
const threadId = value('--thread-id') ?? 'session-smoke'
const project = value('--project') ?? process.cwd()
const binding = {
  schema_version: 'loopx_host_thread_binding_v1',
  host_surface: 'dsh',
  thread_id: threadId,
  revision: 7,
  state: 'bound',
  target: { goal_id: goalId, agent_id: agentId },
}

let output
if (command === 'resolve-agent-thread') {
  if (value('--host-surface') !== 'dsh') throw new Error('exact DSH Host surface is required')
  output = mode === 'fail'
    ? {
        schema_version: 'loopx_host_thread_binding_command_v1',
        ok: false, changed: false, application: 'no',
        error_kind: 'authority_unhealthy', binding,
      }
    : {
        schema_version: 'loopx_host_thread_binding_command_v1',
        ok: true, changed: false, application: 'no', binding,
      }
} else if (command === 'status') {
  output = {
    schema_version: 'loopx_status_v0', ok: true, goal_filter: goalId,
    registry: sentinel, state_file: sentinel, raw_stderr: sentinel, trace: sentinel,
    attention_queue: {
      items: [{
        goal_id: goalId, status: 'active', waiting_on: sentinel,
        severity: 'normal', lifecycle_phase: 'active', recommended_action: sentinel,
      }],
    },
  }
} else if (command === 'bootstrap-command-pack') {
  output = {
    schema_version: 'loopx_bootstrap_command_pack_v0', ok: true, read_only: true,
    project, goal_id: goalId, agent_id: agentId,
    agent_type: 'deepseek-harness-native', host_surface: 'dsh', thread_id: threadId,
    host_thread_binding: binding,
    host_loop_activation: {
      schema_version: 'loopx_host_loop_activation_v1',
      agent_type: 'deepseek-harness-native', goal_id: goalId, agent_id: agentId,
      activation_allowed: true,
      identity_contract: {
        schema_version: 'loopx_host_loop_identity_selection_v0',
        registered_agents: [agentId],
      },
      identity_selection_gate: null,
      host_surface: 'deepseek_harness_native_session',
      activation_method: 'current_session_host_tool',
      activation_input: {
        schema_version: 'loopx_deepseek_harness_native_activation_input_v0',
        tool: 'loopx_goal_activate', arguments: { goalId, agentId },
      },
      host_mutation: {
        owner: 'DSH LoopX plugin', host_tool: 'loopx_goal_activate',
        current_session_only: true, cli_can_mutate_directly: false,
        forbidden_tool_arguments: ['sessionId', 'registryPath', 'taskBody', 'argv'],
      },
    },
  }
} else {
  output = {
    schema_version: 'loopx_heartbeat_prompt_v0', ok: true,
    goal_id: goalId, agent_id: agentId, runtime_profile: 'generic_cli',
    task_body: 'Continue through fresh LoopX authority.',
  }
}
process.stdout.write(JSON.stringify(output))
if (output.ok === false) process.exitCode = 2
`

async function importFrom(requireFromPlugin, specifier) {
  return import(pathToFileURL(requireFromPlugin.resolve(specifier)).href)
}

function makeAgent(project) {
  const nextTurn = []
  const nextStep = []
  const followups = []
  const steers = []
  let status = 'idle'
  let maintenance = false
  const session = {
    id: 'session-smoke',
    header: { version: 0, id: 'session-smoke', createdAt: 7, cwd: project, seedLength: 0 },
    events: [],
    surface: { nodes: [] },
  }
  const agent = {
    id: 'session-smoke',
    session,
    get status() { return status },
    inbox: {
      nextTurn,
      nextStep,
      get hasPending() { return nextTurn.length > 0 || nextStep.length > 0 },
      append(target, message) {
        const queue = target === 'next-step' ? nextStep : nextTurn
        queue.push(message)
      },
      remove(id) {
        for (const queue of [nextStep, nextTurn]) {
          const position = queue.findIndex(message => message.id === id)
          if (position >= 0) {
            queue.splice(position, 1)
            return true
          }
        }
        return false
      },
    },
    followup(message) {
      followups.push(message)
      nextTurn.push(message)
    },
    steer(message) { steers.push(message) },
    send(message, target) {
      const queue = target === 'next-step' ? nextStep : nextTurn
      queue.push(message)
    },
    runMaintenance(task) {
      if (status === 'running' || maintenance) throw new Error('maintenance unavailable')
      maintenance = true
      const controller = new AbortController()
      return Promise.resolve(task(controller.signal)).finally(() => { maintenance = false })
    },
    whenIdle() { return Promise.resolve() },
    cancel() { status = 'idle' },
  }
  return {
    agent, followups, steers, nextTurn, nextStep,
    setStatus(value) { status = value },
  }
}

async function exerciseInstalledPlugin(installedDir, home, mockLoopX, modeFile, callsFile) {
  const requireFromPlugin = createRequire(join(installedDir, 'package.json'))
  const [{ Context }, serviceModule, commandModule, toolsModule, driverModule] = await Promise.all([
    importFrom(requireFromPlugin, '@deepseek-ai/cordis'),
    import(pathToFileURL(join(installedDir, 'lib', 'service.js')).href),
    import(pathToFileURL(join(installedDir, 'lib', 'command.js')).href),
    import(pathToFileURL(join(installedDir, 'lib', 'tools.js')).href),
    import(pathToFileURL(join(installedDir, 'lib', 'driver.js')).href),
  ])
  const project = join(home, 'behavior-project')
  const runtimeRoot = join(home, 'runtime-root')
  const sentinel = '/private/smoke/SECRET_TOKEN raw-stderr TRACE_ID'
  await mkdir(project, { recursive: true })
  await mkdir(runtimeRoot, { recursive: true })
  const ctx = new Context()
  await ctx.plugin(serviceModule.LoopXService, {
    loopxBin: mockLoopX,
    project,
    runtimeRoot,
    environment: {
      LOOPX_SMOKE_MODE: modeFile,
      LOOPX_SMOKE_CALLS: callsFile,
      LOOPX_SMOKE_SENTINEL: sentinel,
    },
  })
  assert.equal(ctx.get('goals'), undefined, 'ctx.loopx must not mount or consume ctx.goals')
  const service = ctx.get('loopx')
  assert(service, 'LoopX service did not activate without a storage-domain')

  const commands = new Map()
  const tools = new Map()
  commandModule.apply({
    loopx: service,
    commands: { register: value => commands.set(value.name, value) },
  })
  toolsModule.apply({
    loopx: service,
    tools: { register: value => tools.set(value.name, value) },
  })
  assert.deepEqual([...tools.keys()].sort(), [
    'loopx_driver_pause',
    'loopx_driver_resume',
    'loopx_goal_activate',
    'loopx_goal_attach',
    'loopx_goal_detach',
    'loopx_goal_start',
    'loopx_status',
    'loopx_todo_add',
    'loopx_todo_claim',
    'loopx_todo_complete',
    'loopx_todo_update',
  ], 'packed plugin must expose exactly eleven bounded model tools')

  const harness = makeAgent(project)
  const { agent } = harness
  const driver = new driverModule.LoopXContinuationDriver({
    service,
    isLiveAgent: current => current === agent,
  })
  driver.observeAgent(agent)
  const command = commands.get('loopx')
  assert(command, '/loopx command was not registered')
  const signal = new AbortController().signal
  let commandOrdinal = 0
  const invoke = async rawInput => {
    const commandId = `smoke-command-${++commandOrdinal}`
    driver.onSessionEvent(agent, { type: 'command/run', data: { commandId } })
    const result = await command.handler({ commandId, agent, rawInput, signal })
    driver.onSessionEvent(agent, { type: 'command/done', data: { commandId } })
    return result
  }

  const installedManifest = JSON.parse(await readFile(join(installedDir, 'package.json'), 'utf8'))
  assert.equal(installedManifest.version, '0.2.0')
  assert.deepEqual(Object.keys(installedManifest.exports).sort(), [
    '.', './command', './cordis.patch.yml', './driver', './package.json', './service', './tools',
  ], 'manifest must expose exactly four runtime faces plus root metadata')

  const statusResult = await invoke('status')
  assert.equal(statusResult.kind, 'success')
  assert.match(statusResult.text, /"hostSurface":"dsh"/u)
  assert.match(statusResult.text, /"activation":"disarmed"/u)
  assert(!statusResult.text.includes(sentinel), 'typed command receipt leaked private CLI fields')
  assert.equal(harness.followups.length, 1, 'idle status must queue one bounded follow-up')
  assert(!harness.followups[0].content[0].text.includes(sentinel), 'follow-up leaked private CLI fields')

  const session = commandModule.deriveLoopXSessionRef(agent, 'smoke')
  assert.equal(session.ok, true)
  harness.nextTurn.length = 0
  harness.followups.length = 0
  harness.setStatus('running')
  const resumed = await service.resume(session.value, signal)
  assert.equal(resumed.ok, true, 'fresh authoritative resume did not arm')
  const armed = await service.status(session.value, signal)
  assert.equal(armed.ok, true)
  assert.equal(armed.value.host.activation, 'armed')

  const foreignId = 'smoke-foreign-command'
  driver.onSessionEvent(agent, { type: 'command/run', data: { commandId: foreignId } })
  await Promise.resolve()
  driver.onSessionEvent(agent, { type: 'command/done', data: { commandId: foreignId } })
  const disarmed = await service.status(session.value, signal)
  assert.equal(disarmed.ok, true)
  assert.equal(disarmed.value.host.activation, 'disarmed', 'foreign command did not latch disarm')

  let toolOrdinal = 0
  const executeStatusTool = async () => {
    const definition = tools.get('loopx_status')
    const callId = `smoke-tool-${++toolOrdinal}`
    return definition.execute({}, {
      name: 'loopx_status', callId, rootCallId: callId, arguments: {}, agent, signal,
      token: Symbol(callId), concludeTurn() {},
    })
  }
  await writeFile(modeFile, 'fail')
  for (let attempt = 1; attempt <= 8; attempt += 1) {
    const failed = await executeStatusTool()
    assert.equal(failed.execution, 'rejected', `failure ${attempt} did not settle once`)
    assert.equal(failed.application, 'no')
  }
  await writeFile(modeFile, 'ok')
  const suppressed = await service.status(session.value, signal)
  assert.equal(suppressed.ok, true)
  assert.equal(suppressed.value.host.automaticFollowupSuppressed, true)
  const recovered = await executeStatusTool()
  assert.equal(recovered.execution, 'succeeded')
  assert(!JSON.stringify(recovered).includes(sentinel), 'tool receipt leaked private CLI fields')
  const readback = await service.status(session.value, signal)
  assert.equal(readback.ok, true)
  assert.equal(readback.value.host.automaticFollowupSuppressed, false)

  const calls = (await readFile(callsFile, 'utf8')).trim().split('\n')
  for (const expected of ['resolve-agent-thread', 'status', 'bootstrap-command-pack', 'heartbeat-prompt']) {
    assert(calls.includes(expected), `assembled lifecycle did not call ${expected}`)
  }
  await driver.dispose()
  await ctx.fiber.dispose()
}

async function runProfileSmoke(spec, ordinal) {
  if (spec.kind === 'tarball') assertPackedFiles(spec.value)
  const home = await mkdtemp(join(tmpdir(), `dsh-loopx-profile-${ordinal}-`))
  const mockLoopX = join(home, 'loopx-smoke.mjs')
  const modeFile = join(home, 'loopx-mode.txt')
  const callsFile = join(home, 'loopx-calls.txt')
  await writeFile(mockLoopX, mockLoopXSource)
  await chmod(mockLoopX, 0o755)
  await writeFile(modeFile, 'ok')
  await writeFile(callsFile, '')
  const env = { ...process.env, DSH_HOME: home, LOOPX_BIN: mockLoopX }
  try {
    const installSpecs = spec.kind === 'tarball'
      ? [
          ...await Promise.all(hostProvidedPeers.map(name => realpath(
            join(packageRoot, 'node_modules', ...name.split('/')),
          ))),
          spec.value,
        ]
      : [spec.value]
    run(dshBin, [
      'plugin', '--profile', profileName, 'add', ...installSpecs,
      spec.kind === 'tarball' ? '--prefer-offline' : '--offline', '--ignore-scripts',
    ], { env })
    const dump = run(dshBin, ['--profile', profileName, '--dump-config'], { env })
    assertInstalledConfig(dump)
    const installed = await realpath(join(home, 'profiles', profileName, 'node_modules', 'dsh-loopx-plugin'))
    await exerciseInstalledPlugin(installed, home, mockLoopX, modeFile, callsFile)
    run(dshBin, ['plugin', '--profile', profileName, 'remove', 'dsh-loopx-plugin'], { env })
    const removed = run(dshBin, ['--profile', profileName, '--dump-config'], { env })
    for (const [id] of bundleRows) assert(!removed.includes(`id: ${id}`), `remove retained ${id}`)
  } finally {
    await rm(home, { recursive: true, force: true })
  }
}

const specs = parseSpecs(process.argv.slice(2))
for (const [index, spec] of specs.entries()) await runProfileSmoke(spec, index + 1)
process.stdout.write(`dsh-loopx profile smoke passed (${specs.map(spec => spec.kind).join(', ')})\n`)
