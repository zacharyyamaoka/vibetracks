"""Codex round-2 findings on the roadmap's live API (reports/media/audits/2026-10-04-vibetracks-roadmap-r2.md).

W01 a stored document stands in for a configured live projector only when it is that projector's loop at that checkout,
and is always marked stale; W02 a projection never blesses a dependency that changed while it ran; W04 a registry's
source map names only destinations its projector reads; W05 a request on an older configuration never evicts the current
one's last good document; W06 a cold-cache failure watches its stored fallback's links and is retried after a minute.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from unittest import mock

from test_roadmap_api_r1 import _NoRegistry, _WithRegistry
from test_roadmap_live import clear_caches, get, get_json, touch

from vibetracks.roadmap import api
from vibetracks.roadmap.projector import project_kinsim

SCHEMA = "bam-roadmap/1"
GREEN = [{"id": "G1", "status": "green", "title": "an old green rung"}]


def link(path: Path) -> dict:
    exists = path.exists()
    return {"kind": "file", "label": None, "path": str(path), "base": "abs", "abs": str(path) if exists else None,
            "line": None, "end_line": None, "exists": exists, "why_unresolved": None}


def age(root: Path, seconds: int = 30) -> None:
    """Every file under ``root`` written ``seconds`` ago: a loop at rest, so no linked file reads as written mid-projection."""

    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(directory, name)
            if not os.path.islink(path):
                stat = os.stat(path)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns - seconds * 1_000_000_000))


def fake_projector(**fields) -> api.LiveProjector:
    """A projector built from KINSIM's, keeping only the fields this ``LiveProjector`` has."""

    known = {field.name for field in dataclasses.fields(api.LiveProjector)}
    return dataclasses.replace(api.KINSIM, **{name: value for name, value in fields.items() if name in known})


def stale(document: dict) -> list[str]:
    return [warning for warning in document.get("warnings", []) if warning.startswith("stale: ")]


