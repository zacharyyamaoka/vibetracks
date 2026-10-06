"""Fixture curriculum: 2 tiers, 3 envs, written in the real curriculum.py's idiom (comprehensions, stars, f-strings)."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import EnvSpec, ModelSpec

TIERS: dict[int, str] = {
    1: "Toy grasping - synthetic images (ex6-ex9)",
    3: "Real images, offline - a dataset",
}

_J = "analytic point/jaw"
ENVS: tuple[EnvSpec, ...] = (
    *(EnvSpec(f"toy/{name}", f"Toy {name}", 1, dof, "F0 analytic", "synthetic image", "top1_success", "planar", _J)
      for name, dof in (
          ("x", "1"),
          ("xy", "2"),
      )),
    EnvSpec("data/seen", "A dataset, seen split", 3, "3+3+1", "F2 analytic-on-real", "real RGB-D (dataset)", "ap",
            "6dof", "canonical jaw", min_grasps=50, request_k=300, notes="Reduced protocol data-30x4."),
)

MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("M0.uniform", "Random", 0, "floor", "none", "planar", False, "BAM (ours)"),
    ModelSpec("M1.oracle", "Oracle", 1, "privileged", "privileged", "planar", False, "BAM (ours)"),
    ModelSpec("M3.bandit", "Bandit", 3, "learned", "rgb", "planar", True, "BAM (ours)"),
    ModelSpec("M5.ggcnn", "GG-CNN", 5, "published", "depth", "planar", False, "BSD-3"),
)


@dataclass(frozen=True)
class Cell:
    model: str
    env: str
    status: str
    why: str = ""

    @property
    def id(self) -> str:
        return f"{self.model}@{self.env}"


_TOY = ("toy/x", "toy/xy")

CELLS: tuple[Cell, ...] = (
    *(Cell(m, e, "wave1") for e in _TOY for m in ("M0.uniform", "M1.oracle", "M3.bandit")),
    Cell("M5.ggcnn", "toy/xy", "needs", "download approval (planar classics, BSD-3)"),
    *(Cell(m, "data/seen", "wave1") for m in ("M0.uniform", "M1.oracle")),
    Cell("M3.bandit", "data/seen", "wave2"),
)

#: Wilson 95% lower bound of the best model's top-1 success over the frozen eval protocol.
GATES: dict[str, float] = {"toy/x": 0.97, "toy/xy": 0.95}

#: Dataset envs have no absolute gate: progress = AP above the previous best with a
#: paired, scene-bootstrapped 95% CI excluding zero.
PUBLISHED_AP: dict[str, dict[str, float]] = {"data/seen": {"A paper": 27.98}}


def cells(status: str | None = None) -> list[Cell]:
    return [c for c in CELLS if status is None or c.status == status]
