# Vibe Tracks remote: agents on several machines, one dashboard

## The problem

The dashboard's adapters read loop files (`status.json`, `loop_events.jsonl`, `runs.jsonl`, …) from paths on **this** workstation (`vibetracks/sources.py`). Agents running on other machines (the Windows box, a laptop, a cloud VM) write the same kind of files there, and the dashboard cannot see them. We want those agents to keep working exactly as they do today, and Zach to see every track, from any machine, on his phone.

## The shape

```
worker machine (win-a)                          share (a git repo on GitHub)            hub (this workstation)
  agents write their own loop files               hosts/win-a/host.json                   ls-remote: 5 s after news, else 60 s
  vibetracks.remote.sync (every 3 s, local):      hosts/win-a/sources.json   ──pull──▶    pull only when the remote moved
    copy changed files into the clone             hosts/win-a/files/<key>/...             restore mtimes from commits
    only if something changed:         ──push──▶  hosts/win-a/sessions/<id>.json          merge every sources.json
      commit hosts/win-a/ only, push              hosts/win-b/...                         run vibetracks.dashboard.build
      ──poke (POST /api/poke)─────────────────────────────────────────────────────────▶   serve the phone app on :4470
  session hook (Claude Code) writes a session card into the clone
```

- **`vibetracks/remote/share.py`**: the layout (above) and its helpers.
  `hosts/<host>/host.json` is the heartbeat `{host, platform, python, vt_sync_version, last_sync, interval_s, mirrors, skipped, error}`; `sources.json` maps each source key to a path inside the host folder; `files/<key>/` holds the copies (a mirrored directory keeps its tree); `sessions/<session_id>.json` are session cards.
- **One writer per host folder.** A machine only ever stages `hosts/<its name>/`, so two machines never touch the same path: every pull is a fast-forward or a trivial rebase, and a conflict means something wrote where it must not (sync then aborts the rebase, keeps its local commit, and reports the error; it never forces).
- **`sync.py`** (per machine): every `interval_s`, mirror and (when due) heartbeat, locally; only when something is there to send: commit, `git pull --rebase --autostash`, `git push`, poke. It only reads the agents' files. `init` and `hook-config` set a machine up (docs/remote/WORKER_SETUP.md).
- **`session_hook.py`**: a Claude Code hook that records `{session_id, host, account, agent, model, cwd, track, url, …}`. The `url` is `https://claude.ai/code/<CLAUDE_CODE_BRIDGE_SESSION_ID>`, which exists only when the session has Remote Control on (`remoteControlAtStartup` in settings); otherwise the card says so and the app shows "no Remote Control link".
- **`hub.py`**: checks the share (below), pulls when it moved, writes `<data-home>/remote-sources.json` (this machine's own `sources.json` if any, then every key the share supplies pointed into `hosts/<host>/files/`, then `dashboard_data_home` = the hub's `--data-home`), runs the ordinary `python -m vibetracks.dashboard.build` with `$VIBETRACKS_SOURCES` naming that file, and serves `/api/state`, `/api/track/<id>`, `/api/events` (SSE), `/api/health`, the JSON POSTs `/api/refresh` and `/api/poke`, and the app. `/api/state` lists every session card under its machine (`hosts[].sessions`: live first, then up to 10 others), with or without a track, so the Machines page answers "which agents run on win-a, and how do I talk to them". A track is attributed to the hosts that supply at least one of its declared `vibe-sources` keys; a track none of whose keys come from the share is on the hub machine. Two hosts supplying the same key: the newer `last_sync` wins and a `duplicate_key` problem is listed.

## The refresh model: push on change, poke, adaptive checks, Refresh now

- **A worker sends only when it has something.** Each round decides locally, with no network, whether there is
  anything to send: an uncommitted change under `hosts/<host>/` (`git status --porcelain -- hosts/<host>`: the mirror,
  a due heartbeat, or a card the session hook wrote straight into the clone) or a local commit the upstream lacks
  (`git rev-list --count @{u}..HEAD`). Nothing: the round ends, no fetch, no pull, no push. WHY: the prototype pulled
  and pushed every 3 s, ~2,400 GitHub round trips an hour per idle machine. Something: commit, pull --rebase, push.
  `receive_interval_s` (default 0, never) makes an idle worker pull at that period too, for files the hub may one day
  send back.
