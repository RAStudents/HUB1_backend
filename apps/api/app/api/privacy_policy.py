from fastapi import APIRouter

from apps.api.app.privacy_policy_text import (
    PRIVACY_POLICY_SUBTITLE,
    PRIVACY_POLICY_TEXT,
    PRIVACY_POLICY_TITLE,
)
from apps.api.app.schemas.privacy_policy import PrivacyPolicyResponse


router = APIRouter(prefix="/privacy-policy", tags=["legal"])


@router.get("", response_model=PrivacyPolicyResponse, summary="Политика конфиденциальности")
def get_privacy_policy() -> PrivacyPolicyResponse:
    return PrivacyPolicyResponse(
        title=PRIVACY_POLICY_TITLE,
        subtitle=PRIVACY_POLICY_SUBTITLE,
        content=PRIVACY_POLICY_TEXT,
    )
