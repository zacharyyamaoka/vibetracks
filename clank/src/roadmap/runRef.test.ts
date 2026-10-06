import { describe, expect, it } from 'vitest'
import { runRef } from './runRef'

// V11: a named run opens THAT run's recorded evidence, never the rung's latest run.
const run = (over: Record<string, unknown>) => ({ kind: 'run', run_id: 'T52', abs: null, line: null, path: null, ...over }) as never

describe('runRef (what a proof row\'s run button opens)', () => {
  it('opens the recorded evidence file at its recorded line', () => {
    expect(runRef(run({ abs: '/data/runs/T52/result.json', line: 14 }))).toEqual({ path: '/data/runs/T52/result.json', line: 14 })
  })

  it('has no line when none is recorded', () => {
    expect(runRef(run({ abs: '/data/runs/T52/result.json' }))).toEqual({ path: '/data/runs/T52/result.json' })
  })

  it('has nothing to open without an absolute path (a relative path or an unresolved link is not openable)', () => {
    expect(runRef(run({ path: 'runs/T52/result.json' }))).toBeNull()
    expect(runRef(run({ abs: '' }))).toBeNull()
    expect(runRef(run({ abs: 'runs/T52/result.json' }))).toBeNull()
  })
})