- **Poke is the interrupt.** After a push the worker POSTs `{"host": …}` to `poke_url` (the hub's `/api/poke`, 3 s
  timeout; a failure is logged, never an error). The hub answers 202 at once and checks within a second.
- **Adaptive checks are the safety net** (a missed poke, a worker without `poke_url`). A check is one
  `git ls-remote <remote> <branch>` compared with the local remote-tracking ref; fetch + merge + mtime restore only
  when they differ. Checks run every `--check-fast` (5 s) for `--fast-window` (120 s) after any change, Refresh or poke,
  else every `--check-slow` (60 s). The hub's own loops change too: on every fast tick it stats the projection's local
  source files (and a source directory's direct children) and rebuilds when an `(mtime_ns, size)` moved, plus a safety
  rebuild every `--rebuild-interval` (300 s).
- **Refresh now.** The app's Refresh button (or `r`) POSTs `/api/refresh`: check + pull + rebuild, answered when done
  (`{ok, revision, changed, took_s}`); a second press joins the one in flight. The header shows "checked N s ago" from
  `hub.last_check`, kept current by an SSE `check` event.
- **The POSTs are guarded** because they make the hub run git and a build: an allowed Host (403, the same DNS-rebinding
  guard as the GETs), `Content-Type: application/json` (415, which a cross-site form cannot send) and a body of at most
  4 KB (413).

**Request budget.** An idle worker: one push per heartbeat (`heartbeat_s`, 300 s: 12 an hour), nothing else. A busy
worker: one pull + one push per round that has news. The hub on a quiet share: one `ls-remote` a minute (60 an hour);
for two minutes after news, one every 5 s. A poke is one small local HTTP request.

## The session hook on a settings.json that every machine shares

Zach's `~/.claude/settings.json` is a symlink into his vault, identical on every machine, so it cannot name one
machine's python, share or host. `python -m vibetracks.remote.sync hook-config` writes two machine-local files instead:

- `~/.vibetracks/remote.json`: `{"python", "share", "host", "tracks_map"}`;
- `~/.vibetracks/hook`: a two-line POSIX sh launcher, `exec "<this machine's python>" "<…>/vibetracks_session.py"`.

settings.json gets one line, the same on every machine, under `UserPromptSubmit`, `Stop` and `SessionEnd`:

```bash
[ ! -x "$HOME/.vibetracks/hook" ] || exec "$HOME/.vibetracks/hook"
```

- A machine that never ran hook-config has no launcher, so the line is a silent no-op there (exit 0, no output). The
  hub workstation and every other machine are unaffected, and a second or third worker needs no edit to the shared
  file: running hook-config on it is what switches the hook on there.
- `vibetracks_session.py` is stdlib only. It runs `<python from remote.json> -m vibetracks.remote.session_hook
  --share … --host …` with the hook's stdin and environment (`CLAUDE_CODE_BRIDGE_SESSION_ID` is how the card gets its
  Remote Control link), a 5 s timeout and stdout discarded (a UserPromptSubmit hook's stdout would land in the
  prompt), and always exits 0.
- On Windows the hook shell is Git Bash, which runs the sh launcher; the launcher names the venv's python by absolute
  path, so a missing `python3` there does not matter. `tests/test_remote_units.py` runs the exact line through `sh`.

## Why git for v1, and the mtime restore

