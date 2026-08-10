from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session, sessionmaker

T = TypeVar("T")


class SessionRepository:
    """Run sync ORM work on a dedicated session, optionally via a worker thread."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def run(self, work: Callable[[Session], T]) -> T:
        """Execute ``work`` in a committed session. Assumes ``work`` uses only that session."""
        session = self._factory()
        try:
            result = work(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def call(self, work: Callable[[Session], T]) -> T:
        """Return ``work`` on a worker thread. Assumes ``work`` is thread-safe per session."""
        return await asyncio.to_thread(self.run, work)
