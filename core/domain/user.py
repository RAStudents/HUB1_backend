# core/domain/user.py

import logging


logger = logging.getLogger(__name__)


class User:
    def __init__(self,
                 id: int,
                 name: str) -> None:
        self.id = id
        self.name = name

    @property
    def id(self) -> int: #
        return self._id

    @id.setter
    def id(self, id: int) -> None:
        if not isinstance(id, int) or isinstance(id, bool):
            raise TypeError(f"'id' must be 'int', but got {type(id).__name__}")
        if id < 0:
            raise ValueError(f"'id' must be >= 0")
        self._id = id

    @property
    def name(self) -> str:
        """str: Gets the descriptive name of the event."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        if not isinstance(name, str):
            raise TypeError(f"Field 'name' should be '<str>', but got {type(name).__name__}")
        if len(name) == 0:
            raise ValueError("'component' length should be > 0")
        self._name = name

