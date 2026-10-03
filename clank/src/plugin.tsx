// Vibe Tracks dashboard as a Clank plugin (clank-workbench CLAUDE.md §1): one viewer, for `.vtdash` files, whose
// backend (backend/server.py) serves the projection built by vibetracks/dashboard/build.py and its media.
// WHY a Clank plugin and not an app of its own: a new view of a file is a Clank plugin, never a new shell (every
// copied shell froze at one version).

import { LayoutDashboard } from 'lucide-react'
import type { ClankPlugin, ViewerProps } from '@clank/api'
import { Dashboard } from './Dashboard'

/** `?vtdash=<workspace-relative path>` opens that file once at startup (scripts/open-dashboard uses it).
 * WHY a URL parameter read by this plugin: Clank has no "open this file" URL of its own, and `ctx.workbench.open`
 * waits for the restored layout, so one link always lands on the dashboard whatever the workspace last showed. */
export function startupPath(search: string): string | null {
  const value = new URLSearchParams(search).get('vtdash')
  if (!value) return null
  const path = value.replace(/^\/+/, '')
  if (!path.endsWith('.vtdash') || path.split('/').some((segment) => segment === '..' || segment === '.')) return null
  return path
}

const STARTUP_OPEN_DELAY_MS = 1500

const plugin: ClankPlugin = {
  id: 'vibetracks',
  activate(ctx) {
    function VibeTracksDashboard(props: ViewerProps) {
      return <Dashboard {...props} backend={ctx.backend} />
    }
    const viewer = ctx.registerViewer({
      id: 'vibetracks.dashboard',
      displayName: 'Vibe Tracks dashboard',
      icon: LayoutDashboard,
      selector: [{ extensions: ['.vtdash'] }],
      // WHY 'default': no core viewer claims `.vtdash`, and opening one should show the dashboard itself; its two
      // keys (title, data_home) are edited in any text editor through Open with….
      priority: 'default',
      documentType: 'text',
      component: VibeTracksDashboard,
    })
    const path = startupPath(location.search)
    // WHY a delay before the open (measured 2026-10-03 on a fresh lane workspace): an open fired the moment the workspace
    // is ready raced Clank's first-run setup (Home's auto-open and the empty main group) and left the dashboard in a
    // split beside an empty pane, which the saved layout then kept forever; 1.5 s later it joins the main group as a tab.
    // Rejected: reaching into dockview (Clank-internal, `@/` imports are refused from plugins). Worst case on a slow
    // machine is that split again, never a lost open.
    if (path) window.setTimeout(() => ctx.workbench.open(path, { viewerId: 'vibetracks.dashboard' }), STARTUP_OPEN_DELAY_MS)
    return () => viewer.dispose()
  },
}

export default plugin
