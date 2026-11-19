import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request, Response

from apps.api.app.consent_text import ELECTRONIC_USER_DATA_CONSENT_TEXT
from apps.api.app.deps import get_consent_repo
from apps.api.app.schemas.consent import (
    ConsentActionRequest,
    ConsentStatusResponse,
)


router = APIRouter(prefix="/consent", tags=["consent"])
ELECTRONIC_USER_DATA_CONSENT_VERSION = "1"
CONSENT_VISITOR_COOKIE = "consent_visitor_id"
_COOKIE_SECURE = os.getenv("HUB_ENV", "dev").strip().lower() in {"prod", "production"}


def _get_visitor_id(request: Request, response: Response) -> str:
    cookie_value = request.cookies.get(CONSENT_VISITOR_COOKIE)
    if cookie_value:
        try:
            return str(UUID(cookie_value))
        except ValueError:
            pass

    visitor_id = str(uuid4())
    response.set_cookie(
        key=CONSENT_VISITOR_COOKIE,
        value=visitor_id,
        max_age=60 * 60 * 24 * 365,
        path="/api/consent",
        secure=_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return visitor_id


def _response(record: dict | None) -> ConsentStatusResponse:
    return ConsentStatusResponse(
        version=ELECTRONIC_USER_DATA_CONSENT_VERSION,
        consent_text=ELECTRONIC_USER_DATA_CONSENT_TEXT,
        policy_link_text="Политика конфиденциальности",
        policy_url="/privacy-policy",
        action=record["action"] if record else None,
        recorded_at=record["created_at"] if record else None,
    )


@router.get("", response_model=ConsentStatusResponse, summary="Текущий статус согласия")
def get_consent_status(
    request: Request,
    response: Response,
    consent_repo=Depends(get_consent_repo),
) -> ConsentStatusResponse:
    visitor_id = _get_visitor_id(request, response)
    record = consent_repo.get_latest(
        visitor_id=visitor_id,
        version=ELECTRONIC_USER_DATA_CONSENT_VERSION,
    )
    return _response(record)


@router.post(
    "",
    response_model=ConsentStatusResponse,
    summary="Записать действие по согласию",
)
def record_consent_action(
    payload: ConsentActionRequest,
    request: Request,
    response: Response,
    consent_repo=Depends(get_consent_repo),
) -> ConsentStatusResponse:
    visitor_id = _get_visitor_id(request, response)
    latest = consent_repo.get_latest(
        visitor_id=visitor_id,
        version=ELECTRONIC_USER_DATA_CONSENT_VERSION,
    )

    if latest and latest["action"] == payload.action:
        return _response(latest)
    if payload.action == "withdrawn" and (
        latest is None or latest["action"] != "accepted"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Отозвать можно только ранее принятое согласие",
        )
    if payload.action == "rejected" and latest and latest["action"] == "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Для прекращения принятого согласия используйте действие withdrawn",
        )

    record = consent_repo.record(
        visitor_id=visitor_id,
        version=ELECTRONIC_USER_DATA_CONSENT_VERSION,
        action=payload.action,
    )
    return _response(record)
