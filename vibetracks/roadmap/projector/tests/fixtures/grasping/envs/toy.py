"""Fixture: the toy env implementation."""

from ..contracts import EnvSpec


def make_env(env_id: str, **options):
    return {"id": env_id, **options}
