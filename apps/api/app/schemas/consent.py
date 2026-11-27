from datetime import datetime
from typing import Literal

from pydantic import BaseModel


ConsentAction = Literal["accepted", "rejected", "withdrawn"]


class ConsentActionRequest(BaseModel):
    action: ConsentAction


class ConsentStatusResponse(BaseModel):
    version: str
    consent_text: str
    policy_link_text: str
    policy_url: str
    action: ConsentAction | None
    recorded_at: datetime | None
