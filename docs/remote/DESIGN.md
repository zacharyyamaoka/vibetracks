# Vibe Tracks remote: agents on several machines, one dashboard

## The problem

The dashboard's adapters read loop files (`status.json`, `loop_events.jsonl`, `runs.jsonl`, …) from paths on **this** workstation (`vibetracks/sources.py`). Agents running on other machines (the Windows box, a laptop, a cloud VM) write the same kind of files there, and the dashboard cannot see them. We want those agents to keep working exactly as they do today, and Zach to see every track, from any machine, on his phone.

## The shape

```
worker machine (win-a)                          share (a git repo on GitHub)            hub (this workstation)
  agents write their own loop files               hosts/win-a/host.json                   git pull every 3 s
  vibetracks.remote.sync (every 3 s):  ──push──▶  hosts/win-a/sources.json   ──pull──▶    restore mtimes from commits
    copy changed files into the clone             hosts/win-a/files/<key>/...             merge every sources.json
    commit hosts/win-a/ only                      hosts/win-a/sessions/<id>.json          run vibetracks.dashboard.build
  session_hook (Claude Code hook)                 hosts/win-b/...                         serve the phone app on :4470
    writes a session card into the clone
```

- **`vibetracks/remote/share.py`**: the layout (above) and its helpers.
  `hosts/<host>/host.json` is the heartbeat `{host, platform, python, vt_sync_version, last_sync, interval_s, mirrors, skipped, error}`; `sources.json` maps each source key to a path inside the host folder; `files/<key>/` holds the copies (a mirrored directory keeps its tree); `sessions/<session_id>.json` are session cards.
- **One writer per host folder.** A machine only ever stages `hosts/<its name>/`, so two machines never touch the same path: every pull is a fast-forward or a trivial rebase, and a conflict means something wrote where it must not (sync then aborts the rebase, keeps its local commit, and reports the error; it never forces).
- **`sync.py`** (per machine): mirror, heartbeat, commit, `git pull --rebase`, `git push`, every `interval_s`. It only reads the agents' files.
- **`session_hook.py`**: a Claude Code hook that records `{session_id, host, account, agent, model, cwd, track, url, …}`. The `url` is `https://claude.ai/code/<CLAUDE_CODE_BRIDGE_SESSION_ID>`, which exists only when the session has Remote Control on (`remoteControlAtStartup` in settings); otherwise the card says so and the app shows "no Remote Control link".
- **`hub.py`**: pulls, writes `<data-home>/remote-sources.json` (this machine's own `sources.json` if any, then every key the share supplies pointed into `hosts/<host>/files/`, then `dashboard_data_home` = the hub's `--data-home`), runs the ordinary `python -m vibetracks.dashboard.build` with `$VIBETRACKS_SOURCES` naming that file, and serves `/api/state`, `/api/track/<id>`, `/api/events` (SSE), `/api/health` and the app. A track is attributed to the hosts that supply at least one of its declared `vibe-sources` keys; a track none of whose keys come from the share is on the hub machine. Two hosts supplying the same key: the newer `last_sync` wins and a `duplicate_key` problem is listed.

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

The two-machine sandbox (a bare origin standing in for GitHub, win-a syncing a copy of the real kinsim loop, an offline win-b, a demo session card, the hub on :4471):

```bash
/home/bam/vibetracks-remote/scripts/remote-demo --dir /tmp/vt-remote-demo --port 4471
```

The hub on this workstation over a real share clone:

```bash
PYTHONPATH=/home/bam/vibetracks-remote python3 -m vibetracks.remote.hub --share /home/bam/vt-share --workspace /home/bam/vibetracks-remote/workspace --data-home /home/bam/.local/share/vibetracks-remote --port 4470
```

