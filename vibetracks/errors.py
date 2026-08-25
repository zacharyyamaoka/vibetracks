"""Exception types shared across Vibe Tracks."""

from __future__ import annotations


class VibeTracksError(RuntimeError):
    """Base error for anything the CLI or API reports to the caller."""


class RevisionConflict(VibeTracksError):
    """The note changed on disk after the caller read it. Reload and retry."""


class InvalidTransition(VibeTracksError):
    """The requested status is not part of this project's status set."""


class UnknownFeature(VibeTracksError):
    """No feature with the requested id exists in this project."""
