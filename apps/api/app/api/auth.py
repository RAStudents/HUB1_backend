# apps/api/app/api/auth.py

import hashlib
import logging
import os
from io import BytesIO
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.api.app.deps import CurrentUser, get_auth_service, get_current_user, get_s3_client
from core.application.auth_service import AuthService
from core.infrastructure.s3.client import S3Client
from core.infrastructure.s3.keys import user_avatar_key


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])

YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "").strip()
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "").strip()
YANDEX_REDIRECT_URI = os.getenv(
    "YANDEX_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/yandex/callback"
).strip()
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 40_000_000
AVATAR_SIZE = (512, 512)
YANDEX_AVATAR_SIZE = "islands-200"


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
            f"?v={version}"
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


async def _store_yandex_avatar(
    s3: S3Client,
    user_id: int,
    avatar_id: str | None,
) -> None:
    if not isinstance(avatar_id, str) or not avatar_id.strip():
        return

    try:
        key = user_avatar_key(user_id)
        if s3.get_bytes(key):
            return

        avatar_url = (
            f"https://avatars.yandex.net/get-yapic/{quote(avatar_id, safe='')}"
            f"/{YANDEX_AVATAR_SIZE}"
        )
        content = bytearray()
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", avatar_url, timeout=10.0) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_AVATAR_BYTES:
                    raise ValueError("Аватар Яндекса превышает допустимый размер")

                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_AVATAR_BYTES:
                        raise ValueError("Аватар Яндекса превышает допустимый размер")

        normalized_avatar = _normalize_avatar(bytes(content))
        s3.put_bytes(
            key,
            normalized_avatar,
            content_type="image/webp",
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning("Не удалось сохранить аватар Яндекса для пользователя %s: %s", user_id, exc)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/me", summary="Изменить отображаемое имя в профиле")
def update_me(request: Request,
              payload: dict,
              user: CurrentUser = Depends(get_current_user),
              service: AuthService = Depends(get_auth_service),
              s3: S3Client = Depends(get_s3_client)):
    try:
        profile = service.update_profile(user_id=user.id, name=payload.get("name", ""))
        return _profile_with_avatar(profile, user.id, request, s3)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        profile = service.get_profile(user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    s3.delete(user_avatar_key(user.id))
    return _profile_with_avatar(
        profile,
        user.id,
        request,
        s3,
    )


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
        f"&force_confirm=yes"
    )
    return {"auth_url": auth_url}


@router.get("/yandex/callback", summary="Колбэк Яндекс OAuth")
async def yandex_callback(code: str,
                          service: AuthService = Depends(get_auth_service),
                          s3: S3Client = Depends(get_s3_client)):
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
    auth_response = service.login_with_yandex(yandex_id=yandex_id, email=email, name=name)
    if not info.get("is_avatar_empty"):
        await _store_yandex_avatar(
            s3=s3,
            user_id=auth_response["user_id"],
            avatar_id=info.get("default_avatar_id"),
        )
    return auth_response
