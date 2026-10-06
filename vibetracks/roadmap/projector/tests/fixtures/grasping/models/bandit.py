"""Fixture: the learned bandit."""

from . import heatmap


def make_bandit(env_id: str, **options):
    return heatmap.HeatmapNet()
