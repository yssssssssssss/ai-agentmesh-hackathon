import { readdir, stat } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const defaultAssetsDirectory = fileURLToPath(new URL('../dist/assets/', import.meta.url))
const assetsDirectory = resolve(process.env.AGENTMESH_BUNDLE_ASSET_DIR ?? defaultAssetsDirectory)
const limitBytes = Number(process.env.AGENTMESH_BUNDLE_CHUNK_LIMIT_BYTES ?? 500_000)

if (!Number.isFinite(limitBytes) || limitBytes <= 0) {
  throw new Error('AGENTMESH_BUNDLE_CHUNK_LIMIT_BYTES must be a positive number')
}

const chunks = await Promise.all(
  (await readdir(assetsDirectory))
    .filter((fileName) => fileName.endsWith('.js'))
    .map(async (fileName) => ({
      fileName,
      sizeBytes: (await stat(resolve(assetsDirectory, fileName))).size,
    })),
)

if (chunks.length === 0) throw new Error(`No JavaScript chunks found in ${assetsDirectory}`)

chunks.sort((left, right) => right.sizeBytes - left.sizeBytes)
const oversized = chunks.filter((chunk) => chunk.sizeBytes > limitBytes)
const largest = chunks[0]

console.log(
  `Bundle budget: largest=${largest.fileName} ${largest.sizeBytes} bytes; limit=${limitBytes} bytes`,
)

if (oversized.length > 0) {
  for (const chunk of oversized) console.error(`Oversized chunk: ${chunk.fileName} ${chunk.sizeBytes} bytes`)
  process.exitCode = 1
}
