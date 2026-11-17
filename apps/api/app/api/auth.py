# apps/api/app/api/auth.py

import os
import jwt
import time
import httpx
import hashlib
import logging
import secrets
from io import BytesIO
from typing import Any
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.api.app.errors import client_error
from apps.api.app.deps import CurrentUser, get_auth_service, get_auth_token_repo, get_current_user, get_s3_client
from apps.api.app.schemas.auth import LoginRequest, LogoutRequest, NameUpdateRequest, RefreshRequest, RegisterRequest

from core.config import LOCAL_API_BASE_URL
from core.application.auth_service import AuthService

from core.infrastructure.s3.client import S3Client
from core.infrastructure.s3.keys import user_avatar_key
from core.infrastructure.auth.tokens import decode_access_claims, jwt_secret


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])
optional_security = HTTPBearer(auto_error=False)

YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "").strip()
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "").strip()
YANDEX_REDIRECT_URI = os.getenv(
    "YANDEX_REDIRECT_URI", f"{LOCAL_API_BASE_URL}/api/auth/yandex/callback"
).strip()
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 40_000_000
AVATAR_SIZE = (512, 512)
_ATTEMPTS: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limit(bucket: str, limit: int = 10, window: int = 600) -> None:
    now = time.monotonic()
    hits = [item for item in _ATTEMPTS.get(bucket, []) if now - item < window]
    if len(hits) >= limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Слишком много попыток")
    hits.append(now)
    _ATTEMPTS[bucket] = hits


def _yandex_state() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"purpose": "yandex", "nonce": secrets.token_hex(16), "exp": now + timedelta(minutes=10), "iat": now},
        jwt_secret(),
        algorithm="HS256",
    )


def _check_yandex_state(state: str) -> None:
    try:
        payload = jwt.decode(state, jwt_secret(), algorithms=["HS256"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный state") from exc
    if payload.get("purpose") != "yandex":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный state")


def _profile_with_avatar(profile: dict[str, Any],
                         user_id: int,
                         request: Request,
                         s3: S3Client) -> dict[str, Any]:
    avatar_bytes = s3.get_bytes(user_avatar_key(user_id))
    avatar_url = None
    if avatar_bytes:
        version = hashlib.sha256(avatar_bytes).hexdigest()[:12]
        avatar_url = (
            f"{s3.get_presigned_url(user_avatar_key(user_id), base_url=str(request.base_url))}"
            f"&v={version}"
        )
    return {**profile, "avatar_url": avatar_url}


def _normalize_avatar(content: bytes) -> bytes:
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Поддерживаются только изображения JPEG, PNG и WebP")
            width, height = source.size
            if width < 1 or height < 1 or width * height > MAX_AVATAR_PIXELS:
                raise ValueError("Изображение слишком большое")

            image = ImageOps.exif_transpose(source)
            image.thumbnail(AVATAR_SIZE, Image.Resampling.LANCZOS)
            mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            image = image.convert(mode)
            output = BytesIO()
            image.save(output, format="WEBP", quality=86, method=5)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Не удалось прочитать изображение. Выберите JPEG, PNG или WebP") from exc


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
def register(payload: RegisterRequest,
             request: Request,
             service: AuthService = Depends(get_auth_service)):
    _limit(f"register:{_client_ip(request)}")
    try:
        return service.register(email=payload.email, password=payload.password, name=payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc))


@router.post("/login", summary="Вход по email и паролю")
def login(payload: LoginRequest,
          request: Request,
          service: AuthService = Depends(get_auth_service)):
    _limit(f"login:{_client_ip(request)}:{payload.email.strip().lower()}")
    try:
        return service.authenticate(email=payload.email, password=payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=client_error(exc))


@router.get("/me", summary="Профиль текущего пользователя")
def get_me(request: Request,
           user: CurrentUser = Depends(get_current_user),
           service: AuthService = Depends(get_auth_service),
           s3: S3Client = Depends(get_s3_client)):
    try:
        return _profile_with_avatar(
            service.get_profile(user_id=user.id),
            user_id=user.id,
            request=request,
            s3=s3,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc))


