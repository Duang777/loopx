import { readFile, readdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

async function text(path: string): Promise<string> {
  return readFile(join(packageRoot, path), 'utf8')
}

describe('sidecar-free package boundary', () => {
  it('ships the deliberate 0.2.0 contract without a direct storage dependency', async () => {
    const manifest = JSON.parse(await text('package.json')) as {
      version: string
      dependencies?: Record<string, string>
      peerDependencies?: Record<string, string>
      optionalDependencies?: Record<string, string>
      devDependencies?: Record<string, string>
    }

    expect(manifest.version).toBe('0.2.0')
    for (const dependencies of [
      manifest.dependencies,
      manifest.peerDependencies,
      manifest.optionalDependencies,
      manifest.devDependencies,
    ]) {
      expect(Object.keys(dependencies ?? {}).filter(name => (
        name.startsWith('@deepseek-ai/dsh-storage')
      ))).toEqual([])
    }
  })

  it('contains no plugin-owned sidecar schema, injection, or compatibility file', async () => {
    const sourceNames = (await readdir(join(packageRoot, 'src'))).sort()
    expect(sourceNames).not.toContain('binding.ts')

    const source = (
      await Promise.all(sourceNames.map(name => text(join('src', name))))
    ).join('\n')
    expect(source).not.toContain('@deepseek-ai/dsh-storage-domain')
    expect(source).not.toContain('dsh_loopx_plugin')
    expect(source).not.toContain('storageDomain')
    expect(source).not.toContain('loopxBindingDomainSpec')

    const installMetadata = `${await text('cordis.patch.yml')}\n${await text('install.sh')}`
    expect(installMetadata).not.toContain('storage-domain')
  })

  it('keeps the coordinator private and the existing four Cordis faces', async () => {
    const rootExports = await text('src/index.ts')
    expect(rootExports).not.toMatch(/coordinator/iu)

    const patch = await text('cordis.patch.yml')
    expect([...patch.matchAll(/^\s*- id: (loopx-[^\s]+)$/gmu)].map(match => match[1])).toEqual([
      'loopx-service',
      'loopx-command',
      'loopx-tools',
      'loopx-driver',
    ])
  })
})
