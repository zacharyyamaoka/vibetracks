// Named .check.mjs, not .test.mjs, so a whole-tree vitest run does not pick up this node:test file. Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/variants/a/renameFence.check.mjs
// The rename fence (audit 2026-10-04 #6, #8): the revision is captured when editing starts, never adopted from a
// refreshed projection, and only an explicit "Save mine anyway" re-fences; the title goes out exactly as typed.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import * as fence from './renameFence.ts'

test('the fence is the revision on screen when editing started, whatever the projection does later', () => {
  let session = fence.begin('grasping', 'Grasping', 'R1')
  session = fence.edited(session, 'Grasp bench')
  // The projection refreshes mid-edit with another writer's title at R2: nothing in the session reads it.
  assert.deepEqual(fence.request(session), { title: 'Grasp bench', revision: 'R1' })
  // Not even after a conflict: the stored base is still R1 until the reader chooses.
  session = fence.conflicted(session, 'R2')
  assert.equal(session.base.revision, 'R1')
  assert.equal(session.draft, 'Grasp bench')
})

test('a 409 shows the other title only once the projection has re-read the note', () => {
  const session = fence.conflicted(fence.edited(fence.begin('grasping', 'Grasping', 'R1'), 'Mine'), 'R2')
  assert.equal(fence.theirsOf(session, 'Grasping', 'R1'), null, 'still the old revision: their title is not known yet')
  assert.deepEqual(fence.theirsOf(session, 'Theirs', 'R2'), { title: 'Theirs', revision: 'R2' })
  assert.equal(fence.theirsOf(fence.edited(fence.begin('g', 'G', 'R1'), 'x'), 'Theirs', 'R2'), null, 'no conflict, no theirs')
})

test('"Save mine anyway" re-fences on the revision the reader was shown, and only then', () => {
  let session = fence.conflicted(fence.edited(fence.begin('grasping', 'Grasping', 'R1'), 'Mine'), 'R2')
  const theirs = fence.theirsOf(session, 'Theirs', 'R2')
  session = fence.saveMineAnyway(session, theirs)
  assert.deepEqual(fence.request(session), { title: 'Mine', revision: 'R2' })
  assert.equal(session.phase.kind, 'editing')
  // A third writer after the reader looked (R3) is not adopted: saving against R2 409s again.
  assert.equal(fence.request(session).revision, 'R2')
})

test('blur never saves in a conflict, nor re-sends a draft the server just refused', () => {
  const editing = fence.edited(fence.begin('g', 'G', 'R1'), 'New')
  assert.equal(fence.onBlur(editing), 'submit')
  assert.equal(fence.onBlur(fence.conflicted(editing, 'R2')), 'stay')
  const refused = fence.failed(editing, 'title must not be empty')
  assert.equal(fence.onBlur(refused), 'stay')
  const retyped = fence.edited(refused, 'Newer')
  assert.equal(retyped.phase.kind, 'editing', 'typing clears the stale message')
  assert.equal(fence.onBlur(retyped), 'submit')
  assert.equal(fence.edited(fence.conflicted(editing, 'R2'), 'x').phase.kind, 'conflict', 'typing does not resolve a conflict')
})

test('the title is sent exactly as typed: no trim, no normalisation', () => {
  for (const typed of ['  Grasping  ', '\tGrasping', 'Grasping\n', '   ', '', 'Ｇrasping', 'é']) {
    const session = fence.edited(fence.begin('g', 'Grasping', 'R1'), typed)
    assert.deepEqual(fence.request(session), { title: typed, revision: 'R1' }, JSON.stringify(typed))
  }
})

test('only the exact starting text counts as unchanged', () => {
  assert.equal(fence.request(fence.begin('g', 'Grasping', 'R1')), null)
  assert.notEqual(fence.request(fence.edited(fence.begin('g', 'Grasping', 'R1'), 'Grasping ')), null)
})
