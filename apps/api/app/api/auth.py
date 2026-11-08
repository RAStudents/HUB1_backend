# apps/api/app/api/auth.py

import os
import httpx
import logging
from core.application.auth_service import AuthService
from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.api.app.deps import CurrentUser, get_auth_service, get_current_user


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])

YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "").strip()
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "").strip()
YANDEX_REDIRECT_URI = os.getenv(
    "YANDEX_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/yandex/callback"
).strip()


def _require_yandex_configured() -> None:
    """Проверяет, что Яндекс OAuth настроен; иначе возвращает 503."""
    if not YANDEX_CLIENT_ID or not YANDEX_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Вход через Яндекс временно недоступен (не заданы YANDEX_CLIENT_ID и "
                "YANDEX_CLIENT_SECRET). Используйте вход по email и паролю."
            ),
        )


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Регистрация по email и паролю")
def register(payload: dict,
             service: AuthService = Depends(get_auth_service)):
    try:
        return service.register(
            email=payload.get("email", ""),
            password=payload.get("password", ""),
            name=payload.get("name", "User"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/login", summary="Вход по email и паролю")
def login(payload: dict,
          service: AuthService = Depends(get_auth_service)):
    try:
        return service.authenticate(
            email=payload.get("email", ""),
            password=payload.get("password", ""),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.get("/me", summary="Профиль текущего пользователя")
def get_me(user: CurrentUser = Depends(get_current_user),
           service: AuthService = Depends(get_auth_service)):
    try:
        return service.get_profile(user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/me", summary="Изменить отображаемое имя в профиле")
def update_me(payload: dict,
              user: CurrentUser = Depends(get_current_user),
              service: AuthService = Depends(get_auth_service)):
    try:
        return service.update_profile(user_id=user.id, name=payload.get("name", ""))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/logout", summary="Выход из аккаунта")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"status": "ok", "message": "Вы вышли из аккаунта"}


@router.get("/yandex/login", summary="Получить ссылку для входа через Яндекс")
def yandex_login():
    _require_yandex_configured()
    auth_url = (
        f"https://oauth.yandex.ru/authorize?response_type=code"
        f"&client_id={YANDEX_CLIENT_ID}"
        f"&redirect_uri={YANDEX_REDIRECT_URI}"
    )
    return {"auth_url": auth_url}


@router.get("/yandex/callback", summary="Колбэк Яндекс OAuth")
async def yandex_callback(code: str,
                          service: AuthService = Depends(get_auth_service)):
    _require_yandex_configured()

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth.yandex.ru/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": YANDEX_CLIENT_ID,
                "client_secret": YANDEX_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ошибка обмена кода Яндекс: {token_resp.text}",
            )
        yandex_token = token_resp.json().get("access_token")

        info_resp = await client.get(
            "https://login.yandex.ru/info?format=json",
            headers={"Authorization": f"OAuth {yandex_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось получить профиль пользователя из Яндекса",
            )
        info = info_resp.json()

    yandex_id = str(info.get("id"))
    email = info.get("default_email") or f"{info.get('login')}@yandex.ru"
    name = (
        info.get("real_name")
        or info.get("display_name")
        or info.get("login")
        or "Yandex User"
    )
    return service.login_with_yandex(yandex_id=yandex_id, email=email, name=name)
