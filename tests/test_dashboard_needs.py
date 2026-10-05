"""vibetracks/dashboard/needs.py: the live "Needs you" projection (vibetracks-needs/1) and its /needs mount.

    python3 -m unittest tests/test_dashboard_needs.py      (from the repo root)

Every test builds its own loop folders in a temp dir; the live files are never required.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vibetracks.dashboard import needs


def item(triage_id, *, after, blocks=(), status="open", question="Q.", recommendation="R.", default="D.", wave=1):
    return {"triage_id": triage_id, "title": f"Title of {triage_id}", "opened_wave": wave, "question": question,
            "recommendation": recommendation, "default": default, "default_applies_after_wave": after,
            "blocks": list(blocks), "status": status}


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.kinsim_dir = root / "repo" / "src" / "dev" / "bam_curriculum"
        self.kinsim_home = root / "home"
        self.rig_dir = root / "rig" / "src" / "dev" / "bam_rig_loop"
        for path in (self.kinsim_dir / "research", self.kinsim_home, self.rig_dir):
            path.mkdir(parents=True)
        (root / "repo" / ".git").mkdir()
        (self.kinsim_dir / "research" / "w3-belt.md").write_text("# belt\n", encoding="utf-8")
        self.write_kinsim([
            item("T1", after=1, status="defaulted"),
            item("T11", after=1),                                   # open, but its default applied after wave 1
            item("T12", after=None, default="Do not land; ask again."),
            item("T47", after=5, blocks=["BT3", "BT4"],
                 question="Filed at wave-3 close from `research/w3-belt.md` §5. No pick exists at 1.0 m/s. More."),
            item("T52", after=4, blocks=["VZ3"]),                   # wave 4 finished -> in effect -> not blocking
            item("T53", after=6, blocks=[]),                        # pending, blocks nothing -> waiting
            item("T60", after=6),                                   # will be answered via jsonl but still 'open'
        ])
        self.write_json(self.kinsim_home / "status.json", {"wave": 4, "phase": "between_waves", "blocking_triage": ["T47"],
                                                           "rungs": [{"rung_id": "BT3", "title": "Belt 1.0 m/s"}]})
        events = [
            {"kind": "triage_changed", "subject": "T45-T48", "status": "opened", "ts": "2026-10-03T04:25:43+00:00", "detail": "opened"},
            {"kind": "wave_finished", "wave": 4, "ts": "2026-10-05T00:55:48+00:00"},
        ]
        (self.kinsim_home / "loop_events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        answers = [{"ts": "2026-10-04T10:00:00+00:00", "triage_id": "T60", "choice": "other", "note": "first"},
                   {"ts": "2026-10-04T11:00:00+00:00", "triage_id": "T60", "choice": "use_default", "note": ""},
                   "not json at all"]
        (self.kinsim_home / "triage_answers.jsonl").write_text(
            "".join((json.dumps(a) if isinstance(a, dict) else a) + "\n" for a in answers), encoding="utf-8")
        self.write_json(self.rig_dir / "triage.json", {"schema": "bam-triage/1", "items": [
            item("T1", after=None, status="answered",
                 recommendation='Remove them. Answer: Zach 2026-10-02: "yes you can delete old worktrees". Removed 5.'),
            item("T2", after=None, blocks=["BN1"], question="Base text. UPDATE 2026-10-03 (round 6): newer. UPDATE 17:15: W0c round 7: timed. UPDATE 2026-10-04 (round 9): newest."),
            item("T4", after=1, blocks=["BN1"]),
            item("T12", after=None, status="answered", recommendation="Resolved 2026-10-03: freed outside this loop."),
            item("T13", after=4),
            item("T17", after=None, default="No default: real-arm motion stays disabled until you answer."),
        ]})
        self.write_json(self.rig_dir / "loop-status.json", {"tick": {"kind": "wave", "n": 4, "phase": "running"}})
        self.write_json(self.rig_dir / "ladder.json", {"axes": [{"rungs": [{"id": "BN1", "title": "Window 1"}]}], "packages": []})
        (self.rig_dir / "loop_events.jsonl").write_text(json.dumps(
            {"kind": "triage_changed", "subject": "T17", "status": "open", "ts": "2026-10-04T09:00:00-07:00",
             "detail": "Opened T17: arm support"}) + "\n", encoding="utf-8")

    def write_kinsim(self, items) -> None:
        self.write_json(self.kinsim_dir / "triage.json", {"schema": "bam-triage/1", "items": items})

    @staticmethod
    def write_json(path: Path, data) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def sources(self) -> dict[str, str]:
        return {"kinsim_triage_dir": str(self.kinsim_dir), "kinsim_home": str(self.kinsim_home),
                "rig_loop_dir": str(self.rig_dir), "bam_ws_root": str(self.root / "nonexistent-repo"),
                "kinsim_loop_branch": "no-such-branch", "rig_loop_branch": "no-such-branch"}


class NeedsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))
        self.sources = self.fx.sources()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def kinsim(self):
        return needs.build_track("kinsim", self.sources)

    def by_id(self, doc):
        return {it["local_id"]: it for it in doc["items"]}

    def test_every_source_field_survives_verbatim(self) -> None:
        doc = self.kinsim()
        self.assertEqual(doc["schema"], "vibetracks-needs/1")
        t47 = self.by_id(doc)["T47"]
        self.assertEqual(t47["id"], "kinsim:T47")
        self.assertEqual(t47["title"], "Title of T47")
        self.assertIn("No pick exists at 1.0 m/s", t47["context_md"])
        self.assertEqual(t47["recommendation_md"], "R.")
        self.assertEqual(t47["default"]["text_md"], "D.")
        self.assertEqual(t47["default"]["applies"], {"unit": "wave", "after": 5})
        self.assertEqual([b["id"] for b in t47["blocks"]], ["BT3", "BT4"])
        self.assertEqual(t47["blocks"][0]["label"], "Belt 1.0 m/s")
        self.assertEqual(t47["created"], {"iteration": 1, "ts": "2026-10-03T04:25:43+00:00"})
        self.assertEqual([o["key"] for o in t47["options"]], ["accept_recommendation", "use_default", "other"])
        self.assertEqual(t47["provenance_md"], "Filed at wave-3 close from `research/w3-belt.md` §5.")
        self.assertEqual(t47["context_lead_md"], "No pick exists at 1.0 m/s.")
        self.assertIsNone(t47["context_summary"], "the dashboard never invents a summary")

    def test_evidence_is_absolute_and_exists(self) -> None:
        t47 = self.by_id(self.kinsim())["T47"]
        self.assertEqual(len(t47["evidence"]), 1)
        evidence = t47["evidence"][0]
        self.assertEqual(evidence["path"], str(self.fx.kinsim_dir / "research" / "w3-belt.md"))
        self.assertTrue(Path(evidence["path"]).is_absolute())

    def test_default_state_is_computed_not_trusted(self) -> None:
        items = self.by_id(self.kinsim())
        self.assertEqual(items["T11"]["status"], "open")
        self.assertEqual(items["T11"]["default"]["state"], "in_effect")
        self.assertEqual(items["T52"]["default"]["state"], "in_effect")
        self.assertFalse(items["T52"]["blocking_now"], "a default in effect stops blocking")
        self.assertEqual(items["T47"]["default"]["state"], "pending")
        self.assertTrue(items["T47"]["blocking_now"])
        self.assertEqual(items["T12"]["default"]["state"], "none")
        self.assertEqual(items["T12"]["default"]["applies"]["unit"], "never")

    def test_order_blocking_first_then_by_when_default_fires(self) -> None:
        groups = [(it["local_id"], it["group"]) for it in self.kinsim()["items"]]
        self.assertEqual(groups[0], ("T47", "blocking"))
        self.assertEqual(groups[1], ("T12", "no_default"))
        self.assertEqual(groups[2], ("T53", "waiting"))
        self.assertEqual([g for _, g in groups], sorted([g for _, g in groups], key=needs.GROUP_ORDER.index))

    def test_jsonl_answer_latest_row_wins_and_counts(self) -> None:
        doc = self.kinsim()
        t60 = self.by_id(doc)["T60"]
        self.assertEqual(t60["status"], "answered")
        self.assertEqual(t60["raw_status"], "open")
        self.assertEqual(t60["answer"]["choice"], "use_default")
        self.assertFalse(t60["answer"]["folded"])
        self.assertEqual(doc["counts"]["blocking_now"], 1)
        self.assertEqual(doc["counts"]["no_default"], 1)
        self.assertEqual(doc["answer_channel"]["row_schema"], "bam-triage-answer/1")
        self.assertEqual(doc["iteration"]["finished"], 4)

    def test_rig_finished_iteration_and_no_default_blocking(self) -> None:
        doc = needs.build_track("rig", self.sources)
        items = self.by_id(doc)
        self.assertEqual(doc["iteration"]["finished"], 3, "wave 4 is running, so wave 3 is the last finished")
        self.assertTrue(items["T2"]["blocking_now"], "no default + blocks a rung")
        self.assertEqual(items["T2"]["group"], "blocking")
        self.assertEqual(items["T17"]["group"], "no_default")
        self.assertEqual(items["T13"]["default"]["state"], "pending")
        self.assertEqual(items["T4"]["group"], "defaulting")
        self.assertEqual(doc["answer_channel"]["kind"], "chat_paste")
        self.assertIsNone(doc["answer_channel"]["row_schema"])
        self.assertEqual(items["T17"]["created"]["ts"], "2026-10-04T09:00:00-07:00")

    def test_rig_updates_split_verbatim(self) -> None:
        t2 = self.by_id(needs.build_track("rig", self.sources))["T2"]
        self.assertEqual(t2["context_base_md"], "Base text.")
        self.assertEqual([u["header"] for u in t2["updates"]], ["2026-10-03 (round 6)", "17:15", "2026-10-04 (round 9)"])
        self.assertEqual(t2["updates"][1]["text_md"], "W0c round 7: timed.")
        self.assertEqual(t2["updates"][-1]["text_md"], "newest.")
        self.assertEqual(t2["updated"]["note"], "UPDATE 2026-10-04 (round 9)")

    def test_rig_folded_answer_is_quoted_and_unattributed_resolution_is_not(self) -> None:
        items = self.by_id(needs.build_track("rig", self.sources))
        self.assertEqual(items["T1"]["answer"]["note"], "yes you can delete old worktrees")
        self.assertEqual(items["T1"]["answer"]["by"], "zach")
        self.assertEqual(items["T1"]["answer"]["action_md"], "Removed 5.")
        self.assertIsNone(items["T12"]["answer"]["by"], "resolved by circumstance is not Zach's answer")

    def test_unstructured_tracks_are_empty_with_a_note(self) -> None:
        for track in ("grasping", "detection", "pyblocks"):
            doc = needs.build_track(track, self.sources)
            self.assertEqual(doc["items"], [])
            self.assertTrue(doc["source"]["note"])
            self.assertFalse(doc["source"]["live"])

    def test_missing_loop_is_an_empty_doc_not_a_crash(self) -> None:
        sources = dict(self.sources, kinsim_triage_dir=str(self.fx.root / "gone"))
        doc = needs.build_track("kinsim", sources)
        self.assertEqual(doc["items"], [])
        self.assertIn("not found", doc["source"]["note"])

    def test_subject_ranges(self) -> None:
        self.assertEqual(needs.parse_subject_ids("T14 T45 T46 T48-T51"), {"T14", "T45", "T46", "T48", "T49", "T50", "T51"})
        self.assertEqual(needs.parse_subject_ids("T52-T57"), {f"T{n}" for n in range(52, 58)})


class RouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))
        self.sources = self.fx.sources()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def get(self, subpath, **query):
        status, headers, body = needs.handle("GET", subpath, {k: [v] for k, v in query.items()}, {}, sources=self.sources)
        return status, headers, b"".join(body)

    def test_one_track_and_all(self) -> None:
        status, headers, body = self.get("", track="kinsim")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["track"], "kinsim")
        status, _, body = self.get("")
        data = json.loads(body)
        self.assertEqual(data["schema"], "vibetracks-needs-all/1")
        self.assertEqual([d["track"] for d in data["tracks"]], [t for t, _ in needs.TRACKS])

    def test_unknown_track_404(self) -> None:
        self.assertEqual(self.get("", track="nope")[0], 404)

    def test_evidence_served_only_from_the_items_own_list(self) -> None:
        status, headers, body = self.get("/evidence", track="kinsim", item="kinsim:T47", n="0")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"# belt\n")
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertEqual(self.get("/evidence", track="kinsim", item="T47", n="1")[0], 404)
        self.assertEqual(self.get("/evidence", track="kinsim", item="T47", n="x")[0], 400)
        self.assertEqual(self.get("/evidence", track="kinsim", item="T999", n="0")[0], 404)

    def test_mount_is_registered(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mounts_under_test", Path(__file__).resolve().parents[1] / "clank" / "backend" / "mounts.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn(("/needs", "vibetracks.dashboard.needs:handle"), module.MOUNTS)


if __name__ == "__main__":
    unittest.main()
