# Vibe Tracks worker setup (paste this whole file into Claude Code on the other machine)

You are setting this machine up as a **Vibe Tracks worker**: a small sync process copies this machine's session cards
(and later its loop files) into a git "share" on GitHub, and Zach's hub on his workstation reads them. Do the steps in
order, check each one, and stop and tell Zach when one fails. Do not change anything outside `C:\Users\BAM\`.

## What is true on this box (Windows)

- Windows 11. Anything Zach pastes himself is **PowerShell 5.1** (one command per line, no `&&`). You run commands in
  **Git Bash**.
- Python is `C:\Users\BAM\miniconda3\python` (3.11.5); `pythonw` sits beside it. Set `PYTHONIOENCODING=utf-8` for every
  python you run (the console is cp1252).
- git 2.41, `core.autocrlf=true` system-wide. GitHub auth works **only** through GitHub Desktop's credential manager:
  no `gh`, no SSH key. If git asks for credentials or fails with 401/403, stop and ask Zach to sign into GitHub Desktop.
- Claude Desktop is an MSIX app: it virtualizes `%APPDATA%` and `%LOCALAPPDATA%` but **not** the home folder. Keep
  every file under `C:\Users\BAM\`. If you are running inside Claude Desktop (not the CLI in a terminal), a
  `pip install --user` you run lands in the app's private copy of `%APPDATA%`, which Task Scheduler cannot see: in
  that case ask Zach to paste the pip line of step 2 into his own PowerShell window instead.
- Long heredocs and backslashes in Bash heredocs get mangled: write files with the Write tool, not `cat <<EOF`.

## Steps

1. **Clone the share** (skip if `C:/Users/BAM/vibetracks-share/.git` exists):

   ```bash
   git clone https://github.com/zacharyyamaoka/vibetracks-share C:/Users/BAM/vibetracks-share
   ```

2. **Install Vibe Tracks** (public repo; brings PyYAML):

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python -m pip install --user "vibetracks @ git+https://github.com/zacharyyamaoka/vibetracks@main"
   ```

   Check: `/c/Users/BAM/miniconda3/python -m vibetracks.remote.sync --help` prints usage.

3. **Choose the host name**: the lower-case hostname (`hostname | tr A-Z a-z`), or what Zach says (e.g. `win-a`).
   Letters, digits, `.`, `_`, `-` only. Below it is `HOST`.

4. **Write the sync config**, with no mirrored files at first (session cards and the heartbeat only) unless Zach names
   loop files (then add `--mirror KEY=PATH` per file, KEY being the `vibetracks/sources.py` key he gives you). Add
   `--poke-url http://<hub>:4470/api/poke` only if Zach gives you the hub's address:

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python -m vibetracks.remote.sync init --share C:/Users/BAM/vibetracks-share --host HOST --config C:/Users/BAM/vibetracks-sync.json
   ```

   It checks the clone answers `git ls-remote`, writes the config, sets the clone's `user.name`/`user.email` to the
   host if unset, and prints the next commands.

5. **One round, then confirm the push landed**:

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python -m vibetracks.remote.sync --config C:/Users/BAM/vibetracks-sync.json --once
   git -C C:/Users/BAM/vibetracks-share fetch -q && git -C C:/Users/BAM/vibetracks-share log origin/main -1 --format='%h %an %ar %s'
   ```

   Expect `"pushed": true, "error": null` and a commit `vt-sync HOST: …` by HOST.

6. **Run it at logon** with Task Scheduler (`pythonw`: no console window; `--log` is its only output):

   ```bash
   schtasks //Create //SC ONLOGON //TN "Vibe Tracks sync" //TR "C:\Users\BAM\miniconda3\pythonw.exe -m vibetracks.remote.sync --config C:/Users/BAM/vibetracks-sync.json --log C:/Users/BAM/vibetracks-sync.log" //F
   schtasks //Run //TN "Vibe Tracks sync"
   ```

   (Git Bash needs `//` for schtasks switches; in PowerShell they are `/Create`, `/SC`, …) Check after ~10 s:
   `schtasks //Query //TN "Vibe Tracks sync"` says Running, and `C:/Users/BAM/vibetracks-sync.log` has a
   `sync loop for HOST …` line and no `error:` lines.

7. **Session hook config**:

   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/BAM/miniconda3/python -m vibetracks.remote.sync hook-config --share C:/Users/BAM/vibetracks-share --host HOST
   ```

   It writes `C:/Users/BAM/.vibetracks/remote.json` and prints one guarded line, of this shape:
   `[ ! -f "$HOME/.vibetracks/remote.json" ] || exec "C:/Users/BAM/miniconda3/python.exe" "<…>/vibetracks/remote/hooks/vibetracks_session.py"`.
   **Ask Zach before adding it** to `~/.claude/settings.json`: that file is shared with his other machines through his
   vault. Show him the line; it goes in three places, `UserPromptSubmit`, `Stop` and `SessionEnd`, each as
   `{"hooks": [{"type": "command", "command": "<the line>"}]}` (hook-config prints that JSON too). The guard makes it a
   no-op on any machine without `~/.vibetracks/remote.json`, but the python and script paths in it are this machine's,
   so a second worker with a different layout needs Zach's decision. Edit with the Edit tool, keep the JSON valid.

8. **Remote Control**: `remoteControlAtStartup` is already `true` in the shared settings. Confirm with
   `grep remoteControlAtStartup ~/.claude/settings.json`. With it on, the session card carries a
   `https://claude.ai/code/…` link and the hub shows **Talk to agent ↗**. After the hook is in, the next prompt in any
   session writes `C:/Users/BAM/vibetracks-share/hosts/HOST/sessions/<id>.json` and the next sync round pushes it.

9. **Report back to Zach**, in one short message: the host name; the last push (`git log origin/main -1` line from
   step 5, or a newer one); the task status (`schtasks //Query`); whether the hook line is in settings.json (and
   whether a card appeared under `hosts/HOST/sessions/`); anything that failed and what you need from him.

## Linux variant (instead of steps 2 and 6)

```bash
python3 -m pip install --user "vibetracks @ git+https://github.com/zacharyyamaoka/vibetracks@main"
mkdir -p ~/.config/systemd/user
printf '[Unit]\nDescription=Vibe Tracks sync\n\n[Service]\nExecStart=%s -m vibetracks.remote.sync --config %s/vibetracks-sync.json --log %s/vibetracks-sync.log\nRestart=always\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n' "$(command -v python3)" "$HOME" "$HOME" > ~/.config/systemd/user/vibetracks-sync.service
systemctl --user daemon-reload && systemctl --user enable --now vibetracks-sync.service
systemctl --user status vibetracks-sync.service --no-pager
```

Steps 1, 3–5, 7–9 are the same with `python3` and paths under `$HOME`; hook-config prints `python3` in the line.
