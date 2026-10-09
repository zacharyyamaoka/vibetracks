"""Derived agent activity: what Claude Code itself wrote, read without hooks (docs/peps/0001).

- ``harness``: the live session files (``~/.claude-*/sessions/<pid>.json``, checked against /proc) and an incremental
  index over the transcripts (``~/.claude-*/projects/**.jsonl``, subagents included), with byte cursors.
- ``join``: which track a session belongs to, from the rules a track's note declares (``vibe-sessions``), and how.
- ``derive``: the rule order that turns those facts into a state word, health and worked time.

Stdlib only. Nothing here reads what an agent says about itself.
"""
