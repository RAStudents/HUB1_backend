from typing import Literal

from pydantic import BaseModel


class DatasetInvitationDTO(BaseModel):
    dataset_id: int
    dataset_name: str
    role: Literal["labeler", "observer"]
    inviter_name: str
