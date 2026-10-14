// Shared bits for the home stories: mount a page over the toolbar's fixture set and label where its data came from.
import { fixtureSet, mountPage, richestTrack, biggestProject, until, useFixture } from '../../lib/home.js';

export { until, fixtureSet, useFixture };

/** The story's DOM: the mounted page plus a chip naming the fixture (real capture or synthetic). */
export function page(ctx, opts) {
  // A story may pin its set (parameters.data): the rename story needs revisions, which only the r3 code writes.
  const set = fixtureSet(Object.assign({}, ctx.globals, ctx.parameters.data ? { data: ctx.parameters.data } : {}));
  const resolved = typeof opts === 'function' ? opts(set) : opts;
  const root = mountPage(set, Object.assign({ theme: ctx.globals.theme }, resolved));
  const wrap = document.createElement('div');
  wrap.style.display = 'contents';
  wrap.append(root);
  const chip = document.createElement('div');
  chip.className = 'sb-fixture';
  chip.textContent = `fixture: ${set.label}`;
  wrap.append(chip);
  return wrap;
}
/** The track a story shows: the richest one, or the richest one for which want(trackDoc) holds. */
export const trackRoute = (set, query, want) => ({ name: 'track', id: richestTrack(set, want) || richestTrack(set), query: query || {} });
export const projectRoute = (set) => ({ name: 'project', id: biggestProject(set), query: {} });
/** Home pages read a fixture clock and fixtures; these parameters switch that on.
 *  WHY a11y is 'todo' (reported in the panel, not a failing gate) for the EXISTING home only: axe flags Claude
 *  Desktop's own muted ink (tokens.css, copied verbatim on Zach's Oct 9 instruction, "do not retune these by eye")
 *  below 4.5:1 on small labels (color-contrast, 38 hits on Oct 10), plus link-in-text-block, heading-order and one
 *  aria-required-children. Retuning Claude's tokens is Zach's call, not a storyboard side effect. New components
 *  (stories/viz) keep the default 'error'. */
export const HOME = { home: true, a11y: { test: 'todo' } };