(Its `--data-home` is its own folder, never the dashboard's `~/.local/share/vibetracks/`. Tests: `python3 -m pytest -q /home/bam/vibetracks-remote/tests/test_remote_acceptance.py /home/bam/vibetracks-remote/tests/test_remote_units.py`.)

A worker on Linux, with this config at `/home/bam/vt-sync.json`:

```json
{"host": "laptop", "share": "/home/bam/vt-share", "interval_s": 3, "heartbeat_s": 300,
 "mirror": [{"key": "kinsim_status", "path": "/home/bam/.local/share/bam_curriculum/status.json"},
            {"key": "kinsim_events", "path": "/home/bam/.local/share/bam_curriculum/loop_events.jsonl"},
            {"key": "rig_loop_dir", "path": "/home/bam/rig/loop", "include": ["*.json", "*.jsonl"]}]}
```

```bash
PYTHONPATH=/home/bam/vibetracks-remote python3 -m vibetracks.remote.sync --config /home/bam/vt-sync.json
```

The keys are `vibetracks/sources.py` keys (the ones a track's `vibe-sources` declares). A key the share supplies overrides the hub's own path for it.

## Adding a real Windows machine

1. **Clone two repos with GitHub Desktop** (File → Clone repository): the share (e.g. `zacharyyamaoka/vt-share`, private) into `C:\Users\BAM\vt-share`, and Vibe Tracks into `C:\Users\BAM\vibetracks`. GitHub Desktop's Git Credential Manager then authenticates the clone's `git push`; do not use `gh` or SSH keys on that box.
2. **Python once** (PowerShell 5.1). `vibetracks/__init__.py` imports PyYAML, so the worker needs it even though sync itself is stdlib:

   ```powershell
   py -3 -m pip install --user PyYAML
   ```

3. **Write the config** `C:\Users\BAM\vt-sync.json` (forward slashes are fine in JSON):

   ```json
   {"host": "win-a", "share": "C:/Users/BAM/vt-share", "interval_s": 3, "heartbeat_s": 300,
    "mirror": [{"key": "kinsim_events", "path": "C:/Users/BAM/.local/share/bam_curriculum/loop_events.jsonl"}]}
   ```

4. **Try one round** (prints `{"committed": …, "pushed": …, "pulled": […], "error": null}`):

   ```powershell
   $env:PYTHONPATH = "C:\Users\BAM\vibetracks"; py -3 -m vibetracks.remote.sync --config C:\Users\BAM\vt-sync.json --once
   ```

5. **Run it at logon with Task Scheduler** (one line; `pyw` runs it without a console window):

   ```powershell
   schtasks /Create /F /SC ONLOGON /TN "Vibe Tracks sync" /TR "cmd /c set PYTHONPATH=C:\Users\BAM\vibetracks& pyw -3 -m vibetracks.remote.sync --config C:\Users\BAM\vt-sync.json"
   ```

   Start it now without logging out: `schtasks /Run /TN "Vibe Tracks sync"`. The machine appears on the hub's Machines tab within one pull.

6. **Add the session hook** to that account's Claude Code `settings.json` (`%USERPROFILE%\.claude\settings.json`, or the account's `CLAUDE_CONFIG_DIR`). It writes a card on every prompt, after every turn and at session end; sync commits it on its next round. Turn on Remote Control at startup if you want the hub's "Talk to agent ↗" link to work:

   ```json
   {
     "remoteControlAtStartup": true,
     "hooks": {
       "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "cmd /c set PYTHONPATH=C:\\Users\\BAM\\vibetracks& py -3 -m vibetracks.remote.session_hook --share C:\\Users\\BAM\\vt-share --host win-a --tracks-map C:\\Users\\BAM\\vt-tracks.json"}]}],
       "Stop":             [{"hooks": [{"type": "command", "command": "cmd /c set PYTHONPATH=C:\\Users\\BAM\\vibetracks& py -3 -m vibetracks.remote.session_hook --share C:\\Users\\BAM\\vt-share --host win-a --tracks-map C:\\Users\\BAM\\vt-tracks.json"}]}],
       "SessionEnd":       [{"hooks": [{"type": "command", "command": "cmd /c set PYTHONPATH=C:\\Users\\BAM\\vibetracks& py -3 -m vibetracks.remote.session_hook --share C:\\Users\\BAM\\vt-share --host win-a --tracks-map C:\\Users\\BAM\\vt-tracks.json"}]}]
     }
   }
   ```

   `C:\Users\BAM\vt-tracks.json` maps a track to the folders its agents work in, first match wins (put the more specific folder first): `{"kinsim": ["C:\\Users\\BAM\\bam_ws\\src\\dev\\bam_curriculum"], "rig": ["C:\\Users\\BAM\\bam_ws"]}`. Use `--track <id>` instead when a whole account works on one track. On Linux the command is `PYTHONPATH=/home/bam/vibetracks-remote python3 -m vibetracks.remote.session_hook --share /home/bam/vt-share --host bam-GPU --track kinsim`. The hook never fails a session: bad input writes nothing and exits 0.
