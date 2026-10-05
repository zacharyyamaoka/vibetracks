"""Codex round-1 findings on the roadmap's live API (reports/media/audits/2026-10-04-vibetracks-roadmap-r1.md).

V06 the stamp covers every file the last good document links to; V07 the evidence allowlist comes only from the
schema's declared Link locations; V08 the cache is keyed by (track, projector, sources); V09 an unknown source key in the
registry is a 500, never a silent default; V10 a registry that says "no roadmap" is never answered from a stored file;
V03 grasping and detection project live through the real workspace's registry.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from test_roadmap_live import LiveDocTestCase, clear_caches, fixtures, get, get_json, touch

from vibetracks.roadmap import api
from vibetracks.roadmap.projector import ProjectionError
from vibetracks.roadmap.projector import grasping as grasping_projector

SCHEMA = "bam-roadmap/1"
WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"

NOTE = """---
vibe-track: worktrack
vibe-id: {id}
vibe-title: {id}
vibe-status: running
vibe-priority: 1
vibe-owner: test
vibe-adapter: none
vibe-sources: []
vibe-roadmap: {roadmap}
vibe-children: []
---

# {id}
"""


class _NoRegistry(LiveDocTestCase):
    """The kinsim fixture loop with no reachable registry: the built-in table answers."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.tmp / "no-workspace")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def acceptance(self) -> Path:
        return self.loop.repo / fixtures.ACCEPTANCE

    def link_to(self, document: dict, path: Path) -> list[dict]:
        return [link for link in api._links(document) if link.get("path") == fixtures.ACCEPTANCE or link.get("abs") == str(path)]


class _WithRegistry(_NoRegistry):
    """The kinsim fixture loop behind a temporary work-track registry whose notes each test writes."""

    def setUp(self) -> None:
        super().setUp()
        self.workspace = self.tmp / "workspace"
        (self.workspace / "tracks").mkdir(parents=True)
        for name in ("Agent work.vtdash", "Work tracks.vibetrack"):
            shutil.copy(WORKSPACE / name, self.workspace / name)
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.workspace)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def note(self, track: str, roadmap: str) -> None:
        (self.workspace / "tracks" / f"{track}.md").write_text(NOTE.format(id=track, roadmap=roadmap), encoding="utf-8")


class V06LinkedFilesStampTest(_NoRegistry):
    def test_a_linked_file_that_vanishes_and_comes_back_projects_again(self) -> None:
        counted = self.counting()
        status, first = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.assertTrue(any(link["exists"] for link in self.link_to(first, self.acceptance())), "the fixture links its test")
        hidden = self.tmp / "hidden.py"
        self.acceptance().rename(hidden)  # no event, no ledger row, no commit: only the linked file moved
        status, second = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count), (200, 2))
        self.assertFalse(any(link["exists"] for link in self.link_to(second, self.acceptance())), second["warnings"])
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)  # still gone: same stamp
        hidden.rename(self.acceptance())
        status, third = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count), (200, 3))
        self.assertTrue(any(link["exists"] for link in self.link_to(third, self.acceptance())))

    def test_a_linked_file_rewritten_in_place_projects_again(self) -> None:
        counted = self.counting()
        get("/doc", "track=kinsim")
        touch(self.acceptance())
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)

    def test_a_failed_projection_is_retried_when_a_linked_file_changes(self) -> None:
        status, good = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        counted = self.counting(side_effect=ProjectionError("cannot read the test: boom"), wraps=None)
        touch(self.acceptance())
        status, stale = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count), (200, 1))
        self.assertTrue(stale["warnings"][0].startswith("stale: "), stale["warnings"])
        self.assertIn("boom", stale["warnings"][0])
        self.assertIn(good["generated_at"], stale["warnings"][0])
        self.assertEqual(stale["generated_at"], good["generated_at"])
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 1)  # nothing it depends on moved: not retried
        touch(self.acceptance())
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)  # a dependency moved: retried

    def test_a_failure_recovers_when_its_dependency_does(self) -> None:
        self.assertEqual(get("/doc", "track=kinsim")[0], 200)
        hidden = self.tmp / "hidden.py"
        self.acceptance().rename(hidden)
        with mock.patch("vibetracks.roadmap.api.project_kinsim", side_effect=ProjectionError("the test is gone")):
            status, stale = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.assertTrue(stale["warnings"][0].startswith("stale: "))
        counted = self.counting()
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 0)  # the failed stamp holds while nothing moves
        hidden.rename(self.acceptance())
        status, fresh = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count), (200, 1))
        self.assertFalse([warning for warning in fresh["warnings"] if warning.startswith("stale")])


