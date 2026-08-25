"""Vibe Tracks: file-first feature tracking with Graph, Kanban, and Focus views."""

from .edits import (
    append_feature_comment,
    create_feature,
    update_feature_dependencies,
    update_feature_status,
)
from .errors import (
    InvalidTransition,
    RevisionConflict,
    UnknownFeature,
    VibeTracksError,
)
from .project import TrackItem, TrackProject, load_project
from .scaffold import init_project

__all__ = [
    "InvalidTransition",
    "RevisionConflict",
    "TrackItem",
    "TrackProject",
    "UnknownFeature",
    "VibeTracksError",
    "append_feature_comment",
    "create_feature",
    "init_project",
    "load_project",
    "update_feature_dependencies",
    "update_feature_status",
]

__version__ = "0.2.0"
