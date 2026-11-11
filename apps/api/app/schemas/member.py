# apps/api/app/schemas/member.py

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


MemberRole = Literal["owner", "labeler", "observer"]
AssignableMemberRole = Literal["labeler", "observer"]


class AddDatasetMemberDTO(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: AssignableMemberRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if (
            len(normalized) > 255
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized)
        ):
            raise ValueError("Некорректный email")
        return normalized


class UpdateDatasetMemberRoleDTO(BaseModel):
    role: AssignableMemberRole


class DatasetMemberDTO(BaseModel):
    user_id: int
    email: str
    name: str
    role: MemberRole
    notification_id: int | None = None
    email_notification_sent: bool | None = None