class W01StoredFallbackOwnershipTest(_WithRegistry):
    def setUp(self) -> None:
        super().setUp()
        age(self.tmp)
        self.detection = self.tmp / "no-detection"  # the fixture's detection_dir: made present here
        self.detection.mkdir()
        (self.detection / "ladder_data.py").write_text("LADDER = []\n", encoding="utf-8")

    def snapshot(self, loop: str, repo: Path | str, generated_at: str = "2026-09-01T00:00:00+00:00") -> dict:
        """``loop``'s snapshot at ``repo``, its other roots and declared source those of this fixture's sources (X01)."""

        consumed = {"grasping": self.tmp / "no-grasping", "detection": self.detection, "rig": self.tmp / "no-rig-loop",
                    "kinsim": self.loop.curriculum_dir}[loop]
        roots = {"repo": str(repo)}
        if loop in ("grasping", "kinsim"):
            roots["data_home"] = str(self.tmp / "no-grasping" / "out" if loop == "grasping" else self.loop.data_home)
        return {"schema": SCHEMA, "title": f"old {loop}", "generated_at": generated_at, "loop": loop, "roots": roots,
                "sources": [link(consumed / "input.json")], "rungs": GREEN, "warnings": ["its own"]}

    def test_codex_reproduction_another_loops_snapshot_never_answers_a_failed_projection(self) -> None:
        self.note("custom-track", "{projector: detection, sources: [detection_dir]}")
        self.store("custom-track", self.snapshot("grasping", self.tmp / "no-grasping"))
        with mock.patch("vibetracks.roadmap.api.project_detection", side_effect=RuntimeError("injected failure")):
            status, body = get_json("/doc", "track=custom-track")
        self.assertEqual(status, 503, body)
        self.assertIn("injected failure", body["error"])
        self.assertNotIn("green", json.dumps(body))

    def test_the_same_loop_at_another_checkout_never_answers_a_failed_projection(self) -> None:
        self.note("custom-track", "{projector: detection, sources: [detection_dir]}")
        self.store("custom-track", self.snapshot("detection", self.tmp / "elsewhere"))
        with mock.patch("vibetracks.roadmap.api.project_detection", side_effect=RuntimeError("injected failure")):
            self.assertEqual(get_json("/doc", "track=custom-track")[0], 503)

    def test_its_own_snapshot_answers_a_failed_projection_marked_stale(self) -> None:
        self.note("custom-track", "{projector: detection, sources: [detection_dir]}")
        stored = self.snapshot("detection", self.detection)
        self.store("custom-track", stored)
        with mock.patch("vibetracks.roadmap.api.project_detection", side_effect=RuntimeError("injected failure")):
            status, document = get_json("/doc", "track=custom-track")
        self.assertEqual((status, document["generated_at"], document["loop"]), (200, stored["generated_at"], "detection"))
        self.assertTrue(document["warnings"][0].startswith("stale: "), document["warnings"])
        self.assertIn("injected failure", document["warnings"][0])
        self.assertEqual(document["warnings"][1:], ["its own"])

    def test_codex_reproduction_an_absent_loops_snapshot_is_marked_stale(self) -> None:
        self.note("custom-track", "{projector: grasping, sources: [grasp_bench_dir]}")
        stored = self.snapshot("grasping", self.tmp / "no-grasping")
        self.store("custom-track", stored)
        status, document = get_json("/doc", "track=custom-track")
        self.assertEqual((status, document["generated_at"], document["rungs"]), (200, stored["generated_at"], GREEN))
        self.assertTrue(document["warnings"][0].startswith("stale: the grasping loop is not on this machine"),
                        document["warnings"])
        self.assertEqual(document["warnings"][1:], ["its own"])

    def test_an_absent_loop_never_serves_another_loops_or_checkouts_snapshot(self) -> None:
        self.note("custom-track", "{projector: grasping, sources: [grasp_bench_dir]}")
        for stored in (self.snapshot("detection", self.tmp / "no-grasping"), self.snapshot("grasping", self.tmp / "other"),
                       {"schema": SCHEMA, "title": "no loop", "generated_at": "t", "rungs": GREEN}):
            with self.subTest(loop=stored.get("loop"), roots=stored.get("roots")):
                self.store("custom-track", stored)
                self.assertEqual(get_json("/doc", "track=custom-track"), (404, {"error": "no roadmap reported yet"}))

    def test_an_absent_checkout_under_the_snapshots_repo_is_the_same_checkout(self) -> None:
        """Absent, the checkout is compared by path: the projector's directory inside the snapshot's ``roots.repo``."""

        self.note("custom-track", "{projector: grasping, sources: [grasp_bench_dir]}")
        self.store("custom-track", self.snapshot("grasping", self.tmp))
        self.assertEqual(get_json("/doc", "track=custom-track")[0], 200)
        self.store("custom-track", self.snapshot("grasping", str(self.tmp) + "-sibling"))
        self.assertEqual(get_json("/doc", "track=custom-track")[0], 404)

    def test_a_present_checkout_is_compared_by_git_toplevel(self) -> None:
        self.note("kinsim", "{projector: kinsim, sources: [kinsim_curriculum_dir, kinsim_home]}")
        self.counting(side_effect=RuntimeError("injected failure"), wraps=None)
        other = self.tmp / "other-repo"
        other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        self.store("kinsim", self.snapshot("kinsim", other))
        self.assertEqual(get_json("/doc", "track=kinsim")[0], 503)
        clear_caches()
        # the snapshot names the checkout through a path git resolves to the same toplevel
        self.store("kinsim", self.snapshot("kinsim", self.loop.repo / "src" / ".."))
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["loop"]), (200, "kinsim"))
        self.assertTrue(stale(document), document["warnings"])

    def test_without_a_registry_a_builtin_tracks_absent_loop_is_its_stale_snapshot(self) -> None:
        stored = self.snapshot("rig", self.tmp / "no-rig-loop")
        self.store("rig", stored)
        with mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.tmp / "nowhere")}):
            status, document = get_json("/doc", "track=rig")
            self.assertEqual((status, document["generated_at"]), (200, stored["generated_at"]))
            self.assertTrue(document["warnings"][0].startswith("stale: the rig loop is not on this machine"))
            self.store("rig", self.snapshot("kinsim", self.tmp / "no-rig-loop"))
            self.assertEqual(get_json("/doc", "track=rig")[0], 404)

    def test_without_a_registry_a_track_no_projector_covers_is_its_stored_file_unchanged(self) -> None:
        stored = {"schema": SCHEMA, "title": "Other", "generated_at": "t", "warnings": []}
        self.store("other", stored)
        with mock.patch.dict(os.environ, {"VIBETRACKS_WORKSPACE": str(self.tmp / "nowhere")}):
            self.assertEqual(get_json("/doc", "track=other"), (200, stored))

    def test_the_live_document_carries_no_stale_warning(self) -> None:
        self.note("kinsim", "{projector: kinsim, sources: [kinsim_curriculum_dir, kinsim_home]}")
        self.store("kinsim", self.snapshot("kinsim", self.loop.repo))
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["title"], stale(document)), (200, "Kinsim curriculum", []))


