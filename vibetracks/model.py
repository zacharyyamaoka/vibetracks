"""Compatibility facade.

The original single-module implementation grew into focused modules:
`descriptor`, `notes`, `project`, `edits`, `scaffold`. Import from the package
root (`vibetracks`) in new code; this module keeps the old import path alive.
"""

from __future__ import annotations

from .descriptor import DEFAULT_PROPERTIES, DEFAULT_STATUSES
from .edits import (
    append_feature_comment,
    create_feature,
    update_feature_dependencies,
    update_feature_status,
)
from .errors import InvalidTransition, RevisionConflict, UnknownFeature, VibeTracksError
from .project import TrackItem, TrackProject, load_project

__all__ = [
    "DEFAULT_PROPERTIES",
    "DEFAULT_STATUSES",
    "InvalidTransition",
    "RevisionConflict",
    "TrackItem",
    "TrackProject",
    "UnknownFeature",
    "VibeTracksError",
    "append_feature_comment",
    "create_feature",
    "load_project",
    "update_feature_dependencies",
    "update_feature_status",
]
