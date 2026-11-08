# core/domain/event.py

import logging
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


class Event:
    def __init__(
        self,
        id: int | None,
        dataset_id: int,
        sample_id: int | None,
        user_id: int,
        action: str,
        created_at: datetime | None = None,
    ):
        self.id = id
        self.dataset_id = dataset_id
        self.sample_id = sample_id
        self.user_id = user_id
        self.action = action
        self.created_at = created_at or datetime.now(timezone.utc)