// review.js — the Review page over GET ../needs (real fixture; the synthetic set has no needs document).
import { expect } from 'storybook/test';
import { page, until, HOME } from './_page.js';

export default { title: 'Home/Pages/Review', parameters: HOME };

export const Review = {
  render: (_, ctx) => page(ctx, { route: { name: 'review' } }),
  play: async ({ canvasElement }) => {
    await until(() => canvasElement.querySelector('[data-testid="vt-review"]') && !/Reading the loops/.test(canvasElement.textContent), 'the needs document');
  },
};
/** review.js#itemCard — one decision a loop is waiting on. */
export const ReviewItem = { render: (_, ctx) => page(ctx, { route: { name: 'review' }, focus: '[data-testid="vt-review-item"]' }) };
