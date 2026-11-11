# core/infrastructure/media/convert.py

import logging
import pillow_heif
from PIL import Image
from io import BytesIO
from pathlib import Path


logger = logging.getLogger(__name__)

pillow_heif.register_heif_opener()
Image.MAX_IMAGE_PIXELS = 40_000_000

KEEP_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CONVERT_EXTENSIONS = {".heic", ".heif", ".webp", ".bmp", ".tiff", ".tif"}
_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def normalize_image_file(src_path: Path,
                         jpeg_quality: int = 92) -> tuple[bytes, str, str]:
    """
    Нормализует изображение к поддерживаемому формату.

    - .jpg / .jpeg / .png — возвращает как есть.
    - .heic / .webp / .bmp / .tiff — конвертирует в .jpg с сохранением stem.

    Returns:
        (байты_файла, имя_файла_с_расширением, content_type)
    """
    ext = src_path.suffix.lower()
    stem = src_path.stem

    try:
        file_bytes = src_path.read_bytes()
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать файл {src_path.name}") from exc
    if len(file_bytes) > _MAX_IMAGE_BYTES:
        raise ValueError(f"Изображение слишком большое: {src_path.name}")

    if ext in KEEP_EXTENSIONS:
        content_type = "image/png" if ext == ".png" else "image/jpeg"
        return file_bytes, f"{stem}{ext}", content_type

    if ext in CONVERT_EXTENSIONS:
        try:
            with Image.open(BytesIO(file_bytes)) as img:
                buf = BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=jpeg_quality)
                return buf.getvalue(), f"{stem}.jpg", "image/jpeg"
        except Exception as exc:
            raise ValueError(f"Ошибка конвертации изображения {src_path.name}") from exc

    raise ValueError(f"Неподдерживаемый формат изображения: {ext}")