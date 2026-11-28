# apps/api/app/uploads.py

import os
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status


MAX_ZIP_BYTES = 5 * 1024 * 1024 * 1024


async def spool_upload(upload: UploadFile,
                       limit: int = MAX_ZIP_BYTES) -> Path:
    """Пишет загрузку во временный файл и не держит архив целиком в памяти."""
    descriptor, raw_path = tempfile.mkstemp(prefix="hub_upload_", suffix=".zip")
    path = Path(raw_path)
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Размер ZIP-датасета не должен превышать 5 ГиБ",
                    )
                output.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
