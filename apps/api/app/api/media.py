# apps/api/app/api/media.py

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from apps.api.app.deps import get_s3_client
from core.infrastructure.s3.client import S3Client, media_signature_ok


logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.get("/media")
def read_media(key: str = Query(...),
               exp: int = Query(...),
               sig: str = Query(...),
               s3: S3Client = Depends(get_s3_client)):
    """Отдаёт только картинку и только по подписи. Каталог /storage снаружи закрыт."""
    if not media_signature_ok(key, exp, sig):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    try:
        path = s3.safe_path(key)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    media_type = _TYPES.get(path.suffix.lower())
    if media_type is None or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=300",
        },
    )