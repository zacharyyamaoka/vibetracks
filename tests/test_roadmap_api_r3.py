"""Codex round-3 findings on the roadmap's live API (reports/media/audits/2026-10-04-vibetracks-roadmap-r3.md).

X01 a stored document stands in only for the configuration whose every consumed source location produced its roots;
X02 the stamp kept after a projection is exactly the reading that was compared; X03 a cache entry is evicted only when no
request holds it and it has sat idle for ten minutes, so the current configuration and every held lock survive.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_roadmap_api_r1 import _NoRegistry
from test_roadmap_api_r2 import age, link
from test_roadmap_live import clear_caches, get, get_json, touch

from vibetracks.roadmap import api
from vibetracks.roadmap.projector import project_kinsim

SCHEMA = "bam-roadmap/1"
UNRELATED_HOME = "/audit-unrelated-kinsim-data-home"


class _Fixture(_NoRegistry):
    def setUp(self) -> None:
        super().setUp()
        age(self.tmp)

    def write_sources(self, **changes: str) -> None:
        sources_file = Path(os.environ["VIBETRACKS_SOURCES"])
        sources = json.loads(sources_file.read_text(encoding="utf-8"))
        sources_file.write_text(json.dumps({**sources, **changes}), encoding="utf-8")

    def kinsim_snapshot(self) -> dict:
        """The fixture loop's own snapshot: its checkout, its data home, its curriculum's and data home's files."""

        return {"schema": SCHEMA, "title": "Stored", "generated_at": "2026-09-01T00:00:00+00:00", "loop": "kinsim",
                "roots": {"repo": str(self.loop.repo), "data_home": str(self.loop.data_home)},
                "sources": [link(self.loop.curriculum_dir / "curriculum.json"), link(self.loop.data_home / "status.json")],
                "rungs": [{"id": "G1", "status": "green"}], "warnings": []}


class X01ConsumedSourcesOwnershipTest(_Fixture):
    def test_codex_reproduction_another_data_home_never_answers_a_failed_projection(self) -> None:
        self.store("kinsim", self.kinsim_snapshot())
        self.counting(side_effect=RuntimeError("injected failure"), wraps=None)
        self.write_sources(kinsim_home=UNRELATED_HOME)
        status, body = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 503, body)
        self.assertNotIn(str(self.loop.data_home), json.dumps(body))
        self.write_sources(kinsim_home=str(self.loop.data_home))  # its own data home: it answers, marked stale
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document["title"], document["generated_at"]), (200, "Stored", "2026-09-01T00:00:00+00:00"))
        self.assertTrue(document["warnings"][0].startswith("stale: "), document["warnings"])

    def test_another_curriculum_directory_in_the_same_checkout_is_not_this_one(self) -> None:
        other = self.loop.repo / "src" / "other_curriculum"
        shutil.copytree(self.loop.curriculum_dir, other)
        age(other)
        self.store("kinsim", self.kinsim_snapshot())
        self.counting(side_effect=RuntimeError("injected failure"), wraps=None)
        self.write_sources(kinsim_curriculum_dir=str(other))
        self.assertEqual(get_json("/doc", "track=kinsim")[0], 503)

    def test_an_absent_loops_snapshot_from_another_data_home_is_404(self) -> None:
        def grasping(data_home: Path) -> dict:
            return {"schema": SCHEMA, "title": "Grasp", "generated_at": "t", "loop": "grasping",
                    "roots": {"repo": str(self.tmp), "data_home": str(data_home)},
                    "sources": [link(self.tmp / "no-grasping" / "src" / "grasp_bench" / "curriculum.py")], "warnings": []}

        self.store("grasping", grasping(self.tmp / "elsewhere" / "out"))
        self.assertEqual(get_json("/doc", "track=grasping"), (404, {"error": "no roadmap reported yet"}))
        self.store("grasping", grasping(self.tmp / "no-grasping" / "out"))
        status, document = get_json("/doc", "track=grasping")
        self.assertEqual(status, 200)
        self.assertTrue(document["warnings"][0].startswith("stale: the grasping loop is not on this machine"))

    def test_each_projector_claims_every_key_it_reads(self) -> None:
        sources = {key: f"/configured/{key}" for projector in api.PROJECTORS.values() for key in projector.keys}
        for name, projector in api.PROJECTORS.items():
            with self.subTest(projector=name):
                claimed = {str(claim.location) for claim in projector.claims(sources)}
                for key in projector.keys:
                    self.assertTrue(any(location.startswith(sources[key]) for location in claimed), (key, claimed))


