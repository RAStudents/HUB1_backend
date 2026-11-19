from pydantic import BaseModel


class PrivacyPolicyResponse(BaseModel):
    title: str
    subtitle: str
    content: str
