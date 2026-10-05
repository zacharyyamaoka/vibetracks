"""Fixture: grasp_bench's registry.py, the only place that names each (model, env-family) cell's code."""

from __future__ import annotations

import importlib

ENV_FACTORIES: dict[str, str] = {
    "toy": "envs.toy:make_env",
}

MODEL_FACTORIES: dict[tuple[str, str], str] = {
    ("M0.uniform", "toy"): "models.simple:uniform",
    ("M1.oracle", "toy"): "models.simple:label_oracle",
    ("M3.bandit", "toy"): "models.bandit:make_bandit",
}


def make_env(env_id: str, **options):
    module, function = ENV_FACTORIES[env_id.split("/", 1)[0]].split(":")
    return getattr(importlib.import_module(f"grasp_bench.{module}"), function)(env_id, **options)
