"""Fixture: grasp_bench's runner.py frozen-protocol table (read as literals, never imported), and its imports (the
runner's freshness scope: what it runs and scores with)."""

from __future__ import annotations

import numpy as np

from . import registry, stats
from .contracts import EnvSpec, EvalProtocol

DEFAULT_PROTOCOLS: dict[str, tuple[str, int]] = {
    "toy": ("eval-2000", 2000),
    "data": ("data-30x4", 120),
}
FALLBACK_PROTOCOL = ("eval-200", 200)


def default_k(spec) -> int:
    return max(spec.request_k, spec.min_grasps, 1)