class V07AllowlistTest(_NoRegistry):
    def test_link_shaped_metadata_does_not_widen_the_allowlist(self) -> None:
        secret = self.tmp / "secret.txt"
        secret.write_text("secret\n", encoding="utf-8")
        declared = self.tmp / "declared.txt"
        declared.write_text("declared\n", encoding="utf-8")
        smuggled = {"path": str(secret), "abs": str(secret), "base": "abs"}

        def link(path: Path) -> dict:
            return {"kind": "file", "label": None, "path": str(path), "base": "abs", "abs": str(path), "line": None,
                    "end_line": None, "exists": True, "why_unresolved": None}

        evidence = {**link(declared), "id": "e1", "facts": {"protocol": {"extra_metadata": smuggled}, "deep": [smuggled]}}
        # the rig loop is absent here, so its stored snapshot answers (W01: it must be that loop's, at that checkout)
        self.store("rig", {"schema": SCHEMA, "title": "Rig", "generated_at": "t", "loop": "rig",
                           "sources": [link(self.tmp / "no-rig-loop" / "ladder.json")],
                           "roots": {"repo": str(self.tmp / "no-rig-loop")},
                           "rungs": [{"evidence": [evidence], "x": smuggled}], "work": [{"x": {"nested": smuggled}}],
                           "facts": smuggled, "anything": [smuggled]})
        self.assertEqual(get_json("/evidence", f"track=rig&path={quote(str(declared), safe='')}")[0], 200)
        status, body = get_json("/evidence", f"track=rig&path={quote(str(secret), safe='')}")
        self.assertEqual(status, 403)
        self.assertNotIn("secret\n", json.dumps(body))


class V07CodexReproductionTest(unittest.TestCase):
    """The real grasp bench through this machine's default sources, with no registry; skipped where it is absent."""

    def setUp(self) -> None:
        clear_caches()
        self.addCleanup(clear_caches)
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": "/nonexistent-vibetracks-workspace"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_codex_reproduction_ledger_protocol_metadata_is_403(self) -> None:
        """Codex V07: a ledger row's ``protocol.extra_metadata`` naming /etc/hostname, through the real grasping projector."""

        sources = api.load_sources()
        live = api.projector_for("grasping")
        if live is None or not live[0].present(live[1]):
            self.skipTest(f"the grasping loop is not on this machine ({sources.get('grasp_bench_dir')})")
        if not os.path.isfile("/etc/hostname"):
            self.skipTest("/etc/hostname does not exist here")
        injected = {"path": "/etc/hostname", "abs": "/etc/hostname"}
        real_read = grasping_projector.read_jsonl

        def read_jsonl(*args, **kwargs):
            rows = real_read(*args, **kwargs)
            for row in rows:
                protocol = row.get("protocol") if isinstance(row.get("protocol"), dict) else {}
                row["protocol"] = {**protocol, "extra_metadata": dict(injected)}
            return rows

        with mock.patch.object(grasping_projector, "read_jsonl", read_jsonl):
            status, body = get("/doc", "track=grasping")
            self.assertEqual(status, 200, body[:500])
            self.assertIn('"extra_metadata": {\n', body.decode("utf-8"), "the injected row reached the document")
            status, evidence = get_json("/evidence", f"track=grasping&path={quote('/etc/hostname', safe='')}")
        self.assertEqual(status, 403, evidence)


class V08ConfigurationKeyedCacheTest(_WithRegistry):
    def test_codex_reproduction_a_track_switched_to_another_projector_never_serves_the_old_loop(self) -> None:
        self.note("custom-track", "{projector: kinsim, sources: [kinsim_curriculum_dir, kinsim_home]}")
        status, document = get_json("/doc", "track=custom-track")
        self.assertEqual((status, document["loop"]), (200, "kinsim"))
        fake_rig = self.tmp / "fake-rig"
        fake_rig.mkdir()
        (fake_rig / "ladder.json").write_text("{}", encoding="utf-8")
        sources_file = Path(os.environ["VIBETRACKS_SOURCES"])
        sources = json.loads(sources_file.read_text(encoding="utf-8"))
        sources_file.write_text(json.dumps({**sources, "fake_rig_dir": str(fake_rig)}), encoding="utf-8")
        self.note("custom-track", "{projector: rig, sources: {rig_loop_dir: fake_rig_dir}}")
        with mock.patch("vibetracks.roadmap.api.project_rig", side_effect=RuntimeError("injected rig failure")):
            status, body = get_json("/doc", "track=custom-track")
        self.assertEqual(status, 503, body)
        self.assertIn("injected rig failure", body["error"])
        self.assertNotIn("kinsim", json.dumps(body))

    def test_the_same_projector_on_other_sources_never_serves_the_old_document(self) -> None:
        self.note("kinsim", "{projector: kinsim, sources: [kinsim_curriculum_dir, kinsim_home]}")
        self.assertEqual(get("/doc", "track=kinsim")[0], 200)
        other_home = self.tmp / "other-home"
        shutil.copytree(self.loop.data_home, other_home)
        sources_file = Path(os.environ["VIBETRACKS_SOURCES"])
        sources = json.loads(sources_file.read_text(encoding="utf-8"))
        sources_file.write_text(json.dumps({**sources, "kinsim_home": str(other_home)}), encoding="utf-8")
        self.counting(side_effect=RuntimeError("other home failed"), wraps=None)
        status, body = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 503, body)
        self.assertIn("other home failed", body["error"])

    def test_the_same_configuration_still_falls_back_to_its_own_last_good_document(self) -> None:
        self.note("kinsim", "{projector: kinsim, sources: [kinsim_curriculum_dir, kinsim_home]}")
        status, good = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        self.counting(side_effect=RuntimeError("boom"), wraps=None)
        touch(self.loop.data_home / "loop_events.jsonl")
        status, stale = get_json("/doc", "track=kinsim")
        self.assertEqual((status, stale["generated_at"], stale["loop"]), (200, good["generated_at"], "kinsim"))
        self.assertTrue(stale["warnings"][0].startswith("stale: "), stale["warnings"])