@router.patch("/me", summary="Изменить отображаемое имя в профиле")
def update_me(request: Request,
              payload: NameUpdateRequest,
              user: CurrentUser = Depends(get_current_user),
              service: AuthService = Depends(get_auth_service),
              s3: S3Client = Depends(get_s3_client)):
    try:
        profile = service.update_profile(user_id=user.id, name=payload.name)
        return _profile_with_avatar(profile, user.id, request, s3)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc))


@router.put("/me/avatar", summary="Загрузить аватар профиля")
async def upload_avatar(request: Request,
                        file: UploadFile = File(...),
                        user: CurrentUser = Depends(get_current_user),
                        service: AuthService = Depends(get_auth_service),
                        s3: S3Client = Depends(get_s3_client)):
    content = await file.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Размер аватара не должен превышать 5 МБ",
        )
    try:
        avatar = _normalize_avatar(content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc))

    try:
        profile = service.get_profile(user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc))
    s3.put_bytes(user_avatar_key(user.id), avatar, content_type="image/webp")
    return _profile_with_avatar(
        profile,
        user.id,
        request,
        s3,
    )


@router.delete("/me/avatar", summary="Удалить аватар профиля")
def delete_avatar(request: Request,
                  user: CurrentUser = Depends(get_current_user),
                  service: AuthService = Depends(get_auth_service),
                  s3: S3Client = Depends(get_s3_client)):
    try:
        profile = service.get_profile(user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc))
    s3.delete(user_avatar_key(user.id))
    return _profile_with_avatar(
        profile,
        user.id,
        request,
        s3,
    )


@router.post("/logout", summary="Выход из аккаунта")
def logout(payload: LogoutRequest | None = None,
           credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
           service: AuthService = Depends(get_auth_service),
           token_repo=Depends(get_auth_token_repo)):
    refresh_token = payload.refresh_token if payload is not None else None
    claims = decode_access_claims(credentials.credentials) if credentials is not None else None
    if claims is not None and not token_repo.is_access_revoked(claims["jti"]):
        service.logout(
            user_id=int(claims["sub"]),
            jti=claims["jti"],
            access_expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
            refresh_token=refresh_token,
        )
        return {"status": "ok", "message": "Вы вышли из аккаунта"}

    if refresh_token:
        service.logout_refresh_only(refresh_token)
        return {"status": "ok", "message": "Вы вышли из аккаунта"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недействительный или просроченный токен авторизации",
    )


@router.post("/refresh", summary="Обменять refresh-токен на новую пару")
def refresh_session(payload: RefreshRequest,
                    request: Request,
                    service: AuthService = Depends(get_auth_service)):
    _limit(f"refresh:{_client_ip(request)}")
    try:
        return service.refresh(refresh_token=payload.refresh_token)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=client_error(exc))


@router.get("/yandex/login", summary="Получить ссылку для входа через Яндекс")
def yandex_login():
    _require_yandex_configured()
    state = _yandex_state()
    auth_url = (
        "https://oauth.yandex.ru/authorize?response_type=code"
        f"&client_id={quote(YANDEX_CLIENT_ID, safe='')}"
        f"&redirect_uri={quote(YANDEX_REDIRECT_URI, safe='')}"
        #"&force_confirm=yes"
        f"&state={quote(state, safe='')}"
    )
    return {"auth_url": auth_url}


@router.get("/yandex/callback", summary="Колбэк Яндекс OAuth")
async def yandex_callback(code: str,
                          state: str,
                          service: AuthService = Depends(get_auth_service)):
    _require_yandex_configured()
    _check_yandex_state(state)

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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ошибка обмена кода Яндекс")
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

    yandex_id = info.get("id")
    email = info.get("default_email")
    if not yandex_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Яндекс не вернул id или email",
        )
    name = (
        info.get("real_name")
        or info.get("display_name")
        or info.get("login")
        or "Yandex User"
    )
    try:
        return service.login_with_yandex(yandex_id=str(yandex_id), email=email, name=name)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=client_error(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc))