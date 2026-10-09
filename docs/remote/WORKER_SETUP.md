# Vibe Tracks worker setup (paste this whole file into Claude Code on the other machine)

You are setting this machine up as a **Vibe Tracks worker**: a small sync process copies this machine's session cards
(and later its loop files) into a git "share" on GitHub, and Zach's hub on his workstation reads them. Do the steps in
order, check each one, and stop and tell Zach when one fails. Keep every file you create under `C:\Users\BAM\`.

## What is true on this box (Windows)

- Windows 11. Anything Zach pastes himself is **PowerShell 5.1** (one command per line, no `&&`). You run commands in
  **Git Bash**.
- The base Python is `C:\Users\BAM\miniconda3\python` (3.11.5). Set `PYTHONIOENCODING=utf-8` for every python you run
  (the console is cp1252).
- git 2.41, `core.autocrlf=true` system-wide (the share's `.gitattributes` turns conversion off for its files).
  GitHub auth works **only** through GitHub Desktop's credential manager: no `gh`, no SSH key. If git asks for
  credentials or fails with 401/403, stop and ask Zach to sign into GitHub Desktop.
- Claude Desktop is an MSIX app: it virtualizes `%APPDATA%` and `%LOCALAPPDATA%` but **not** the home folder. That is
  why everything below lives in `C:\Users\BAM\.vibetracks\` (a venv, not `pip install --user`, whose files would land
  in the app's private `%APPDATA%` where Task Scheduler cannot see them).
- Long heredocs and backslashes in Bash heredocs get mangled: write files with the Write tool, not `cat <<EOF`.

Below, `PY` means `C:/Users/BAM/.vibetracks/venv/Scripts/python.exe` and `PYW` means the `pythonw.exe` beside it.

## Steps

1. **Clone the share** (skip if `C:/Users/BAM/vibetracks-share/.git` exists):

   ```bash
   git clone https://github.com/zacharyyamaoka/vibetracks-share C:/Users/BAM/vibetracks-share
   ```

2. **Install Vibe Tracks into its own venv** (public repo; brings PyYAML). `REF` is `main` unless Zach names a branch:

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python -m venv C:/Users/BAM/.vibetracks/venv
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m pip install "vibetracks @ git+https://github.com/zacharyyamaoka/vibetracks@REF"
   ```

   Check: `PY -m vibetracks.remote.sync hook-config --help` prints usage (that subcommand is v1; if it is missing,
   the REF is too old: tell Zach).

3. **Choose the host name**: the lower-case hostname (`hostname | tr A-Z a-z`), or what Zach says (e.g. `win-a`).
   Letters, digits, `.`, `_`, `-` only. Below it is `HOST`.

4. **Write the sync config**, with no mirrored files at first (session cards and the heartbeat only) unless Zach names
   loop files (then add `--mirror KEY=PATH` per file, KEY being the `vibetracks/sources.py` key he gives you). Add
   `--poke-url http://<hub>:4470/api/poke` only if Zach gives you the hub's address:

   ```bash
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m vibetracks.remote.sync init --share C:/Users/BAM/vibetracks-share --host HOST --config C:/Users/BAM/.vibetracks/sync.json
   ```

   It checks the clone answers `git ls-remote`, writes the config, sets the clone's `user.name`/`user.email` to the
   host if unset, and prints the next commands.

5. **One round, then confirm the push landed**:

   ```bash
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m vibetracks.remote.sync --config C:/Users/BAM/.vibetracks/sync.json --once
   git -C C:/Users/BAM/vibetracks-share fetch -q && git -C C:/Users/BAM/vibetracks-share log origin/main -1 --format='%h %an %ar %s'
   ```

   Expect `"pushed": true, "error": null` and a commit `vt-sync HOST: …` by HOST.

6. **Run it at logon** with Task Scheduler (`pythonw`: no console window; `--log` is its only output):

   ```bash
   schtasks //Create //SC ONLOGON //TN "Vibe Tracks sync" //TR "C:\Users\BAM\.vibetracks\venv\Scripts\pythonw.exe -m vibetracks.remote.sync --config C:/Users/BAM/.vibetracks/sync.json --log C:/Users/BAM/.vibetracks/sync.log" //F
   schtasks //Run //TN "Vibe Tracks sync"
   ```

   (Git Bash needs `//` for schtasks switches; in PowerShell they are `/Create`, `/SC`, …) Check after ~10 s:
   `schtasks //Query //TN "Vibe Tracks sync"` says Running, and `C:/Users/BAM/.vibetracks/sync.log` has a
   `sync loop for HOST …` line and no `error:` lines. An idle worker is quiet on the network: it pushes only when a
   file or session card changed, plus one heartbeat every 5 minutes.

7. **Session hook**:

   ```bash
   PYTHONIOENCODING=utf-8 C:/Users/BAM/.vibetracks/venv/Scripts/python.exe -m vibetracks.remote.sync hook-config --share C:/Users/BAM/vibetracks-share --host HOST
   ```

   It writes `C:/Users/BAM/.vibetracks/remote.json` and the launcher `C:/Users/BAM/.vibetracks/hook` (this machine's
   python and hook script), and prints the one line that goes in settings.json. That line is **the same on every
   machine** and names no paths: `[ ! -x "$HOME/.vibetracks/hook" ] || exec "$HOME/.vibetracks/hook"`. On a machine
   without the launcher it does nothing.
   **Ask Zach before adding it** to `~/.claude/settings.json`: that file is shared with his other machines through his
   vault. If he says yes, add it under `UserPromptSubmit`, `Stop` and `SessionEnd`, each as
   `{"hooks": [{"type": "command", "command": "<the line>"}]}` (hook-config prints that JSON). Edit with the Edit tool
   and keep the JSON valid. If the line is already there (another machine added it), you are done: the launcher alone
   switches it on here.

8. **Remote Control**: `remoteControlAtStartup` is already `true` in the shared settings. Confirm with
   `grep remoteControlAtStartup ~/.claude/settings.json`. With it on, the session card carries a
   `https://claude.ai/code/…` link and the hub shows **Talk to agent ↗**. After the hook is in, the next prompt in any
   session writes `C:/Users/BAM/vibetracks-share/hosts/HOST/sessions/<id>.json` and the next sync round pushes it.

9. **Report back to Zach**, in one short message: the host name; the last push (`git log origin/main -1` line from
   step 5, or a newer one); the task status (`schtasks //Query`); whether the hook line is in settings.json (and
   whether a card appeared under `hosts/HOST/sessions/`); anything that failed and what you need from him.

## Linux variant (instead of steps 2 and 6)

```bash
python3 -m venv ~/.vibetracks/venv
~/.vibetracks/venv/bin/python -m pip install "vibetracks @ git+https://github.com/zacharyyamaoka/vibetracks@REF"
mkdir -p ~/.config/systemd/user
printf '[Unit]\nDescription=Vibe Tracks sync\n\n[Service]\nExecStart=%s -m vibetracks.remote.sync --config %s/.vibetracks/sync.json --log %s/.vibetracks/sync.log\nRestart=always\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n' "$HOME/.vibetracks/venv/bin/python" "$HOME" "$HOME" > ~/.config/systemd/user/vibetracks-sync.service
systemctl --user daemon-reload && systemctl --user enable --now vibetracks-sync.service
systemctl --user status vibetracks-sync.service --no-pager
```

Steps 1, 3–5, 7–9 are the same with `~/.vibetracks/venv/bin/python` and paths under `$HOME`.