class W02NoBlessingTest(_NoRegistry):
    def setUp(self) -> None:
        super().setUp()
        age(self.tmp)

    def test_codex_reproduction_a_linked_file_rewritten_during_projection_projects_again(self) -> None:
        acceptance = self.acceptance()
        self.assertEqual(get("/doc", "track=kinsim")[0], 200)
        version_2 = acceptance.stat().st_mtime_ns + 5_000_000_000

        def rewritten_mid_projection(*args, **kwargs):
            document = project_kinsim(*args, **kwargs)  # read version 1
            os.utime(acceptance, ns=(version_2, version_2))  # then version 2 lands
            return document

        counted = self.counting(side_effect=rewritten_mid_projection, wraps=None)
        self.assertEqual(get("/doc", "track=kinsim&refresh=1")[0], 200)
        self.assertEqual(counted.call_count, 1)
        counted.side_effect = project_kinsim
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count), (200, 2))  # the version-1 verdict was not blessed
        self.assertEqual(stale(document), [])
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)  # read at version 2 both before and after: settled

    def test_a_declared_input_appended_during_projection_projects_again(self) -> None:
        self.assertEqual(get("/doc", "track=kinsim")[0], 200)
        events = self.loop.data_home / "loop_events.jsonl"

        def appended_mid_projection(*args, **kwargs):
            document = project_kinsim(*args, **kwargs)
            touch(events)
            return document

        counted = self.counting(side_effect=appended_mid_projection, wraps=None)
        get("/doc", "track=kinsim&refresh=1")
        counted.side_effect = project_kinsim
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)


