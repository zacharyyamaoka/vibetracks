# Vibe Tracks worker setup (for the Claude Code session on the other machine)

You are setting this machine up as a **Vibe Tracks worker**: a small sync process copies this machine's session cards
(and later its loop files) into a git "share" on GitHub, and Zach's hub on his workstation reads them. One command does
it, and the same command updates the machine later. Run it, read its lines, and stop and tell Zach when a step fails.

**Two repos, and they are different things.** `zacharyyamaoka/vibetracks` is the **app**: public code, cloned to
`~/vibetracks`, installed editable into a venv. `zacharyyamaoka/vibetracks-share` is the **database**: private, small
synced files, one folder per machine (`hosts/<host>/`), cloned to `~/vibetracks-share`. Like Obsidian (the app) and a
vault (your data).

## What is true on the Windows box

- Windows 11. Anything Zach pastes himself is **PowerShell 5.1** (one command per line, no `&&`). You run commands in
  **Git Bash**.
- The base Python is `C:\Users\BAM\miniconda3\python` (3.11.5). Set `PYTHONIOENCODING=utf-8` for every python you run
  (the console is cp1252).
- git 2.41, `core.autocrlf=true` system-wide (the share's `.gitattributes` turns conversion off for its files).
  GitHub auth works **only** through GitHub Desktop's credential manager: no `gh`, no SSH key. If git asks for
  credentials or fails with 401/403, stop and ask Zach to sign into GitHub Desktop.
- Claude Desktop is an MSIX app: it virtualizes `%APPDATA%` and `%LOCALAPPDATA%` but **not** the home folder. That is
  why everything lives in `C:\Users\BAM\.vibetracks\` (a venv, not `pip install --user`, whose files would land in
  the app's private `%APPDATA%` where Task Scheduler cannot see them).
- Long heredocs and backslashes in Bash heredocs get mangled: write files with the Write tool, not `cat <<EOF`.

## Steps

1. **Clone the app** (skip if `~/vibetracks/.git` exists; then `git -C ~/vibetracks pull` instead):

   ```bash
   git clone https://github.com/zacharyyamaoka/vibetracks ~/vibetracks
   ```

2. **Choose the host name**: the lower-case hostname (`hostname | tr A-Z a-z`), or what Zach says (e.g. `win-a`).
   Letters, digits, `.`, `_`, `-` only.

3. **Run the setup** (Windows, Git Bash):

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python ~/vibetracks/scripts/setup-machine --host win-a
   ```

   Linux or macOS:

   ```bash
   python3 ~/vibetracks/scripts/setup-machine --host HOST
   ```

   Add `--mirror KEY=PATH` per loop file only if Zach names loop files (KEY is the `vibetracks/sources.py` key he
   gives you), and `--poke-url http://<hub>:4470/api/poke` only if he gives you the hub's address. `--dry-run` prints
   every command without changing anything. What it does, one line each (`✓` done now, `·` already done):

   - **venv / install**: `~/.vibetracks/venv`, then `pip install -e ~/vibetracks` (editable: a `git pull` in the
     clone updates the code).
   - **share**: clones `https://github.com/zacharyyamaoka/vibetracks-share` into `~/vibetracks-share`, or checks an
     existing clone's origin. No credentials: it prints the GitHub Desktop sign-in hint and stops.
   - **config**: `sync init` into `~/.vibetracks/sync.json` (kept as it is unless `--mirror`/`--poke-url` change it).
   - **round**: one `sync --once`; prints the `origin/main` line, and fails unless this host's folder reached origin.
   - **autostart**: Windows: Task Scheduler task "Vibe Tracks sync" at logon (`pythonw`, log in
     `~/.vibetracks/sync.log`), started now and checked Running. Linux: systemd user unit `vibetracks-sync.service`.
     macOS: prints the command to run at login. `--no-autostart` skips it.
   - **hook-config / hook**: writes `~/.vibetracks/remote.json` and the launcher `~/.vibetracks/hook`, then checks
     `~/.claude/settings.json` for the shared hook line.

4. **Ask Zach about the hook line** if the run printed `NEEDS ZACH: add the hook line …`. The line is the same on every
   machine and names no paths: `[ ! -x "$HOME/.vibetracks/hook" ] || exec "$HOME/.vibetracks/hook"`, a no-op where
   the launcher is absent. `~/.claude/settings.json` is shared with his other machines through his vault, so it is his
   call. If he says yes, rerun the same command with `--install-hook`: it adds the line under `UserPromptSubmit`,
   `Stop` and `SessionEnd`, edits the symlink's target (never replaces the link), and backs the file up to
   `~/.vibetracks/settings.json.bak-<time>` first. If the line is already there (another machine added it), the run
   says `· hook: already in settings.json` and the launcher alone switches it on here.

5. **Remote Control**: `remoteControlAtStartup` is already `true` in the shared settings. Confirm with
   `grep remoteControlAtStartup ~/.claude/settings.json`. With it on, the session card carries a
   `https://claude.ai/code/…` link and the hub shows **Talk to agent ↗**. After the hook is in, the next prompt in any
   session writes `~/vibetracks-share/hosts/HOST/sessions/<id>.json` and the next sync round pushes it.

6. **Report back to Zach**: paste the run's `Summary for Zach` block (host, last push, autostart, hook, anything that
   needs him), plus whether a card appeared under `hosts/HOST/sessions/`.

