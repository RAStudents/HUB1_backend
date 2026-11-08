# core/domain/membership.py

import logging
from core.domain.enums import RoleEnum


logger = logging.getLogger(__name__)


class Membership:
    def __init__(
        self,
        id: int | None,
        dataset_id: int,
        user_id: int,
        role: RoleEnum | str,
    ):
        self.id = id
        self.dataset_id = dataset_id
        self.user_id = user_id
        self.role = RoleEnum(role) if isinstance(role, str) else role