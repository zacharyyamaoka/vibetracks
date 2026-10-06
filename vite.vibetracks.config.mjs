// The dashboard lane's Vite config: Clank's own vite.config.ts, unmodified, loaded through Vite's own
// loadConfigFromFile, with one change, an absolute cacheDir in THIS checkout, plus the restart-on-edit of Clank's
// config that a direct `vite` run gets for free (restartWhenChanged below).
//
// Copied from bam_ws src/dev/bam_kinsim_dashboard/vite.kinsim.config.mjs (wave 3), names changed only.
// stable-preview.json's Preview (and so every `sps dev` lane) runs Clank's unmodified vite.js with
// `--config {checkout}/vite.vibetracks.config.mjs`.
//
// WHY a cache per checkout (measured 2026-10-01 in the kinsim lane): Clank's vite.config.ts sets no cacheDir, so a
// lane's Vite optimized its dependencies into /home/bam/clank-workbench/node_modules/.vite, the cache Zach's own Clank
// on 5310 serves from. A cache per checkout means no lane re-optimizes under another.
// WHY a wrapper and not a copy of Clank's config: clank-workbench is never edited, and a copied config freezes at one
// version; loading the real file means every Clank config change reaches the dashboard.

import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const CLANK = '/home/bam/clank-workbench'
const CLANK_CONFIG = join(CLANK, 'vite.config.ts')
// The one Vite that runs the lane (stable-preview.json starts Clank's node_modules/vite/bin/vite.js).
const CLANK_VITE = join(CLANK, 'node_modules', 'vite', 'dist', 'node', 'index.js')
// WHY .vite-cache in the checkout: it is gitignored (so it stays out of commits and out of sps's Stable
// snapshots, which copy git's view of the tree), it goes away with its worktree, and Obsidian never indexes a
// dot-directory (bam_ws/src is an open vault). Vite turns import.meta.url into this file's own URL when it
// bundles a config, so the path is this checkout's however the file is loaded.
const CACHE_DIR = join(dirname(fileURLToPath(import.meta.url)), '.vite-cache')
// WHY the 'native' loader for Clank's file (wave-2 review): Vite's default 'bundle' loader writes the bundled
// config into the nearest node_modules/.vite-temp/ and deletes it after the import, so every lane start wrote, then
// removed, a file inside /home/bam/clank-workbench, a write no before/after snapshot can see (strace, 2026-10-01).
// 'native' imports vite.config.ts with Node's own type stripping (on by default since Node 22.18) and writes
// nothing; Vite 8.2's fresh-import hooks still report the files it imports (scripts/clank_plugins.ts). Rejected:
// 'runner', which builds a module-runner environment to load one TypeScript file. This wrapper itself is still
// loaded by the CLI's default loader; with no node_modules above this checkout, that one-moment bundle lands
// beside it and is gitignored (*.timestamp-*.mjs).
const CLANK_CONFIG_LOADER = 'native'

/**
 * A Vite plugin that restarts the dev server when one of `files` changes.
 *
 * WHY (wave-2 review): Vite restarts a server when its config file or one of that file's imports changes, but it
 * only knows the OUTER config's imports, which is this wrapper. Clank's vite.config.ts and its imports are loaded
 * from inside it, so without this a running lane would keep serving the old Clank config after an edit to them.
 */
export function restartWhenChanged(files) {
  const watched = [...new Set(files.map((file) => resolve(file)))]
  return {
    name: 'vibetracks:restart-when-clank-config-changes',
    apply: 'serve',
    configureServer(server) {
      server.watcher.add(watched)
      server.watcher.on('change', (file) => {
        if (!watched.includes(resolve(file))) return
        server.config.logger.info(`[vibetracks] ${file} changed: restarting the server`, { timestamp: true })
        void server.restart()
      })
    },
  }
}

export default async function vibetracksViteConfig(configEnv) {
  // WHY a computed specifier: Vite bundles a config file before running it, and it inlines every import with
  // an absolute path; this directory has no node_modules for a bare 'vite' either. A dynamic import of a
  // computed URL stays a runtime import of Clank's own Vite.
  const viteEntry = pathToFileURL(CLANK_VITE).href
  const { loadConfigFromFile } = await import(viteEntry)
  const loaded = await loadConfigFromFile(configEnv, CLANK_CONFIG, CLANK, undefined, undefined, CLANK_CONFIG_LOADER)
  if (!loaded) throw new Error(`[vibetracks] no Vite config at ${CLANK_CONFIG}`)
  // WHY these watch ignores (measured 2026-10-03, a lane's dev server died with ENOSPC on fs.watch): Vite's root is all
  // of clank-workbench, whose .claude/worktrees held 27 agent checkouts, and the box's inotify limit (1,048,576
  // watches) ran out. Agent worktrees and journey builds never feed this lane's page, so the lane does not watch them.
  const watch = loaded.config.server?.watch ?? {}
  const ignored = [watch.ignored ?? []].flat()
  return {
    ...loaded.config,
    server: { ...loaded.config.server, watch: { ...watch, ignored: [...ignored, '**/.claude/**', '**/dist-journeys/**'] } },
    cacheDir: CACHE_DIR,
    plugins: [...(loaded.config.plugins ?? []), restartWhenChanged([CLANK_CONFIG, ...loaded.dependencies])],
  }
}