**Updating later**: `git -C ~/vibetracks pull`, then the same setup command. It reinstalls only when needed and
re-checks every step.

## Fallback: the steps by hand

Only when the script fails partway and Zach wants it finished by hand. Below, `PY` means
`C:/Users/BAM/.vibetracks/venv/Scripts/python.exe` (Linux: `~/.vibetracks/venv/bin/python`) and `HOST` the host name.

1. **Clone the share** (skip if `C:/Users/BAM/vibetracks-share/.git` exists):

   ```bash
   git clone https://github.com/zacharyyamaoka/vibetracks-share C:/Users/BAM/vibetracks-share
   ```

2. **Install Vibe Tracks into its own venv**, editable from the app clone (brings PyYAML):

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python -m venv C:/Users/BAM/.vibetracks/venv
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m pip install -e C:/Users/BAM/vibetracks
   ```

   Check: `PY -m vibetracks.remote.sync hook-config --help` prints usage.

3. **Write the sync config** (add `--mirror KEY=PATH` and `--poke-url` as above):

   ```bash
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m vibetracks.remote.sync init --share C:/Users/BAM/vibetracks-share --host HOST --config C:/Users/BAM/.vibetracks/sync.json
   ```

   It checks the clone answers `git ls-remote`, writes the config, sets the clone's `user.name`/`user.email` to the
   host if unset, and prints the next commands.

4. **One round, then confirm the push landed**:

   ```bash
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m vibetracks.remote.sync --config C:/Users/BAM/.vibetracks/sync.json --once
   git -C C:/Users/BAM/vibetracks-share log origin/main -1 --format='%h %an %cr %s'
   ```

   Expect `"pushed": true, "error": null` and a commit `vt-sync HOST: …` by HOST.

5. **Run it at logon** with Task Scheduler (`pythonw`: no console window; `--log` is its only output):

   ```bash
   schtasks //Create //SC ONLOGON //TN "Vibe Tracks sync" //TR "C:\Users\BAM\.vibetracks\venv\Scripts\pythonw.exe -m vibetracks.remote.sync --config C:/Users/BAM/.vibetracks/sync.json --log C:/Users/BAM/.vibetracks/sync.log" //F
   schtasks //Run //TN "Vibe Tracks sync"
   ```

   (Git Bash needs `//` for schtasks switches; in PowerShell they are `/Create`, `/SC`, …) Check after ~10 s:
   `schtasks //Query //TN "Vibe Tracks sync"` says Running, and `C:/Users/BAM/.vibetracks/sync.log` has a
   `sync loop for HOST …` line and no `error:` lines. An idle worker is quiet on the network: it pushes only when a
   file or session card changed, plus one heartbeat every 5 minutes.

   Linux instead:

   ```bash
   mkdir -p ~/.config/systemd/user
   printf '[Unit]\nDescription=Vibe Tracks sync\n\n[Service]\nExecStart=%s -m vibetracks.remote.sync --config %s/.vibetracks/sync.json --log %s/.vibetracks/sync.log\nRestart=always\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n' "$HOME/.vibetracks/venv/bin/python" "$HOME" "$HOME" > ~/.config/systemd/user/vibetracks-sync.service
   systemctl --user daemon-reload
   systemctl --user enable --now vibetracks-sync.service
   ```

6. **Session hook**:

   ```bash
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m vibetracks.remote.sync hook-config --share C:/Users/BAM/vibetracks-share --host HOST
   ```

   It writes `C:/Users/BAM/.vibetracks/remote.json` and the launcher `C:/Users/BAM/.vibetracks/hook`, and prints the
   line and its settings.json JSON. **Ask Zach before adding it**; if he says yes, add it under `UserPromptSubmit`,
   `Stop` and `SessionEnd`, each as `{"hooks": [{"type": "command", "command": "<the line>"}]}`, with the Edit tool on
   the symlink's target, keeping the JSON valid.
