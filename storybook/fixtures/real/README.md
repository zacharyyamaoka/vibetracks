# Real fixtures (local only)

`npm --prefix /home/bam/vibetracks-storybook/storybook run capture` fills this folder with the documents a running
home serves (GET only; default Zach's Stable on 4394). They are BAM's live loop data, so everything here except this
README is gitignored: the repo is public. The stories use them when present (toolbar: Data = real) and fall back to
the committed synthetic set (`fixtures/synthetic/`, built by `npm run fixtures`) when not, saying which in a chip.