class X01RealSnapshotsTest(unittest.TestCase):
    """The real stored snapshots against this machine's default sources; skipped where they or their loops are absent."""

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

    def stored(self, track: str) -> dict:
        path = Path(api.load_sources()["roadmap_docs_dir"]) / f"{track}.json"
        if not path.is_file():
            self.skipTest(f"no stored {track} snapshot here ({path})")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_real_stored_snapshots_stay_eligible(self) -> None:
        for track in ("kinsim", "rig"):
            with self.subTest(track=track):
                document = self.stored(track)
                projector, sources = api.projector_for(track)
                self.assertTrue(api._owned(document, projector, sources), (track, document.get("roots")))

    def test_codex_reproduction_an_unrelated_kinsim_home_never_serves_the_real_snapshot(self) -> None:
        document = self.stored("kinsim")
        self.sources_file.write_text(json.dumps({"kinsim_home": UNRELATED_HOME}), encoding="utf-8")
        projector, sources = api.projector_for("kinsim")
        if not projector.present(sources):
            self.skipTest("the kinsim curriculum is not on this machine")
        with mock.patch("vibetracks.roadmap.api.project_kinsim", side_effect=RuntimeError("injected failure")):
            status, body = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 503, body)
        self.assertNotIn(document["roots"]["data_home"], json.dumps(body))


class X02SingleReadingTest(_Fixture):
    def test_codex_reproduction_a_change_after_the_final_comparison_is_not_blessed(self) -> None:
        acceptance = self.acceptance()
        self.assertEqual(get("/doc", "track=kinsim")[0], 200)
        version_2 = acceptance.stat().st_mtime_ns + 5_000_000_000
        armed = threading.Event()
        real_stamp = api._stamp

        def projected(*args, **kwargs):
            document = project_kinsim(*args, **kwargs)  # reads version 1
            armed.set()
            return document

        def stamp(*args, **kwargs):
            result = real_stamp(*args, **kwargs)
            if armed.is_set():  # the post-projection comparison has read version 1 again: then version 2 lands
                armed.clear()
                os.utime(acceptance, ns=(version_2, version_2))
            return result

        counted = self.counting(side_effect=projected, wraps=None)
        with mock.patch("vibetracks.roadmap.api._stamp", stamp):
            self.assertEqual(get("/doc", "track=kinsim&refresh=1")[0], 200)
        self.assertEqual(acceptance.stat().st_mtime_ns, version_2)
        self.assertEqual(counted.call_count, 1)
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)  # the version-1 verdict was not stamped with version 2
        get("/doc", "track=kinsim")
        self.assertEqual(counted.call_count, 2)  # read at version 2 before and after: settled


