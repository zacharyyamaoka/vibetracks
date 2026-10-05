"""Fixture: the scorer (the Wilson bound every gated row records)."""

import math


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    centre = (successes + z * z / 2) / (n + z * z)
    half = z * math.sqrt(successes * (n - successes) / n + z * z / 4) / (n + z * z)
    return centre - half, centre + half
