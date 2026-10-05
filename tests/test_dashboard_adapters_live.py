"""The five real adapters over the checked-in registry and this machine's loop files: what holds for every one.

    python3 -m pytest -q tests/test_dashboard_adapters_live.py      (from the repo root)

- **Declared reads only.** Each adapter runs under a Python audit hook that records every file it opens and every
  directory it lists. Each must sit inside a path the track's note declares in ``vibe-sources``, because the build
  caches an adapter's output on those paths' mtimes (build.py): an undeclared input changes without a rebuild.
- **``READS`` matches the note**, key for key, with a role from base.READ_ROLES (the build's default heartbeat).
- **Rung**, **local times with a zone**, **KPI labels that do not repeat their group header** and the **whole purpose**.

A loop whose files are not on this machine reads "not reporting" and opens nothing, so these tests stay meaningful
(and green) on any machine; the per-adapter fixture tests pin the numbers.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import site
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Iterator

from vibetracks.dashboard import registry
from vibetracks.dashboard.adapters import base
from vibetracks.notes import first_paragraph, parse_frontmatter
from vibetracks.sources import load_sources

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "workspace"

# What an adapter may touch without declaring it: the interpreter, its libraries (mimetypes reads /etc/mime.types)
# and this package's own modules (a lazy import reads a .py). Never a loop's file.
_IGNORED = tuple(os.path.realpath(p) + os.sep for p in {
    sys.prefix, sys.base_prefix, sys.exec_prefix, *site.getsitepackages(), site.getusersitepackages(),
    str(REPO / "vibetracks"), "/etc", "/usr", "/proc", "/dev", "/sys", "/lib", "/lib64",
} if p)

_recording: list[tuple[str, str]] | None = None


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if _recording is None or event not in ("open", "os.scandir", "os.listdir"):
        return
    target = args[0] if args else None
    if target is None:  # os.scandir() / os.listdir() of the working directory
        target = "."
    if isinstance(target, int):  # an already-open descriptor
        return
    try:
        path = os.path.realpath(os.fsdecode(os.fspath(target)))
    except TypeError:
        return
    if not (path + os.sep).startswith(_IGNORED):
        _recording.append((event, path))


sys.addaudithook(_audit)  # WHY a hook: it sees every open, through pathlib, io, json or a library, not only open()


@contextlib.contextmanager
def recording() -> Iterator[list[tuple[str, str]]]:
    global _recording
    _recording = []
    try:
        yield _recording
    finally:
        _recording = None


def _covered(path: str, declared: list[tuple[str, int]]) -> bool:
    """A declared file itself, a declared folder, or an entry at most ``depth`` levels inside it: exactly what
    build.source_stamp watches (a file deeper than that could change without a rebuild)."""

    for root, depth in declared:
        if path == root:
            return True
        prefix = root.rstrip(os.sep) + os.sep
        if path.startswith(prefix) and path[len(prefix):].count(os.sep) < depth:
            return True
    return False


def _strings(value: Any, skip: frozenset[str], key: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for name, item in value.items():
            if name not in skip:
                yield from _strings(item, skip, f"{key}/{name}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, skip, f"{key}/{index}")
    elif isinstance(value, str):
        yield key, value


class LiveAdaptersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tracks = [t for t in registry.load_registry(WORKSPACE) if not t.archived]
        cls.paths = load_sources()
        cls.outputs: dict[str, list[dict[str, Any]]] = {}
        cls.reads: dict[str, list[tuple[str, str]]] = {}
        for work_track in cls.tracks:
            module = importlib.import_module(f"vibetracks.dashboard.adapters.{work_track.adapter}")
            sources = {key: cls.paths[key] for key in work_track.sources if key in cls.paths}
            with recording() as opened:
                out = [module.build_track(work_track, dict(sources))]
                if work_track.children and callable(getattr(module, "build_children", None)):
                    out += module.build_children(work_track, dict(sources))
            cls.outputs[work_track.id] = out
            cls.reads[work_track.id] = list(opened)

    def test_the_registry_has_the_five_tracks(self) -> None:
        self.assertEqual([t.id for t in self.tracks], ["kinsim", "rig", "grasping", "detection", "pyblocks"])

    def test_every_adapter_exports_reads_matching_its_note(self) -> None:
        for work_track in self.tracks:
            module = importlib.import_module(f"vibetracks.dashboard.adapters.{work_track.adapter}")
            reads = getattr(module, "READS", None)
            self.assertIsInstance(reads, dict, f"adapters/{work_track.adapter}.py exports no READS")
            self.assertEqual(sorted(reads), sorted(work_track.sources),
                             f"{work_track.id}: READS and the note's vibe-sources must name the same keys")
            for key, role in reads.items():
                self.assertIn(role, base.READ_ROLES, f"{work_track.id}: {key}")
                self.assertIn(key, self.paths, f"{work_track.id}: {key} is not a sources.py key")

    def test_adapters_open_only_what_their_note_declares(self) -> None:
        for work_track in self.tracks:
            module = importlib.import_module(f"vibetracks.dashboard.adapters.{work_track.adapter}")
            depth = getattr(module, "DEPTH", None) or {}
            declared = [(os.path.realpath(self.paths[key]), int(depth.get(key, 1)))
                        for key in work_track.sources if key in self.paths]
            stray = sorted({f"{event} {path}" for event, path in self.reads[work_track.id] if not _covered(path, declared)})
            self.assertEqual(stray, [], f"{work_track.id} read outside its vibe-sources {work_track.sources}")

    def test_the_read_check_can_fail(self) -> None:
        # Mutation guard: the same hook flags a read outside the declared roots, so a green run above means something.
        with recording() as opened:
            Path(__file__).read_text(encoding="utf-8")
            os.listdir(Path(__file__).parent)
        self.assertTrue(opened)
        self.assertFalse(all(_covered(path, [(str(REPO / "workspace"), 1)]) for _, path in opened))
        # and depth is exact: a file two folders down is not covered by a one-level watch
        self.assertFalse(_covered("/a/b/c.json", [("/a", 1)]))
        self.assertTrue(_covered("/a/b/c.json", [("/a", 2)]))
        self.assertTrue(_covered("/a/b.json", [("/a", 1)]))

    def test_with_nothing_declared_an_adapter_opens_nothing(self) -> None:
        for work_track in self.tracks:
            module = importlib.import_module(f"vibetracks.dashboard.adapters.{work_track.adapter}")
            with recording() as opened:
                track = module.build_track(work_track, {})
            self.assertEqual(opened, [], work_track.id)
            self.assertEqual(track["state"]["word"], base.NOT_REPORTING, work_track.id)

    def test_every_track_is_sound_and_carries_a_rung_field(self) -> None:
        for track_id, out in self.outputs.items():
            top = out[0]
            self.assertEqual(base.problems(top), [], track_id)
            self.assertIn("rung", top, track_id)
            for child in out[1:]:
                self.assertEqual(base.problems(child), [], f"{track_id}/{child.get('id')}")

    def test_human_times_say_their_zone(self) -> None:
        # Every clock time a person reads carries a zone ("10-04 17:55 PDT"). Machine fields (ISO stamps, paths,
        # provenance) and evidence notes, which quote the loops' own words verbatim, are not checked.
        skip = frozenset({"when", "since", "date", "ts", "generated_at", "modified", "newest", "computed_at", "path",
                          "value", "provenance", "evidence", "source", "media", "links", "registry", "freshness"})
        bare = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])(?!\s?(?:[A-Z]{2,5}\b|UTC[+-]))")
        # and the zone is this machine's: "17:55 PDT" beside "00:55 UTC" is the mix this rule exists to end
        foreign = None if "UTC" in time.tzname else re.compile(r"\d{1,2}:\d{2}(?::\d{2})? UTC\b")
        for track_id, out in self.outputs.items():
            for track in out:
                for key, text in _strings(track, skip):
                    for match in bare.finditer(text):
                        self.fail(f"{track_id}{key}: a time with no zone, {text[max(0, match.start() - 40):match.end() + 10]!r}")
                    if foreign and foreign.search(text):
                        self.fail(f"{track_id}{key}: a UTC time on a {time.tzname[0]}/{time.tzname[1]} machine, {text[:120]!r}")

    def test_kpi_labels_do_not_repeat_a_group_header(self) -> None:
        headers = [name.lower() for name in base.SLOT_NAMES.values()] + ["delivery", "needs you", "cost ·"]
        for track_id, out in self.outputs.items():
            for track in out:
                for kpi in track["kpis"]:
                    label = kpi["label"].lower()
                    self.assertFalse(any(label.startswith(header) for header in headers),
                                     f"{track_id}: {kpi['label']!r} repeats a group header")

    def test_snapshot_kpi_labels_do_not_repeat_a_group_header_either(self) -> None:
        from vibetracks.dashboard import build as build_module
        from vibetracks.dashboard.adapters import bam_loops

        if not build_module.SNAPSHOT_ORIGIN.is_file():
            self.skipTest("the 2026-10-03 snapshot is not on this machine")
        projection = bam_loops.build_projection(bam_loops.load_json(build_module.SNAPSHOT_ORIGIN), None,
                                                snapshot_path=str(build_module.SNAPSHOT_ORIGIN), curriculum_path=None)
        headers = [name.lower() for name in base.SLOT_NAMES.values()]
        for track in projection["tracks"]:
            for kpi in track["kpis"]:
                self.assertFalse(any(kpi["label"].lower().startswith(h) for h in headers), f"{track['id']}: {kpi['label']!r}")

    def test_purpose_is_the_whole_first_paragraph(self) -> None:
        for work_track in self.tracks:
            body = parse_frontmatter(Path(work_track.note_path).read_text(encoding="utf-8"))[1]
            self.assertEqual(work_track.purpose, first_paragraph(body, limit=None), work_track.id)
            self.assertFalse(work_track.purpose.endswith("…"))
        self.assertTrue(any(len(t.purpose) > 280 for t in self.tracks), "no purpose is long enough to prove the uncut read")


if __name__ == "__main__":
    unittest.main()
