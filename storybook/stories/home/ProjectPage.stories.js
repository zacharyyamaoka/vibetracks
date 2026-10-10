// project.js — the project page: the lagging north star over the tracks' leading KPIs on one date axis, then the
// tracks, sessions and folders.
import { expect } from 'storybook/test';
import { page, projectRoute, until, HOME } from './_page.js';

export default { title: 'Home/Pages/Project', parameters: HOME };

export const Project = {
  render: (_, ctx) => page(ctx, (set) => ({ route: projectRoute(set) })),
  play: async ({ canvasElement }) => {
    await until(() => canvasElement.querySelector('[data-testid="vt-project-lagging"]'), 'the project chart');
    // one axis: every leading row's plot starts at the same x as the north star's
    const xs = [...canvasElement.querySelectorAll('.pg-chart .pg-pc')].map((c) => Math.round(c.getBoundingClientRect().left));
    await expect(new Set(xs).size).toBe(1);
  },
};
/** project.js#chart — the lagging / leading chart card alone. */
export const LaggingLeadingChart = {
  render: (_, ctx) => page(ctx, (set) => ({ route: projectRoute(set), focus: '[data-testid="vt-project-chart"]' })),
};