class V09UnknownSourceKeyTest(_WithRegistry):
    def test_codex_reproduction_a_misspelt_mapping_is_refused(self) -> None:
        self.note("custom-track", "{projector: grasping, sources: {grasp_bench_dir: misspelled_source_key}}")
        with self.assertRaises(api.UnknownSourceKey) as raised:
            api.projector_for("custom-track")
        self.assertEqual(str(raised.exception), "registry for custom-track names unknown source key misspelled_source_key")
        self.assertEqual(get_json("/doc", "track=custom-track"),
                         (500, {"error": "registry for custom-track names unknown source key misspelled_source_key"}))

    def test_an_unknown_key_in_a_sources_list_is_refused(self) -> None:
        self.note("kinsim", "{projector: kinsim, sources: [kinsim_curriculum_dir, no_such_key]}")
        self.store("kinsim", {"schema": SCHEMA, "title": "Stored", "generated_at": "t"})
        self.assertEqual(get_json("/doc", "track=kinsim"),
                         (500, {"error": "registry for kinsim names unknown source key no_such_key"}))

    def test_tracks_still_lists_when_one_note_is_misconfigured(self) -> None:
        self.note("kinsim", "{projector: kinsim, sources: [no_such_key]}")
        self.assertEqual(get_json("/tracks")[0], 200)


class V10AuthoritativeRegistryTest(_WithRegistry):
    def setUp(self) -> None:
        super().setUp()
        self.store("kinsim", {"schema": SCHEMA, "title": "Stored", "generated_at": "2026-01-01T00:00:00+00:00",
                              "loop": "kinsim", "roots": {"repo": str(self.loop.repo), "data_home": str(self.loop.data_home)},
                              "sources": [{"kind": "file", "path": str(self.loop.curriculum_dir / "curriculum.json"),
                                           "base": "abs", "abs": None}]})

    def test_codex_reproduction_a_null_roadmap_never_serves_the_stored_file(self) -> None:
        self.note("kinsim", "null")
        self.assertEqual(get_json("/doc", "track=kinsim"), (404, {"error": "no roadmap reported yet"}))
        self.assertEqual(get_json("/evidence", f"track=kinsim&path={quote('/etc/hostname', safe='')}")[0], 404)

    def test_an_unknown_projector_or_an_unregistered_track_never_serves_the_stored_file(self) -> None:
        self.note("kinsim", "{projector: nothing-like-this, sources: []}")
        self.assertEqual(get_json("/doc", "track=kinsim"), (404, {"error": "no roadmap reported yet"}))
        (self.workspace / "tracks" / "kinsim.md").unlink()
        self.note("other", "null")
        self.assertEqual(get_json("/doc", "track=kinsim"), (404, {"error": "no roadmap reported yet"}))

    def test_without_a_reachable_registry_the_stored_file_still_answers(self) -> None:
        absent = dataclasses.replace(api.KINSIM, present=lambda sources: False)
        with mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.tmp / "nowhere")}), \
                mock.patch.dict(api.PROJECTORS, {"kinsim": absent}):
            status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["title"]), (200, "Stored"))


class V03RealWorkspaceTest(unittest.TestCase):
    """The dashboard's own workspace registry, with this machine's default sources (Codex V03)."""

    def setUp(self) -> None:
        clear_caches()
        self.addCleanup(clear_caches)
        patcher = mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(WORKSPACE)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, track: str) -> None:
        live = api.projector_for(track)
        self.assertIsNotNone(live, f"workspace/tracks/{track}.md registers no projector")
        if not live[0].present(live[1]):
            self.skipTest(f"the {track} loop's sources are not on this machine")
        status, body = get("/doc", f"track={track}")
        self.assertEqual(status, 200, body[:500])
        document = json.loads(body)
        self.assertEqual((document["schema"], document["loop"]), (SCHEMA, track))
        self.assertFalse([warning for warning in document["warnings"] if warning.startswith("stale")], document["warnings"])

    def test_grasping(self) -> None:
        self.check("grasping")

    def test_detection(self) -> None:
        self.check("detection")


if __name__ == "__main__":
    unittest.main()
