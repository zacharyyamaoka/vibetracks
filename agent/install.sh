#!/usr/bin/env bash
# Install Vibe Tracks for interactive agent use:
#   1. the `vibetracks` CLI (editable, so repo updates propagate)
#   2. the /vibetracks skill for Claude Code   (~/.claude/skills/vibetracks)
#   3. the /vibetracks prompt for Codex        (~/.codex/prompts/vibetracks.md)
# Symlinks point back into this checkout; re-running is idempotent.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v uv >/dev/null 2>&1; then
  uv tool install --force --editable "$REPO" >/dev/null
  echo "CLI: installed with uv tool (editable) -> $(command -v vibetracks || echo '~/.local/bin/vibetracks')"
else
  python3 -m pip install --user --quiet --editable "$REPO"
  echo "CLI: installed with pip --user (editable)"
fi

mkdir -p "$HOME/.claude/skills" "$HOME/.codex/prompts"
ln -sfn "$REPO/agent/claude/vibetracks" "$HOME/.claude/skills/vibetracks"
echo "Claude skill: ~/.claude/skills/vibetracks -> $REPO/agent/claude/vibetracks"
ln -sf "$REPO/agent/codex/vibetracks.md" "$HOME/.codex/prompts/vibetracks.md"
echo "Codex prompt: ~/.codex/prompts/vibetracks.md -> $REPO/agent/codex/vibetracks.md"

vibetracks agent >/dev/null 2>&1 && echo "OK: 'vibetracks agent' prints the dispatcher briefing" \
  || echo "NOTE: open a new shell if 'vibetracks' is not on PATH yet"
