"""The rungs are data but the KPI table is computed: the ladder still projects, with a warning and no frontier."""

RUNGS = [dict(id="K0", short="Only rung", needs="nothing", needs_rungs=[], kind="correctness", question="q", gate="g", gate_short="g", ruler="r")]

KPIS = [("S2 Frontier gate", "k", "d", "K0: " + str(2 * 3) + " of 12", "t")]
