# 0003 · The home across machines: remote sessions are "current as of", never live; the hub serves the home

- **Date:** 2026-10-09
- **Status:** built on `claude/vibetracks-home-r3` (round 3), not merged
- **Source:** Zach, Oct 9 (Daily Note, "# Vibe tracks feedback"): "please also merge the git remote work into this:
  so I can start like using this across machines"; "vibe tracks doesn't care about the different agent accounts …
  you have made agents too primary. Agents work on tracks"; "I want to be able to double click to rename".

## Decision

1. **One reader of the share for the home.** `vibetracks/home/remote.py` reads what the remote layer already
   publishes (`hosts/<host>/host.json`, `sessions/*.json`, `sources.json` + `files/`; docs/remote/DESIGN.md). The
   dashboard backend finds the share at `$VIBETRACKS_SHARE` (`off` disables) or `~/vibetracks-share`; the hub passes
   its own. Only the hub pulls; everyone else reads the clone as it is and shows its age.
2. **A remote session is never live; it is current as of its host's last report.** No pid on this machine can prove
   a process on another one. `as_of` is the newer of the host's `last_sync` and the card's `last_seen`; the card is
   *current* while the host is online or stale (`hub.host_status`), the card is not ended, and its last hook event is
   within 30 min of `as_of` (the hub's existing rule for a live card). Current remote sessions are counted apart from
   "live" ("2 on other machines, win-a as of 3 min ago"), wear their host's name and a still dot (never Claude's
   blink), and a working one moves its track to Working by a new rule, `remote`, whose why says "as of".
3. **This machine first.** Its own host folder is skipped and any session id it sees locally wins over a card, so a
   workstation that is also a worker is never doubled. With no share the document is byte-identical to before.
4. **The hub serves the home.** `/` redirects to `/home/`, the same page and documents as the dock icon's, over the
   hub's workspace, its merged-sources projection and the share; `/needs` and `/roadmap` are served beside it. It is
   read-only there (`capabilities.rename: false`, no Clank links). The original hub app moved to `/hub/`, its API
   unchanged.
5. **Agents are detail of tracks.** The home counts a track's agents ("2 agents · 1 working") and drops account
   chips; sessions under tracks are off by default; the track page's tab is "Agents" (provider, model, account,
   branch/folder, join, state, worked, Open). Sessions no track matches are sidebar rows (Claude's "Other").
6. **Project identity on rename.** A project's id stays the slug of its name (B2's contract, pinned by
   tests/test_home_detail.py), so renaming moves the id; tracks keep their project because `vibe-project` resolves by
   name, then by the slug of the name against the descriptor's file stem (New project writes `<slug>.vibetrack`). The
   rename is one fenced, atomic line in the descriptor (`POST /projects/<id>/name`).

## Why

- **"as of" over a TTL guess:** the alternatives were (a) count remote cards live while `last_seen` is recent (what
  the hub app does) or (b) refuse to show them until a heartbeat proves the process. (a) would claim liveness the home
  never claims for local sessions without a pid check (docs/peps/0001 §3); (b) hides real work. "Current as of" shows
  the work with its evidence's age, the same contract the home already uses for loop freshness.
- **A redirect, not a second page:** one page everywhere is what makes "use it across machines" free: the phone, a
  laptop and the workstation read the same document shape, and the old hub app keeps working for its machine view.
- **The stem fallback, not a stable id:** making the file stem the id would have been cleaner, but the frozen B2 test
  requests a project by the slug of its name; the fallback keeps tracks attached without touching it.

## Consequences

- Session cards gain `title` and `branch` (from the transcript tail). A worker gets them after `git pull` in its clone
  and the same `setup-machine` command; older cards still read (they join by track or cwd only).
- The dashboard backend's projection reads other machines' keys when the share has them, so a loop mirrored from
  win-a feeds its track on Stable too. Clank's own dashboard pages still read this machine's sources only.
- Remote sessions carry no transcript here, so their worked time is unknown (shown as their host and last event).
- B1's frozen tests/browser/home_page.py has two checks that assert behaviour Zach removed (the home's "Other sessions"
  toggle; every live session on the home with the default display). They fail by design; tests/browser/home_reach.py
  measures the same "none is ever dropped" where sessions now live. Retiring or updating the frozen checks is Zach's
  call.
