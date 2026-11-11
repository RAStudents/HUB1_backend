# core/domain/users/admin.py

import logging
from typing import Optional

from core.domain.users.user import User


logger = logging.getLogger(__name__)


class Admin(User):
    def __init__(self,
                 id: int,
                 name: str,
                 role: Optional[str]) -> None:
        super().__init__(id=id,
                         name=name)
        self.role = role

    @property
    def role(self) -> Optional[str]:
        return self._role

    @role.setter
    def role(self, role: Optional[str]) -> None:
        if role is not None:
            if not isinstance(role, str):
                raise TypeError("dfdsf")
        self._role = role