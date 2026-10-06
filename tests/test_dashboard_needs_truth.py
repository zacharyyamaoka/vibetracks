"""Needs-you truth rules: what blocks, whose words a question is, whose words an option is.

    python3 -m pytest -q tests/test_dashboard_needs_truth.py      (from the repo root)

1. Blocking: an item counts toward ``blocking_now`` only when it names a rung, package or gate. A cell-only item
   (grasping's download approvals hold only that model's cells) never does, and an item naming a rung or gate does.
2. Verbatim asks: grasping's question is the model id plus the cells' own words ("M5.ggcnn · download approval"),
   detection's is the bold lead plus the first sentence (or bullet) after it, sliced from the note.
3. Options are the dashboard's answer affordances (``source: "dashboard"``), never presented as the loop's words.

Fixtures from ``test_dashboard_needs_counts`` (same shapes as the real files); ``LiveTruthTest`` reruns 1-2 against
this machine's real curriculum.py and plan note when they exist.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_dashboard_needs_counts import Fixture, triage_item
from vibetracks.dashboard import needs
from vibetracks.dashboard.adapters import detection as detection_adapter
from vibetracks.dashboard.adapters import grasping as grasping_adapter
from vibetracks.sources import load_sources

SOURCE_NOTE = "download approvals hold only that model's cells; no tier gate waits on them"


def triage(raw: dict, kinds: dict[str, str], *, finished: int = 4) -> dict:
    """One kinsim-style item whose block ids resolve to the given kinds."""
    return needs.build_triage_item("t", raw, finished=finished, unit="wave", events={}, answers={},
                                   rung_labels={block: (kind, None) for block, kind in kinds.items()}, roots=[],
                                   answer_channel_kind="chat_paste")


def prose(blocks: list[dict], *, default_md: str | None = None) -> dict:
    return needs._prose_item("t", "x", kind="approval", title="X", ask="X", context_md="", base_md="", question_md="",
                             default_md=default_md, applies_unit="unstated", blocks=blocks, evidence=[], asked_by="t",
                             updated_ts=None, raw_status="needs")


class BlockingRuleTest(unittest.TestCase):
    def test_a_cell_only_item_never_counts_as_blocking_now(self) -> None:
        cells = [{"id": "M5.ggcnn@toy/x", "kind": "cell", "label": None},
                 {"id": "M5.ggcnn@mujoco/stage0", "kind": "cell", "label": None}]
        for default_md in (None, "keep waiting"):  # no default, and a pending default
            with self.subTest(default=default_md):
                item = prose(cells, default_md=default_md)
                self.assertFalse(item["blocking_now"])
                self.assertNotEqual(item["group"], "blocking")
                self.assertEqual(needs._counts([item])["blocking_now"], 0)
                self.assertEqual(needs._counts([item])["wants_you"], 1, "still open: it wants Zach, it just blocks nothing")
        # The triage path: an open, never-defaulting item whose blocks resolve to cells.
        item = triage(triage_item("T9", after=None, blocks=["c1"]), {"c1": "cell"})
        self.assertFalse(item["blocking_now"])
        self.assertEqual(item["group"], "no_default")
        self.assertFalse(needs.holds_gate([{"kind": "cell"}]))
        self.assertFalse(needs.holds_gate([]))

    def test_an_item_that_blocks_a_rung_package_or_gate_counts(self) -> None:
        for kind in ("rung", "package", "gate"):
            with self.subTest(kind=kind):
                self.assertTrue(prose([{"id": "R1", "kind": kind, "label": None}])["blocking_now"])
                pending = triage(triage_item("T1", after=9, blocks=["R1"]), {"R1": kind})
                never = triage(triage_item("T2", after=None, blocks=["R1"]), {"R1": kind})
                for item in (pending, never):
                    self.assertTrue(item["blocking_now"], item["local_id"])
                    self.assertEqual(item["group"], "blocking")
                self.assertEqual(needs._counts([pending, never])["blocking_now"], 2)
        # A cell beside a rung still blocks: the rung is held.
        mixed = prose([{"id": "c", "kind": "cell", "label": None}, {"id": "H1", "kind": "rung", "label": None}])
        self.assertTrue(mixed["blocking_now"])
        # ... but not once its default is in effect (rig T4's rule).
        self.assertFalse(triage(triage_item("T4", after=1, blocks=["R1"]), {"R1": "rung"})["blocking_now"])

    def test_the_fixture_tracks_follow_the_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            grasping = needs.build_track("grasping", fx.paths, title="Grasping")
            detection = needs.build_track("detection", fx.paths, title="Detection")
        self.assertTrue(grasping["items"])
        for item in grasping["items"]:
            self.assertTrue(item["blocks"])
            self.assertEqual({block["kind"] for block in item["blocks"]}, {"cell"})
            self.assertFalse(item["blocking_now"])
        self.assertEqual(grasping["counts"]["blocking_now"], 0)
        self.assertIn(SOURCE_NOTE, grasping["source"]["note"])
        for item in detection["items"]:
            self.assertEqual(item["blocking_now"], bool(item["blocks"]), item["local_id"])


class VerbatimAskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_grasping_ask_is_the_model_id_and_the_cells_own_words(self) -> None:
        doc = needs.build_track("grasping", self.fx.paths, title="Grasping")
        text = self.fx.curriculum.read_text(encoding="utf-8")
        asks = {item["local_id"]: item["ask"] for item in doc["items"]}
        self.assertEqual(asks, {"M5.ggcnn": "M5.ggcnn · download approval", "M5.rngnet": "M5.rngnet · download approval"})
        for item in doc["items"]:
            model_id, phrase = item["ask"].split(" · ", 1)
            self.assertIn(f'"{model_id}"', text)
            self.assertIn(f'"{phrase}', text, "the phrase opens a CELLS why, verbatim")
            self.assertNotIn("?", item["ask"], "the file asks no question; the dashboard must not frame one")
        ggcnn = doc["items"][0]
        for verbatim in ("GG-CNN (planar, Cornell)", "Licence: BSD-3", "Needs a download (weights in the release zip)."):
            self.assertIn(verbatim, ggcnn["context_md"])

    def test_approval_phrases_never_reword(self) -> None:
        class Cell:
            def __init__(self, why: str) -> None:
                self.why = why
        cells = [Cell("download approval (planar classics, BSD-3)"), Cell("download approval"),
                 Cell("download approval: the bundled checkpoint is epoch 6/200 (AP 0.000)"), Cell("licence approval")]
        self.assertEqual(grasping_adapter.approval_phrases(cells), ["download approval", "licence approval"])

    def test_detection_ask_is_the_lead_plus_its_first_sentence(self) -> None:
        doc = needs.build_track("detection", self.fx.paths, title="Detection")
        note = self.fx.plan.read_text(encoding="utf-8")
        for item in doc["items"]:
            with self.subTest(item=item["local_id"]):
                self.assertIn(item["ask"], note, "a verbatim slice of the note")
                self.assertTrue(item["ask"].startswith(f"**{item['title']}** "), "more than the bold lead")
        asks = {item["local_id"]: item["ask"] for item in doc["items"]}
        self.assertEqual(asks["plan-3"], "**Start the loop.** The work order is ready.")

    def test_sentence_ends_survive_citations_bullets_and_decimals(self) -> None:
        plan = (
            "## Needs you\n\n"
            '1. **Host.** You wrote "on the windows box".[[Daily Note|1]] My recommendation is Linux, for 1.5 reasons:\n'
            "\t- the GPU is there\n\n\tMore. *Default if silent:* Linux.\n"
            "2. **Reasons.**\n\t- first bullet is the ask\n\t- second is context\n"
            "3. No bold lead at all. Then context.\n")
        entries = {entry["n"]: entry for entry in detection_adapter.parse_needs_section(plan)}
        self.assertEqual(entries["1"]["ask_md"], '**Host.** You wrote "on the windows box".[[Daily Note|1]]')
        self.assertEqual(entries["1"]["ask_rest_md"], "My recommendation is Linux, for 1.5 reasons:")
        self.assertEqual(entries["2"]["ask_md"], "**Reasons.**\n\t- first bullet is the ask")
        self.assertEqual(entries["3"]["ask_md"], "No bold lead at all.")
        self.assertEqual(entries["3"]["ask_rest_md"], "Then context.")
        for entry in entries.values():
            self.assertIn(entry["ask_md"], plan)

    def test_every_option_is_the_dashboards_and_none_is_recommended_without_a_recommendation(self) -> None:
        listed = needs.build_all(self.fx.paths)
        self.assertTrue(any(doc["items"] for doc in listed["tracks"]))
        for doc in listed["tracks"]:
            for item in doc["items"]:
                for option in item["options"]:
                    self.assertEqual(option["source"], "dashboard", (item["id"], option["key"]))
                    if not item["recommendation_md"].strip():
                        self.assertFalse(option["recommended"], (item["id"], option["key"]))


_SOURCES = load_sources()


@unittest.skipUnless(Path(_SOURCES.get("grasping_curriculum", "/nonexistent")).is_file()
                     and Path(_SOURCES.get("detection_plan_note", "/nonexistent")).is_file(),
                     "the grasp bench or the detection plan note is not on this machine")
class LiveTruthTest(unittest.TestCase):
    def test_live_grasping(self) -> None:
        doc = needs.build_track("grasping", _SOURCES, title="Grasping")
        text = Path(_SOURCES["grasping_curriculum"]).read_text(encoding="utf-8")
        self.assertIn(SOURCE_NOTE, doc["source"]["note"])
        self.assertEqual(doc["counts"]["blocking_now"], 0)
        for item in doc["items"]:
            with self.subTest(item=item["local_id"]):
                self.assertEqual({block["kind"] for block in item["blocks"]}, {"cell"})
                self.assertFalse(item["blocking_now"])
                model_id, phrase = item["ask"].split(" · ", 1)
                self.assertEqual(model_id, item["local_id"])
                for part in phrase.split(" / "):
                    self.assertIn(part, text)

    def test_live_detection(self) -> None:
        doc = needs.build_track("detection", _SOURCES, title="Detection")
        note = Path(_SOURCES["detection_plan_note"]).read_text(encoding="utf-8")
        for item in doc["items"]:
            with self.subTest(item=item["local_id"]):
                self.assertIn(item["ask"], note)
                self.assertGreater(len(item["ask"]), len(f"**{item['title']}**"), "more than the bold lead")


if __name__ == "__main__":
    unittest.main()