class W02NewlyLinkedFileTest(_NoRegistry):
    """A fake loop whose second projection links a file its first did not: there is no earlier reading of it."""

    def setUp(self) -> None:
        super().setUp()
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        self.old_file = self.fake / "old.txt"
        self.old_file.write_text("old\n", encoding="utf-8")
        self.new_file = self.fake / "new.txt"
        self.new_file.write_text("new\n", encoding="utf-8")
        age(self.tmp)
        self.links = [self.old_file]
        self.calls = 0

        def project(sources, now):
            self.calls += 1
            return {"schema": SCHEMA, "loop": "fake", "title": "Fake", "generated_at": now,
                    "roots": {"repo": str(self.fake)}, "sources": [link(path) for path in self.links], "warnings": []}

        projector = fake_projector(name="fake", loop="fake", title="Fake", present=lambda sources: True,
                                   keys=frozenset({"kinsim_home"}), inputs=lambda sources: [],
                                   checkout=lambda sources: self.fake, project=project)
        for patcher in (mock.patch.dict(api.PROJECTORS, {"fake": projector}),
                        mock.patch("vibetracks.roadmap.api.validate_document", return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_newly_linked_file_written_during_projection_projects_again(self) -> None:
        self.assertEqual(get("/doc", "track=fake")[0], 200)
        self.links = [self.old_file, self.new_file]
        now = time.time_ns()
        os.utime(self.new_file, ns=(now, now))
        self.assertEqual(get("/doc", "track=fake&refresh=1")[0], 200)
        self.assertEqual(self.calls, 2)
        self.assertEqual(get("/doc", "track=fake")[0], 200)
        self.assertEqual(self.calls, 3)  # new.txt had no reading before: its fresh mtime may be mid-projection
        get("/doc", "track=fake")
        self.assertEqual(self.calls, 3)  # now an earlier document's link, read before and after: settled

    def test_a_newly_linked_file_at_rest_is_stamped(self) -> None:
        self.assertEqual(get("/doc", "track=fake")[0], 200)
        self.links = [self.old_file, self.new_file]
        get("/doc", "track=fake&refresh=1")
        get("/doc", "track=fake")
        self.assertEqual(self.calls, 2)
        touch(self.new_file)
        get("/doc", "track=fake")
        self.assertEqual(self.calls, 3)  # and the stamp it joined watches it


class W04DestinationKeyTest(_WithRegistry):
    def test_codex_reproduction_a_misspelt_destination_is_refused(self) -> None:
        self.note("custom-track", "{projector: grasping, sources: {grasp_bench_dri: detection_dir}}")
        with self.assertRaises(api.UnknownSourceKey) as raised:
            api.projector_for("custom-track")
        self.assertIn("unknown destination key grasp_bench_dri", str(raised.exception))
        status, body = get_json("/doc", "track=custom-track")
        self.assertEqual(status, 500)
        self.assertIn("destination key grasp_bench_dri", body["error"])
        self.assertIn("grasp_bench_dir", body["error"])  # what the grasping projector does read

    def test_another_projectors_input_is_not_a_destination(self) -> None:
        self.note("custom-track", "{projector: rig, sources: {kinsim_home: rig_loop_dir}}")
        self.assertEqual(get_json("/doc", "track=custom-track")[0], 500)

    def test_an_unknown_source_is_still_named_as_the_source(self) -> None:
        self.note("custom-track", "{projector: rig, sources: {rig_loop_dir: no_such_key}}")
        self.assertEqual(get_json("/doc", "track=custom-track"),
                         (500, {"error": "registry for custom-track names unknown source key no_such_key"}))

    def test_a_valid_mapping_reads_its_input_from_the_named_key(self) -> None:
        self.note("custom-track", "{projector: rig, sources: {rig_loop_dir: kinsim_home}}")
        projector, sources = api.projector_for("custom-track")
        self.assertEqual((projector.name, sources["rig_loop_dir"]), ("rig", str(self.loop.data_home)))

    def test_each_projector_declares_the_keys_it_reads(self) -> None:
        self.assertEqual({name: projector.keys for name, projector in api.PROJECTORS.items()},
                         {"kinsim": {"kinsim_curriculum_dir", "kinsim_home"}, "rig": {"rig_loop_dir"},
                          "grasping": {"grasp_bench_dir"}, "detection": {"detection_dir"}})
        self.assertEqual({name: projector.loop for name, projector in api.PROJECTORS.items()},
                         {"kinsim": "kinsim", "rig": "rig", "grasping": "grasping", "detection": "detection"})


class W05EvictionTest(_NoRegistry):
    def setUp(self) -> None:
        super().setUp()
        age(self.tmp)

    def write_sources(self, **changes: str) -> None:
        sources_file = Path(os.environ["VIBETRACKS_SOURCES"])
        sources = json.loads(sources_file.read_text(encoding="utf-8"))
        sources_file.write_text(json.dumps({**sources, **changes}), encoding="utf-8")

    def test_codex_reproduction_an_older_request_does_not_evict_the_current_configuration(self) -> None:
        current_home = str(self.loop.data_home)
        old_home = self.tmp / "old-home"
        shutil.copytree(self.loop.data_home, old_home)
        age(old_home)
        paused, release = threading.Event(), threading.Event()

        def present(sources) -> bool:
            if sources["kinsim_home"] == str(old_home) and not release.is_set():
                paused.set()  # request A resolved the old sources and stops here, before it reaches the cache
                release.wait(timeout=30)
            return api.KINSIM.present(sources)

        patcher = mock.patch.dict(api.PROJECTORS, {"kinsim": dataclasses.replace(api.KINSIM, present=present)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_sources(kinsim_home=str(old_home))
        results: list[int] = []
        request_a = threading.Thread(target=lambda: results.append(get("/doc", "track=kinsim")[0]))
        request_a.start()
        self.assertTrue(paused.wait(timeout=30))
        self.write_sources(kinsim_home=current_home)
        status, good = get_json("/doc", "track=kinsim")  # request B caches the current configuration
        self.assertEqual(status, 200)
        release.set()
        request_a.join(timeout=60)
        self.assertEqual(results, [200])
        self.counting(side_effect=RuntimeError("current configuration failed"), wraps=None)
        touch(self.loop.data_home / "loop_events.jsonl")
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200, document)
        self.assertEqual(document["generated_at"], good["generated_at"])
        self.assertTrue(document["warnings"][0].startswith("stale: "), document["warnings"])
        self.assertIn("current configuration failed", document["warnings"][0])


class W06ColdCacheRetryTest(_NoRegistry):
    def setUp(self) -> None:
        super().setUp()
        age(self.tmp)

    def test_codex_reproduction_restoring_the_fallbacks_linked_file_projects_again(self) -> None:
        acceptance = self.acceptance()
        self.store("kinsim", {"schema": SCHEMA, "title": "Stored", "generated_at": "2026-09-01T00:00:00+00:00",
                              "loop": "kinsim", "roots": {"repo": str(self.loop.repo), "data_home": str(self.loop.data_home)},
                              "sources": [link(self.loop.curriculum_dir / "curriculum.json")],
                              "rungs": [{"evidence": [link(acceptance)]}]})
        hidden = self.tmp / "hidden.py"
        acceptance.rename(hidden)

        def needs_the_test(*args, **kwargs):
            if not acceptance.exists():
                raise RuntimeError("the supporting test is unavailable")
            return project_kinsim(*args, **kwargs)

        counted = self.counting(side_effect=needs_the_test, wraps=None)
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["title"], counted.call_count), (200, "Stored", 1))
        self.assertTrue(document["warnings"][0].startswith("stale: "), document["warnings"])
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 1)  # nothing moved: not retried
        hidden.rename(acceptance)
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count, document["title"]), (200, 2, "Kinsim curriculum"))
        self.assertEqual(stale(document), [])

    def test_a_failure_is_retried_a_minute_later_even_on_an_unmoved_stamp(self) -> None:
        clock = [1000.0]
        patcher = mock.patch("vibetracks.roadmap.api._clock", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        counted = self.counting(side_effect=RuntimeError("transient"), wraps=None)
        self.assertEqual(get("/doc", "track=kinsim")[0], 503)
        clock[0] += api._RETRY_FAILED_S - 1
        self.assertEqual(get("/doc", "track=kinsim")[0], 503)
        self.assertEqual(counted.call_count, 1)
        clock[0] += 1
        counted.side_effect = project_kinsim
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, counted.call_count, stale(document)), (200, 2, []))
        clock[0] += 10 * api._RETRY_FAILED_S
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)  # a good document is not re-projected on time alone

    def test_the_retry_interval_is_a_minute(self) -> None:
        self.assertEqual(api._RETRY_FAILED_S, 60)
