"""A tiny planned ladder in the shape of docs/hyperspectral/ladder_data.py: rungs as dict(...) calls, tuples for the rest.

D2 waits on D0 and D1, D3 on D0, D4 on D2 and D3, so the order and the dependencies are both worth checking.
"""

RUNGS = [
    dict(id="D0", short="Plumbing ruler", needs="nothing", needs_rungs=[], kind="correctness",
         question="Do cube I/O and the metric code compute right?",
         gate="coupons 100%; metrics match an independent library",
         gate_short="coupons 100%",
         ruler="Analytic coupons"),
    dict(id="D1", short="Published ruler", needs="drive", needs_rungs=[], kind="external",
         question="Does our harness reproduce the paper's table?",
         gate="All 8 configs within +-2 mIoU of the paper (3 of 8 pass today).",
         gate_short="8 configs within +-2 mIoU",
         ruler="The paper's numbers"),
    dict(id="D2", short="Sim to real", needs="drive", needs_rungs=["D0", "D1"], kind="external",
         needs_detail={"D1": "only the RGB rows reproduced"},
         question="Does synthetic pretraining help at the same label budget?",
         gate="Mean test lift of at least 3 mIoU over 5 paired runs.",
         gate_short="lift >= 3 mIoU",
         ruler="The real test split"),
    dict(id="D3", short="Mock sensors", needs="nothing", needs_rungs=["D0"], kind="correctness",
         question="Can one scene drive three registered twins?",
         gate="Same seed gives the same cube hash.",
         gate_short="deterministic",
         ruler="Scene ground truth"),
    dict(id="D4", short="Real stream", needs="rig", needs_rungs=["D2", "D3"], kind="external",
         question="On a real stream, is it as good as an optical sorter?",
         gate="Purity of at least 95% at recovery of at least 90%.",
         gate_short="purity >= 95% at recovery >= 90%",
         ruler="Human-checked masks"),
]

KPIS = [
    # slot, kpi, definition, today, target
    ("S1 North star", "Real test mIoU", "E3 test mIoU", "no valid result", ">= 58.2"),
    ("S2 Frontier gate", "The current rung's gate metric", "the gate's own number", "D1: 3 of 8 configs reproduced", "the rung's gate"),
]
