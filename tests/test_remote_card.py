"""Session cards in the Vibe Tracks vault (vibetracks/remote/card.py) and the plugin hook that writes them.

Hermetic: every test passes its own environment and home folder, and the hook runs with HOME, USERPROFILE, APPDATA
and XDG_CONFIG_HOME all inside a temp folder. WHY all four: Windows' Path.home() reads USERPROFILE, not HOME, and a
test that set only HOME wrote into the real home on win-a (2026-10-16).

    python3 -m unittest tests.test_remote_card      (from the repo root)
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibetracks.home import remote as home_remote
from vibetracks.remote import card

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "hooks" / "hooks.json"
SESSION = "5e55e55e-0000-1111-2222-333344445555"


def marker(machines: dict[str, str] | None = None) -> str:
    lines = ["---"]
    if machines:
        lines.append("machines:")
        lines += [f"  {key}: {value}" for key, value in machines.items()]
    lines += ["---", "", "# Vibe Tracks share", ""]
    return "\n".join(lines)


class VaultCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-card-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.appdata = self.tmp / "appdata"
        self.home.mkdir()
        self.vault = self.tmp / "Vibe Tracks"
        self.vault.mkdir()
        (self.vault / card.MARKER).write_text(marker({socket.gethostname().lower(): "win-a"}), encoding="utf-8")
        self.brain = self.tmp / "Zach Brain"
        self.brain.mkdir()
        self.environ = {"APPDATA": str(self.appdata), "XDG_CONFIG_HOME": str(self.tmp / "xdg")}

    def register(self, *vaults: Path, registry: Path | None = None) -> None:
        registry = registry or self.appdata / "obsidian" / "obsidian.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        entries = {f"id{index}": {"path": str(vault), "ts": 1, "open": True} for index, vault in enumerate(vaults)}
        registry.write_text(json.dumps({"vaults": entries}), encoding="utf-8")

    def event(self, name: str = "UserPromptSubmit", transcript: Path | None = None) -> dict:
        return {"session_id": SESSION, "cwd": str(self.home), "hook_event_name": name,
                "transcript_path": str(transcript) if transcript else None}


class FindingTheVault(VaultCase):
    def test_the_vault_is_found_in_obsidians_own_list_by_its_marker_note(self) -> None:
        self.register(self.brain, self.vault)
        self.assertEqual(card.find_share(self.environ, self.home), self.vault)

    def test_the_linux_registry_works_too(self) -> None:
        self.register(self.vault, registry=self.tmp / "xdg" / "obsidian" / "obsidian.json")
        self.assertEqual(card.find_share({"XDG_CONFIG_HOME": str(self.tmp / "xdg")}, self.home), self.vault)

    def test_no_marked_vault_means_no_share(self) -> None:
        self.register(self.brain)
        self.assertIsNone(card.find_share(self.environ, self.home))

    def test_the_environment_overrides_and_off_disables(self) -> None:
        self.register(self.vault)
        self.assertEqual(card.find_share({**self.environ, "VIBETRACKS_SHARE": str(self.brain)}, self.home), self.brain)
        self.assertIsNone(card.find_share({**self.environ, "VIBETRACKS_SHARE": "off"}, self.home))

    def test_the_host_name_comes_from_the_marker_note_then_the_hostname(self) -> None:
        self.assertEqual(card.host_name(self.vault, {}, hostname="Other-Box"), "other-box")
        self.assertEqual(card.host_name(self.vault, {}, hostname=socket.gethostname()), "win-a")
        self.assertEqual(card.host_name(self.vault, {"VIBETRACKS_HOST": "lab"}, hostname="x"), "lab")
        self.assertEqual(card.host_name(None, {}, hostname="My PC!"), "my-pc")


class TheNoteFormat(VaultCase):
    def test_a_rendered_card_reads_back_exactly(self) -> None:
        fields = {key: None for key in card.FIELDS}
        fields.update(session_id=SESSION, host="win-a", title='a "quoted" title: with a colon', ended=False,
                      url="https://claude.ai/code/abc", cwd="C:\\Users\\BAM\\Documents\\Zach Brain")
        path = self.vault / "c.md"
        path.write_text(card.render_card(fields), encoding="utf-8")
        self.assertEqual(card.read_card(path), fields)

    def test_what_obsidians_property_editor_writes_back_still_reads(self) -> None:
        text = "---\nmachines:\n  desktop-ab12cd3: win-a\n  'ubuntu-ws': workstation\nnote: plain words\n---\nbody\n"
        self.assertEqual(card.parse_properties(text),
                         {"machines": {"desktop-ab12cd3": "win-a", "ubuntu-ws": "workstation"}, "note": "plain words"})
        self.assertEqual(card.parse_properties("no frontmatter"), {})
        self.assertEqual(card.parse_properties("---\nkey: 1\n"), {})  # never closed: not frontmatter


class WritingCards(VaultCase):
    def test_a_card_is_written_and_rewritten_only_when_it_changed(self) -> None:
        self.register(self.vault)
        transcript = self.tmp / "t.jsonl"
        transcript.write_text("\n".join(json.dumps(row) for row in (
            {"type": "custom-title", "customTitle": "set up win-a"},
            {"type": "user", "gitBranch": "remote-vault"},
            {"type": "assistant", "message": {"model": "claude-opus-5-5"}})) + "\n", encoding="utf-8")
        environ = {**self.environ, "CLAUDE_CODE_BRIDGE_SESSION_ID": "bridge123"}
        path = card.record(self.event(transcript=transcript), environ, self.home, now=1000.0,
                           hostname=socket.gethostname())
        self.assertEqual(path, self.vault / "hosts" / "win-a" / "sessions" / f"{SESSION}.md")
        data = card.read_card(path)
        self.assertEqual((data["host"], data["title"], data["branch"], data["model"], data["url"], data["event"],
                          data["ended"]),
                         ("win-a", "set up win-a", "remote-vault", "claude-opus-5-5",
                          "https://claude.ai/code/bridge123", "UserPromptSubmit", False))
        self.assertIsNone(card.record(self.event(transcript=transcript), environ, self.home, now=1010.0,
                                      hostname=socket.gethostname()))
        self.assertEqual(card.read_card(path)["last_seen"], card.iso_utc(1000.0))
        self.assertEqual(card.record(self.event("Stop", transcript), environ, self.home, now=1011.0,
                                     hostname=socket.gethostname()), path)
        self.assertEqual(card.record(self.event("Stop", transcript), environ, self.home, now=1050.0,
                                     hostname=socket.gethostname()), path)
        ended = card.read_card(card.record(self.event("SessionEnd"), environ, self.home, now=1051.0,
                                           hostname=socket.gethostname()))
        self.assertEqual((ended["ended"], ended["started_at"], ended["title"]), (True, card.iso_utc(1000.0),
                                                                                "set up win-a"))

    def test_no_vault_or_no_session_id_writes_nothing(self) -> None:
        self.assertIsNone(card.record(self.event(), self.environ, self.home, now=1.0))
        self.register(self.vault)
        self.assertIsNone(card.record({"cwd": "x"}, self.environ, self.home, now=1.0))
        self.assertFalse((self.vault / "hosts").exists())


class ThePluginHook(VaultCase):
    """The exact command in hooks/hooks.json, through the shell Claude Code uses (Git Bash on Windows)."""

    def run_hook(self, event_name: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        command = hooks[event_name][0]["hooks"][0]["command"]
        # WHY which(): on Windows a bare "bash" resolves to WSL's System32\bash.exe before PATH; Claude Code uses Git Bash.
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("no bash on PATH")
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "APPDATA": str(self.appdata),
               "XDG_CONFIG_HOME": str(self.tmp / "xdg"), "CLAUDE_PLUGIN_ROOT": str(REPO),
               "CLAUDE_CODE_BRIDGE_SESSION_ID": "bridge456"}
        env.pop("VIBETRACKS_SHARE", None)
        env.pop("VIBETRACKS_HOST", None)
        return subprocess.run([bash, "-c", command], input=json.dumps(payload).encode(), capture_output=True,
                              cwd=cwd, env=env, timeout=60)

    def test_every_event_runs_the_card_writer_from_the_plugin_root(self) -> None:
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "Stop", "SessionEnd"})
        for groups in hooks.values():
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/vibetracks/remote/card.py", groups[0]["hooks"][0]["command"])

    def test_the_hook_writes_a_card_from_a_home_that_holds_the_clone(self) -> None:
        self.register(self.brain, self.vault)
        (self.home / "vibetracks").mkdir()  # the clone root that shadowed the package on win-a (2026-10-16)
        result = self.run_hook("UserPromptSubmit", self.event(), cwd=self.home)
        self.assertEqual((result.returncode, result.stdout), (0, b""), result.stderr)
        data = card.read_card(self.vault / "hosts" / "win-a" / "sessions" / f"{SESSION}.md")
        self.assertIsNotNone(data, result.stderr)
        self.assertEqual((data["url"], data["event"]), ("https://claude.ai/code/bridge456", "UserPromptSubmit"))
        self.assertEqual(list((self.vault / "hosts" / "win-a" / "sessions").iterdir()),
                         [self.vault / "hosts" / "win-a" / "sessions" / f"{SESSION}.md"])  # no .tmp left behind

    def test_a_machine_without_the_vault_gets_silence(self) -> None:
        self.register(self.brain)
        result = self.run_hook("Stop", self.event("Stop"), cwd=self.home)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertFalse((self.brain / "hosts").exists())


class TheHomeReadsTheVault(VaultCase):
    def test_vault_cards_without_a_heartbeat_judge_their_host_by_the_newest_card(self) -> None:
        self.register(self.vault)
        card.record(self.event(), self.environ, self.home, now=10_000.0, hostname=socket.gethostname())
        view = home_remote.read_share(self.vault, 10_060.0, own={"workstation"})
        self.assertEqual([(h["host"], h["status"], h["last_sync"], h["sessions_current"]) for h in view["hosts"]],
                         [("win-a", "online", card.iso_utc(10_000.0), 1)])
        self.assertEqual([(c.session, c.word) for c in view["cards"]], [(SESSION, "working")])
        later = home_remote.read_share(self.vault, 10_000.0 + 2 * 3600, own={"workstation"})
        self.assertEqual([(h["status"], h["sessions_current"]) for h in later["hosts"]], [("offline", 0)])
        self.assertEqual(home_remote.read_share(self.vault, 10_060.0, own={"win-a"})["hosts"], [])

    def test_the_home_finds_the_vault_and_knows_its_own_name_there(self) -> None:
        self.register(self.vault)
        self.assertEqual(home_remote.default_share(self.environ, self.home), self.vault)
        self.assertIn("win-a", home_remote.this_host_names(self.environ, self.home))
        self.assertIsNone(home_remote.default_share({**self.environ, "VIBETRACKS_SHARE": "off"}, self.home))


if __name__ == "__main__":
    unittest.main()
