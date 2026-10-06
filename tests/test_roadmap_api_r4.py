"""Codex round-4 finding Y01 on the roadmap's live API (reports/media/audits/2026-10-04-vibetracks-roadmap-r4.md).

A stored snapshot is a configuration's own only when its declared sources include the projector's entry file at exactly
the configured directory: pointing ``kinsim_curriculum_dir`` or ``rig_loop_dir`` at the parent of the snapshot's
directory no longer serves that child's snapshot as the absent loop's.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_roadmap_api_r2 import link
from test_roadmap_api_r3 import _Fixture
from test_roadmap_live import clear_caches, get_json

from vibetracks.roadmap import api

SCHEMA = "bam-roadmap/1"


class Y01ParentDirectoryFixtureTest(_Fixture):
    def test_codex_reproduction_kinsim_curriculum_dir_at_its_parent(self) -> None:
        self.store("kinsim", self.kinsim_snapshot())
        parent = self.loop.curriculum_dir.parent
        self.assertFalse((parent / "curriculum.json").exists())
        self.write_sources(kinsim_curriculum_dir=str(parent))
        self.assertEqual(get_json("/doc", "track=kinsim"), (404, {"error": "no roadmap reported yet"}))
        self.write_sources(kinsim_curriculum_dir=str(self.loop.curriculum_dir))  # its own directory: it answers, stale
        self.counting(side_effect=RuntimeError("injected failure"), wraps=None)
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["title"]), (200, "Stored"))
        self.assertTrue(document["warnings"][0].startswith("stale: "), document["warnings"])

    def test_codex_reproduction_rig_loop_dir_at_its_parent(self) -> None:
        rig = self.tmp / "no-rig-loop"  # the fixture's rig_loop_dir, absent
        self.store("rig", {"schema": SCHEMA, "title": "Stored rig", "generated_at": "t", "loop": "rig",
                           "roots": {"repo": str(self.tmp)}, "sources": [link(rig / "ladder.json")], "warnings": []})
        self.write_sources(rig_loop_dir=str(self.tmp))
        self.assertEqual(get_json("/doc", "track=rig"), (404, {"error": "no roadmap reported yet"}))
        self.write_sources(rig_loop_dir=str(rig))
        status, document = get_json("/doc", "track=rig")
        self.assertEqual((status, document["title"]), (200, "Stored rig"))
        self.assertTrue(document["warnings"][0].startswith("stale: the rig loop is not on this machine"))

    def test_codex_z02_an_absent_loop_configured_through_a_symlink_alias_keeps_its_snapshot(self) -> None:
        rig = self.tmp / "no-rig-loop"  # absent; the snapshot was taken through its canonical path
        # The alias lives OUTSIDE the snapshot's repo, so only a real-path comparison can see it is the same place.
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        alias = Path(elsewhere.name) / "alias"
        alias.symlink_to(self.tmp, target_is_directory=True)
        self.store("rig", {"schema": SCHEMA, "title": "Stored rig", "generated_at": "t", "loop": "rig",
                           "roots": {"repo": str(self.tmp)}, "sources": [link(rig / "ladder.json")], "warnings": []})
        self.write_sources(rig_loop_dir=str(alias / "no-rig-loop"))
        status, document = get_json("/doc", "track=rig")
        self.assertEqual((status, document.get("title")), (200, "Stored rig"), document)
        self.assertTrue(document["warnings"][0].startswith("stale: the rig loop is not on this machine"))

    def test_a_declared_file_under_the_directory_other_than_the_entry_file_is_not_ownership(self) -> None:
        snapshot = self.kinsim_snapshot()
        snapshot["sources"] = [link(self.loop.curriculum_dir / "triage.json"), link(self.loop.data_home / "status.json")]
        self.store("kinsim", snapshot)
        self.counting(side_effect=RuntimeError("injected failure"), wraps=None)
        self.assertEqual(get_json("/doc", "track=kinsim")[0], 503)


class _RealSources(unittest.TestCase):
    """This machine's default sources and stored snapshots, no registry; skipped where a snapshot or loop is absent."""

    def setUp(self) -> None:
        clear_caches()
        self.addCleanup(clear_caches)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.sources_file = Path(temporary.name) / "sources.json"  # absent: the defaults
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": "/nonexistent-vibetracks-workspace",
                                               "VIBETRACKS_SOURCES": str(self.sources_file)})
        patcher.start()
        self.addCleanup(patcher.stop)


class Y01RealSnapshotsTest(_RealSources):
    def check_parent(self, track: str, key: str) -> None:
        stored = Path(api.load_sources()["roadmap_docs_dir"]) / f"{track}.json"
        if not stored.is_file():
            self.skipTest(f"no stored {track} snapshot here ({stored}); the fixture case covers it")
        projector, sources = api.projector_for(track)
        self.assertTrue(api._owned(json.loads(stored.read_text(encoding="utf-8")), projector, sources),
                        f"the real {track} snapshot must stay eligible under the default sources")
        self.sources_file.write_text(json.dumps({key: str(Path(sources[key]).parent)}), encoding="utf-8")
        projector, parent_sources = api.projector_for(track)
        self.assertFalse(projector.present(parent_sources))
        self.assertEqual(get_json("/doc", f"track={track}"), (404, {"error": "no roadmap reported yet"}))

    def test_codex_reproduction_kinsim(self) -> None:
        self.check_parent("kinsim", "kinsim_curriculum_dir")

    def test_codex_reproduction_rig(self) -> None:
        self.check_parent("rig", "rig_loop_dir")


class Y01EntryFilesTest(_RealSources):
    def test_each_entry_file_is_one_its_real_projection_declares(self) -> None:
        for track, projector in api.PROJECTORS.items():
            with self.subTest(track=track):
                sources = api.load_sources()
                if not projector.present(sources):
                    continue
                document = api._project(projector, sources)
                declared = {os.path.realpath(path) for path in api._declared_sources(document)}
                for claim in projector.claims(sources):
                    if not claim.exact:
                        self.assertIn(os.path.realpath(claim.location / claim.entry), declared)
                self.assertTrue(api._owned(document, projector, sources))


if __name__ == "__main__":
    unittest.main()
