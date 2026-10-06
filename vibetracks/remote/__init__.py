"""Vibe Tracks remote: agents on other machines share their loop files through a git repo; one hub serves them.

- ``share.py``: the share's layout (``hosts/<host>/...``) and the small helpers every side uses.
- ``sync.py``: the per-machine process that mirrors selected files into ``hosts/<host>/`` and syncs the clone.
- ``session_hook.py``: a Claude Code hook that records a session card (and its Remote Control link) in the share.
- ``hub.py``: the web server on the workstation that pulls the share, builds the dashboard projection, serves the app.

docs/remote/DESIGN.md is the why and the how-to.
"""
