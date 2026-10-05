"""Fixture: the slice of grasp_bench's contracts.py the projector reads (dataclass fields, never executed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np  # never imported by the projector: it reads this file's syntax tree only


@dataclass(frozen=True)
class EnvSpec:
    id: str
    title: str
    tier: int
    dof: str
    fidelity: str
    sensor: str
    metric: str
    accepts: str
    embodiment: str
    min_grasps: int = 1
    request_k: int = 1
    notes: str = ""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    title: str
    rank: int
    family: str
    input: str
    output: str
    trains: bool
    licence: str
    notes: str = ""


@dataclass(frozen=True)
class EvalProtocol:
    name: str
    episodes: int
    seed: int = 20261004
    split: str = "test"
    options: dict[str, Any] = field(default_factory=dict)


def not_data() -> np.ndarray:
    return np.zeros(3)
