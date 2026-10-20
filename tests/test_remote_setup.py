"""Tests for scripts/setup-machine, hermetic: a temp HOME, a local bare share, ``--python sys.executable`` (no venv or
pip) and ``--no-autostart``, so nothing outside the temp folder is touched.

    python3 -m pytest -q tests/test_remote_setup.py      (from the repo root)
"""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibetracks.remote import sync

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "setup-machine"
EVENTS = ("UserPromptSubmit", "Stop", "SessionEnd")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def make_share(root: Path) -> Path:
    origin = root / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)
    seed = root / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "user.email", "seed@example.invalid")
    (seed / "README.md").write_text("share\n")
    git(seed, "add", "README.md")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", "origin", "HEAD:main")
    return origin


def origin_head(origin: Path) -> str:
    return git(origin, "rev-parse", "main").strip()


def load_script():
    loader = importlib.machinery.SourceFileLoader("setup_machine", str(SCRIPT))
    spec = importlib.util.spec_from_loader("setup_machine", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def step_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line[:2] in ("✓ ", "· ", "✗ ", "→ ", "! ")]


def tree(root: Path) -> dict[str, bytes | None]:
    return {path.relative_to(root).as_posix(): (path.read_bytes() if path.is_file() else None)
            for path in sorted(root.rglob("*"))}


