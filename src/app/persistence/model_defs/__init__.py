"""Internal domain modules for persistence model declarations.

The package eagerly loads every declaration so the shared SQLAlchemy registry is
complete even when an internal module is imported directly. Application code
should still import model classes through :mod:`src.app.persistence.models`.
"""

from src.app.persistence.model_defs import (
    base,
    connectors,
    memory,
    notifications,
    observability,
    operations,
    people,
    planning,
    platform,
    projects,
    voice,
    workflows,
)

__all__ = (
    "base",
    "connectors",
    "memory",
    "notifications",
    "observability",
    "operations",
    "people",
    "planning",
    "platform",
    "projects",
    "voice",
    "workflows",
)