class X03ThreadedEvictionTest(_Fixture):
    def homes(self, count: int) -> list[Path]:
        homes = []
        for number in range(count):
            home = self.tmp / f"old-home-{number}"
            shutil.copytree(self.loop.data_home, home)
            homes.append(home)
        age(self.tmp)
        return homes

    def current_key(self) -> tuple:
        return api._cache_key("kinsim", api.KINSIM, api.load_sources())

    def test_codex_reproduction_four_paused_obsolete_requests_keep_the_current_document(self) -> None:
        current = str(self.loop.data_home)
        old_homes = self.homes(4)
        paused = {str(home): threading.Event() for home in old_homes}
        release = threading.Event()

        def present(sources) -> bool:
            if sources["kinsim_home"] in paused and not release.is_set():
                paused[sources["kinsim_home"]].set()  # resolved an obsolete configuration; stops before the cache
                release.wait(timeout=30)
            return api.KINSIM.present(sources)

        patcher = mock.patch.dict(api.PROJECTORS, {"kinsim": dataclasses.replace(api.KINSIM, present=present)})
        patcher.start()
        self.addCleanup(patcher.stop)
        results: list[int] = []
        threads = []
        for home in old_homes:
            self.write_sources(kinsim_home=str(home))
            thread = threading.Thread(target=lambda: results.append(get("/doc", "track=kinsim")[0]))
            thread.start()
            threads.append(thread)
            self.assertTrue(paused[str(home)].wait(timeout=30))
        self.write_sources(kinsim_home=current)
        status, good = get_json("/doc", "track=kinsim")
        self.assertEqual(status, 200)
        entry = api._CACHES[self.current_key()]
        release.set()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(results, [200] * 4)
        self.assertIs(api._CACHES.get(self.current_key()), entry)
        self.counting(side_effect=RuntimeError("current configuration failed"), wraps=None)
        touch(self.loop.data_home / "loop_events.jsonl")
        status, document = get_json("/doc", "track=kinsim")
        self.assertEqual((status, document.get("generated_at")), (200, good["generated_at"]), document)
        self.assertIn("current configuration failed", document["warnings"][0])

    def test_codex_reproduction_a_held_lock_survives_four_other_configurations(self) -> None:
        current = str(self.loop.data_home)
        old_homes = self.homes(4)
        entered, second_entered, release = threading.Event(), threading.Event(), threading.Event()
        in_flight, peak, guard = [0], [0], threading.Lock()

        def projected(curriculum_dir, data_home, **kwargs):
            if str(data_home) != current:
                return project_kinsim(curriculum_dir, data_home, **kwargs)
            with guard:
                in_flight[0] += 1
                peak[0] = max(peak[0], in_flight[0])
                first = not entered.is_set()
                (entered if first else second_entered).set()
            try:
                if first:
                    release.wait(timeout=30)  # the first request holds this configuration's lock, mid-projection
                return project_kinsim(curriculum_dir, data_home, **kwargs)
            finally:
                with guard:
                    in_flight[0] -= 1

        counted = self.counting(side_effect=projected, wraps=None)
        results: list[int] = []
        first = threading.Thread(target=lambda: results.append(get("/doc", "track=kinsim")[0]))
        first.start()
        self.assertTrue(entered.wait(timeout=30))
        entry = api._CACHES[self.current_key()]
        for home in old_homes:
            self.write_sources(kinsim_home=str(home))
            self.assertEqual(get("/doc", "track=kinsim")[0], 200)
        self.write_sources(kinsim_home=current)
        second = threading.Thread(target=lambda: results.append(get("/doc", "track=kinsim")[0]))
        second.start()
        self.assertFalse(second_entered.wait(timeout=1.0), "a second lock let another projection start beside the first")
        self.assertIs(api._CACHES.get(self.current_key()), entry)
        release.set()
        first.join(timeout=60)
        second.join(timeout=60)
        self.assertEqual((results, peak[0]), ([200, 200], 1))
        self.assertEqual(counted.call_count, 5)  # the current configuration once, each other one once


class X03IdleEvictionTest(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.clock = [0.0]
        patcher = mock.patch("vibetracks.roadmap.api._clock", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def configuration(self, number: int) -> dict:
        return {"kinsim_home": f"/home-{number}"}

    def key(self, number: int) -> tuple:
        return api._cache_key("kinsim", api.KINSIM, self.configuration(number))

    def use(self, number: int) -> api._Cache:
        with api._acquired("kinsim", api.KINSIM, self.configuration(number)) as cache:
            return cache

    def test_an_idle_unheld_entry_goes_after_ten_minutes(self) -> None:
        self.use(0)
        self.clock[0] = api._IDLE_EVICT_S - 1
        self.use(1)
        self.assertIn(self.key(0), api._CACHES)
        self.clock[0] = api._IDLE_EVICT_S
        self.use(1)
        self.assertNotIn(self.key(0), api._CACHES)
        self.assertEqual(api._IDLE_EVICT_S, 600)

    def test_a_held_entry_is_never_evicted(self) -> None:
        with api._acquired("kinsim", api.KINSIM, self.configuration(0)) as held:
            self.clock[0] = 10 * api._IDLE_EVICT_S
            self.use(1)
            self.assertIs(api._CACHES.get(self.key(0)), held)
            self.assertEqual(held.refs, 1)
        self.assertEqual(held.refs, 0)

    def test_the_polled_configuration_survives_an_hour_of_other_configurations(self) -> None:
        polled = self.use(0)
        for tick in range(1, 121):  # every 30 s for an hour, a new configuration beside the polled one
            self.clock[0] = tick * 30.0
            self.assertIs(self.use(0), polled)
            self.use(tick)
            self.assertLessEqual(len(api._CACHES), int(api._IDLE_EVICT_S / 30) + 2)
        self.assertNotIn(self.key(1), api._CACHES)


if __name__ == "__main__":
    unittest.main()