class SetupMachine(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vt-setup-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.origin = make_share(self.tmp)

    def setup(self, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "PYTHONIOENCODING": "utf-8",
               "XDG_CONFIG_HOME": str(self.home / ".config")}
        return subprocess.run([sys.executable, str(SCRIPT), "--host", "win-a", "--share-url", str(self.origin),
                               "--python", sys.executable, "--no-autostart", *args],
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=self.tmp, timeout=180)

    def test_full_run_then_an_identical_rerun_changes_nothing(self) -> None:
        seed_head = origin_head(self.origin)
        first = self.setup()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        share = self.home / "vibetracks-share"
        self.assertTrue((share / ".git").is_dir(), first.stdout)
        config = json.loads((self.home / ".vibetracks" / "sync.json").read_text())
        self.assertEqual((config["host"], config["share"]), ("win-a", share.resolve().as_posix()))
        pushed = origin_head(self.origin)
        self.assertNotEqual(pushed, seed_head)
        self.assertEqual(git(self.origin, "log", "-1", "--format=%an", "main").strip(), "win-a")
        self.assertIn("hosts/win-a/host.json", git(self.origin, "ls-tree", "-r", "--name-only", "main"))
        remote = json.loads((self.home / ".vibetracks" / "remote.json").read_text())
        self.assertEqual((remote["host"], remote["share"]), ("win-a", share.resolve().as_posix()))
        launcher = self.home / ".vibetracks" / "hook"
        self.assertTrue(launcher.is_file() and os.access(launcher, os.X_OK))
        self.assertIn("✓ round: pushed", first.stdout)
        self.assertIn("NEEDS ZACH: add the hook line to the shared settings.json", first.stdout)
        self.assertIn("Summary for Zach", first.stdout)
        self.assertFalse((self.home / ".claude").exists())

        before = tree(self.home / ".vibetracks")
        second = self.setup()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        lines = step_lines(second.stdout)
        self.assertEqual([line[:2] for line in lines], ["· "] * len(lines), second.stdout)
        self.assertEqual({line[2:].split(":")[0] for line in lines},
                         {"venv", "install", "share", "config", "round", "autostart", "hook-config"})
        self.assertEqual(origin_head(self.origin), pushed)
        self.assertEqual(tree(self.home / ".vibetracks"), before)
        self.assertIn("NEEDS ZACH: add the hook line", second.stdout)

    def test_install_hook_edits_the_symlink_target_and_keeps_everything_else(self) -> None:
        vault = self.tmp / "vault" / "Settings" / "Claude"
        vault.mkdir(parents=True)
        target = vault / "settings.json"
        original = {
            "model": "opus",
            "remoteControlAtStartup": True,
            "permissions": {"allow": ["Bash(git status)"], "deny": []},
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo existing-stop"}]}],
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.py"}]}],
            },
        }
        target.write_text(json.dumps(original, indent=2) + "\n")
        original_text = target.read_text()
        (self.home / ".claude").mkdir()
        link = self.home / ".claude" / "settings.json"
        link.symlink_to(target)

        first = self.setup("--install-hook")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("✓ hook: added the hook line", first.stdout)
        self.assertNotIn("NEEDS ZACH", first.stdout)
        self.assertTrue(link.is_symlink())
        self.assertEqual(Path(os.readlink(link)), target)
        settings = json.loads(target.read_text())
        for event in EVENTS:
            commands = [hook["command"] for group in settings["hooks"][event] for hook in group["hooks"]]
            self.assertEqual(commands.count(sync.HOOK_LINE), 1, event)
        self.assertEqual(settings["hooks"]["Stop"][0], original["hooks"]["Stop"][0])
        self.assertEqual(settings["hooks"]["PreToolUse"], original["hooks"]["PreToolUse"])
        self.assertEqual({k: v for k, v in settings.items() if k != "hooks"},
                         {k: v for k, v in original.items() if k != "hooks"})
        self.assertEqual(list(settings), list(original))
        self.assertTrue(target.read_text().startswith('{\n  "model"'))  # the file's own 2-space indent
        backups = sorted((self.home / ".vibetracks").glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original_text)

        edited = target.read_bytes()
        second = self.setup("--install-hook")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("· hook: already in settings.json", second.stdout)
        self.assertEqual(target.read_bytes(), edited)
        self.assertTrue(link.is_symlink())
        self.assertEqual(len(list((self.home / ".vibetracks").glob("settings.json.bak-*"))), 1)

    def test_dry_run_changes_nothing_and_plans_schtasks_on_windows(self) -> None:
        module = load_script()
        head = origin_head(self.origin)
        for system, expected in (("windows", ["schtasks /Create /SC ONLOGON /TN", '"Vibe Tracks sync"', "/TR",
                                              "pythonw.exe -P -m vibetracks.remote.sync --config", "schtasks /Run"]),
                                 ("linux", ["systemctl --user enable --now vibetracks-sync.service"])):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}), \
                    mock.patch.object(module, "detect_platform", return_value=system), \
                    contextlib.redirect_stdout(out):
                code = module.main(["--host", "win-a", "--share-url", str(self.origin), "--dry-run"])
            text = out.getvalue()
            self.assertEqual(code, 0, text)
            for fragment in expected:
                self.assertIn(fragment, text)
            self.assertIn("would run: git clone", text)
            self.assertIn("-m vibetracks.remote.sync init", text)
            self.assertIn("-m vibetracks.remote.sync hook-config", text)
            self.assertIn("dry run: nothing was changed", text)
            self.assertEqual(list(self.home.iterdir()), [], text)
            self.assertEqual(origin_head(self.origin), head)

    def test_a_clone_of_another_share_is_refused(self) -> None:
        elsewhere = self.tmp / "elsewhere.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(elsewhere)], check=True)
        clone = self.home / "vibetracks-share"
        subprocess.run(["git", "clone", "-q", str(elsewhere), str(clone)], check=True, capture_output=True)
        result = self.setup()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("✗ share:", result.stdout)
        self.assertIn("is a clone of", result.stdout)
        self.assertFalse((self.home / ".vibetracks" / "sync.json").exists())
        self.assertIn("failed:", result.stdout)

    def test_the_hook_line_is_the_one_sync_prints(self) -> None:
        self.assertEqual(load_script().HOOK_LINE, sync.HOOK_LINE)

    def test_minus_p_is_what_stops_the_home_clone_shadowing_an_editable_install(self) -> None:
        # The win-a failure of 2026-10-16, reduced: the cwd holds the clone root (a `vibetracks/` folder, no
        # __init__.py), and the real package is reachable only through a finder appended to sys.meta_path, as
        # setuptools' editable install does. -E -S keep this interpreter's own install and PYTHONPATH out of it, and
        # the finder points at an empty stand-in so the package's own imports play no part.
        (self.home / "vibetracks").mkdir()
        package = self.tmp / "installed" / "vibetracks" / "__init__.py"
        package.parent.mkdir(parents=True)
        package.write_text("")
        probe = ("import importlib.util, sys\n"
                 "class Editable:\n"
                 "    @staticmethod\n"
                 "    def find_spec(name, path=None, target=None):\n"
                 f"        return importlib.util.spec_from_file_location(name, {str(package)!r}) "
                 "if name == 'vibetracks' else None\n"
                 "sys.meta_path.append(Editable)\n"
                 "import vibetracks\n"
                 "print(vibetracks.__file__)\n")

        def imported(*flags: str) -> str:
            return subprocess.run([sys.executable, "-E", "-S", *flags, "-c", probe], capture_output=True, text=True,
                                  cwd=self.home, timeout=60).stdout.strip()

        self.assertEqual(imported(), "None")
        self.assertEqual(Path(imported("-P")), package)

    def test_every_python_it_starts_keeps_the_home_folder_off_sys_path(self) -> None:
        module = load_script()
        commands: list[list[str]] = []
        units: list[str] = []

        def fake_run(setup, argv, step, **kwargs):
            commands.append([str(part) for part in argv])
            return subprocess.CompletedProcess(argv, 0, f"Editable project location: {module.ROOT}\n", "")

        with mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}), \
                mock.patch.object(module.Setup, "run", fake_run), \
                mock.patch.object(module.Setup, "write", lambda setup, path, text: units.append(text)), \
                mock.patch.object(module, "START_WAIT_S", 0), \
                contextlib.redirect_stdout(io.StringIO()):
            for system, autostart in (("windows", "autostart_windows"), ("linux", "autostart_linux")):
                setup = module.Setup(module.parse_args(["--host", "win-a"]), system)
                for step in (setup.step_venv, getattr(setup, autostart), setup.step_hook):
                    with contextlib.suppress(module.StepFailed):
                        step()
        pythons = [argv for argv in commands if Path(argv[0]).name.lower().startswith("python")]
        # venv, pip install, pip show, the import probe and hook-config, once per platform
        self.assertEqual(len(pythons), 10, commands)
        for argv in pythons:
            self.assertEqual(argv[1], "-P", argv)
        task = next(argv[argv.index("/TR") + 1] for argv in commands if argv[:2] == ["schtasks", "/Create"])
        self.assertIn("pythonw.exe -P -m vibetracks.remote.sync --config", task)
        self.assertEqual(len(units), 1, units)
        self.assertIn(" -P -m vibetracks.remote.sync --config ", units[0])

    def test_the_session_hook_starts_python_with_the_cwd_off_sys_path(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "vibetracks_session", REPO / "vibetracks" / "remote" / "hooks" / "vibetracks_session.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        (self.home / ".vibetracks").mkdir()
        (self.home / ".vibetracks" / "remote.json").write_text(
            json.dumps({"python": sys.executable, "share": str(self.home / "vibetracks-share"), "host": "win-a"}))
        with mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}), \
                mock.patch.object(hook.subprocess, "run") as run, \
                mock.patch.object(hook.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{}"))):
            self.assertEqual(hook.main(), 0)
        self.assertEqual(run.call_args.args[0][:4], [sys.executable, "-P", "-m", "vibetracks.remote.session_hook"])


if __name__ == "__main__":
    unittest.main()
