from __future__ import annotations

from riftlens.adapters.db.repositories.coaching import SqlCoachingRepository
from riftlens.adapters.db.repositories.finding import SqlFindingRepository
from riftlens.adapters.db.repositories.gameplay import SqlGameplayRepository
from riftlens.adapters.db.repositories.match import SqlMatchRepository
from riftlens.adapters.db.repositories.media import SqlMediaRepository
from riftlens.adapters.db.repositories.metric import SqlMetricRepository
from riftlens.adapters.db.repositories.player import SqlPlayerRepository
from riftlens.adapters.db.repositories.review import SqlReviewRepository
from riftlens.adapters.db.repositories.sync import SqlSyncRepository

__all__ = [
    "SqlCoachingRepository",
    "SqlFindingRepository",
    "SqlGameplayRepository",
    "SqlMatchRepository",
    "SqlMediaRepository",
    "SqlMetricRepository",
    "SqlPlayerRepository",
    "SqlReviewRepository",
    "SqlSyncRepository",
]
