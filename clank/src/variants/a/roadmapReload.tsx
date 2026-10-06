// One refresh covers the whole page: every useRoadmap(...) a variant-A page mounts registers its reload() here, and the
// variant's reload (the home footer's "Reload", a rename's re-read) calls them all after re-reading the projection.
// WHY a registry and not a prop: the roadmaps are loaded deep in the tree (one per home row's rung cell, one per track
// page's Roadmap section); threading each reload up to the footer would couple every page to the footer.

import type { PluginBackend } from '@clank/api'
import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react'
import { useRoadmap, type RoadmapDocState } from '../../roadmap'

type Registry = Set<() => void>

const RoadmapReloads = createContext<Registry | null>(null)

export function RoadmapReloadProvider({ registry, children }: { registry: Registry; children: ReactNode }) {
  return <RoadmapReloads.Provider value={registry}>{children}</RoadmapReloads.Provider>
}

/** A stable registry for the variant's root. */
export function useRoadmapReloadRegistry(): Registry {
  const registry = useRef<Registry>(new Set())
  return registry.current
}

/** useRoadmap, plus registration of its reload() with the page's registry. Use this, never useRoadmap, in variant A. */
export function useRegisteredRoadmap(backend: PluginBackend, track: string): RoadmapDocState {
  const roadmap = useRoadmap(backend, track)
  const registry = useContext(RoadmapReloads)
  const latest = useRef(roadmap.reload)
  latest.current = roadmap.reload
  useEffect(() => {
    if (!registry) return
    const reload = () => latest.current()
    registry.add(reload)
    return () => {
      registry.delete(reload)
    }
  }, [registry])
  return roadmap
}
