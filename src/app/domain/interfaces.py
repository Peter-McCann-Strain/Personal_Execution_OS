"""Repository interfaces — abstract base classes for data access.

Each repository interface defines the contract for its data layer.
Concrete implementations live in ``src.app.persistence.repositories``.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.persistence.models import (
        Commitment,
        Contact,
        Episode,
        Goal,
        Note,
    )


class EpisodeRepositoryInterface(ABC):  # pragma: no cover
    @abstractmethod
    async def create(
        self,
        content: str,
        episode_type: str,
        source: str,
        summary: str | None = None,
        para_category: str | None = None,
        mood_score: float | None = None,
        energy_rating: float | None = None,
        tags: list[str] | None = None,
        people_mentioned: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Episode: ...

    @abstractmethod
    async def get_by_id(self, episode_id: uuid.UUID) -> Episode | None: ...

    @abstractmethod
    async def get_by_date_range(
        self, start: datetime, end: datetime, limit: int = 50
    ) -> list[Episode]: ...

    @abstractmethod
    async def update_episode(self, episode_id: uuid.UUID, **kwargs: object) -> Episode: ...

    @abstractmethod
    async def delete_episode(self, episode_id: uuid.UUID) -> bool: ...

    @abstractmethod
    async def search_bm25(self, query: str, limit: int = 20) -> list[dict[str, object]]: ...


class GoalRepositoryInterface(ABC):  # pragma: no cover
    @abstractmethod
    async def create(
        self,
        title: str,
        goal_type: str | None = None,
        parent_id: uuid.UUID | None = None,
        priority: int = 5,
        deadline: datetime | None = None,
        evidence: list[str] | None = None,
    ) -> Goal: ...

    @abstractmethod
    async def get_by_id(self, goal_id: uuid.UUID) -> Goal | None: ...

    @abstractmethod
    async def list_goals(
        self,
        status: str | None = None,
        goal_type: str | None = None,
        limit: int = 50,
    ) -> list[Goal]: ...

    @abstractmethod
    async def update(self, goal_id: uuid.UUID, **kwargs: object) -> Goal: ...

    @abstractmethod
    async def delete(self, goal_id: uuid.UUID) -> bool: ...


class NoteRepositoryInterface(ABC):  # pragma: no cover
    @abstractmethod
    async def create(
        self,
        title: str,
        content: str,
        note_type: str = "fleeting",
        para_category: str | None = None,
        tags: list[str] | None = None,
        source_url: str | None = None,
    ) -> Note: ...

    @abstractmethod
    async def get_by_id(self, note_id: uuid.UUID) -> Note | None: ...

    @abstractmethod
    async def update(self, note_id: uuid.UUID, **kwargs: object) -> Note: ...

    @abstractmethod
    async def delete(self, note_id: uuid.UUID) -> bool: ...

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[dict[str, object]]: ...

    @abstractmethod
    async def get_linked_notes(self, note_id: uuid.UUID) -> list[dict[str, object]]: ...


class ContactRepositoryInterface(ABC):  # pragma: no cover
    @abstractmethod
    async def create(
        self,
        first_name: str,
        last_name: str | None = None,
        email: str | None = None,
        tags: list[str] | None = None,
    ) -> Contact: ...

    @abstractmethod
    async def get_by_id(self, contact_id: uuid.UUID) -> Contact | None: ...

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[dict[str, object]]: ...

    @abstractmethod
    async def get_decaying_relationships(
        self, threshold: float = 30.0, limit: int = 10
    ) -> list[Contact]: ...


class CommitmentRepositoryInterface(ABC):  # pragma: no cover
    @abstractmethod
    async def create(
        self,
        verbatim_text: str,
        normalized_action: str,
        who_committed: str,
        who_to: str | None = None,
        temporal_expression: str | None = None,
        confidence_score: float = 1.0,
    ) -> Commitment: ...

    @abstractmethod
    async def get_overdue(self) -> list[Commitment]: ...

    @abstractmethod
    async def get_open(self, limit: int = 20) -> list[Commitment]: ...

    @abstractmethod
    async def update_status(self, commitment_id: uuid.UUID, status: str) -> Commitment: ...