- **Git is already on every machine, authenticated, and versioned.** GitHub is the relay, history is the audit trail ("what did win-a's loop say at 03:00?"), and nothing new has to run or be secured.
- **The one trap is mtime.** A checkout stamps every file with the pull time, and the dashboard's freshness/stall rule reads mtime (VT-007 liveness): a loop that stopped yesterday would look alive after every pull. So sync commits with `GIT_AUTHOR_DATE` = the newest mtime among the mirrored files it changed (`copy2` keeps the worker's mtime on the copy), and `pull_and_restore` sets each pulled file's mtime to the author time of the last commit that touched it. The hub also restores every file once at startup, since a fresh clone carries clone times. The stock tool for the same job is MestreLion's [`git-restore-mtime`](https://github.com/MestreLion/git-tools); ours is the same idea limited to the paths a pull changed, in stdlib Python.
- **Approximation to know about:** files that change in the same sync commit all get that commit's (newest) time on the hub. Freshness reads the newest source, so the track's age is exact; an individual older file in the same commit reads newer than it is.

## What moves and what stays

- **Moves:** small loop files (status, event logs, ledgers, ladders; each ≤ `max_file_bytes`, default 5 MB, anything bigger is listed in `host.json` `skipped`) and session cards.
- **Stays on the worker:** heavy evidence (videos, run folders, checkpoints, datasets). The track page lists those paths; they open on the worker.

## Swap points

- **Transport:** Syncthing, or an Obsidian-Sync-style server, replaces only `sync.py` (it would fill the same `hosts/<host>/` layout and preserve mtimes natively); the hub's pull becomes a no-op.
- **Reaching the hub from the phone:** `tailscale serve` in front of the hub, plus `--allow-host <the MagicDNS name>` so the Host-header guard (the DNS-rebinding defence, same as `vibetracks/server.py`) answers it. Nothing else changes.

## Run it

The two-machine sandbox (a bare origin standing in for GitHub, win-a syncing a copy of the real kinsim loop and poking
the hub, an offline win-b, a demo session card, the hub on :4471):

```bash
/home/bam/vibetracks/scripts/remote-demo --dir /tmp/vt-remote-demo --port 4471
```

The hub on this workstation over the real share clone `~/vibetracks-share`, started or reused (log and pid under
`~/.local/state/vibetracks/`, data home `~/.local/share/vibetracks/hub`, never the dashboard's own data home):

```bash
/home/bam/vibetracks/scripts/open-hub --port 4470
```

Stop it yourself with `/home/bam/vibetracks/scripts/open-hub --port 4470 --stop` (it stops only the pid in its own pid
file). Reaching it from a phone or a worker's poke: `tailscale serve` in front of it, plus `--allow-host <the MagicDNS
name>` on the hub.

Tests:

```bash
python3 -m pytest -q /home/bam/vibetracks/tests/test_remote_acceptance.py /home/bam/vibetracks/tests/test_remote_v1_acceptance.py /home/bam/vibetracks/tests/test_remote_units.py
```

## Adding a worker machine

docs/remote/WORKER_SETUP.md is a paste-ready prompt for a Claude Code session on that machine (Windows, with a Linux
variant): clone the share, `pip install` Vibe Tracks, `python -m vibetracks.remote.sync init`, one `--once` round,
Task Scheduler (or a systemd user unit) for the loop, `hook-config`, then Zach decides on the hook line.

A config `init` writes (the keys are `vibetracks/sources.py` keys, the ones a track's `vibe-sources` declares; a key
the share supplies overrides the hub's own path for it):

```json
{"host": "win-a", "share": "C:/Users/BAM/vibetracks-share", "interval_s": 3, "heartbeat_s": 300, "receive_interval_s": 0,
 "poke_url": "http://hub.tailnet.ts.net:4470/api/poke",
 "mirror": [{"key": "kinsim_events", "path": "C:/Users/BAM/.local/share/bam_curriculum/loop_events.jsonl"},
            {"key": "rig_loop_dir", "path": "D:/rig/loop", "include": ["*.json", "*.jsonl"]}]}
```

A `--tracks-map` for hook-config maps a track to the folders its agents work in, first match wins (put the more
specific folder first): `{"kinsim": ["C:/Users/BAM/bam_ws/src/dev/bam_curriculum"], "rig": ["C:/Users/BAM/bam_ws"]}`.
A session in no listed folder still gets a card (track `null`) and shows under its machine.
