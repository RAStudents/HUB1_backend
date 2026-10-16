from io import BytesIO
from pathlib import Path
from PIL import Image
import pillow_heif

# Регистрируем поддержку HEIC/HEIF в Pillow
pillow_heif.register_heif_opener()

KEEP_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CONVERT_EXTENSIONS = {".heic", ".heif", ".webp", ".bmp", ".tiff", ".tif"}


def normalize_image_file(src_path: Path, jpeg_quality: int = 92) -> tuple[bytes, str, str]:
    """
    Принимает путь к исходному файлу изображения.
    - Если .jpg/.jpeg/.png — оставляет как есть.
    - Если .heic/.webp/.bmp/.tiff — конвертирует в .jpg с сохранением stem.
    Возвращает: (байты_файла, новое_имя_файла_с_расширением, content_type)
    """
    ext = src_path.suffix.lower()
    stem = src_path.stem

    if ext in KEEP_EXTENSIONS:
        content_type = "image/png" if ext == ".png" else "image/jpeg"
        return src_path.read_bytes(), f"{stem}{ext}", content_type

    if ext in CONVERT_EXTENSIONS:
        with Image.open(src_path) as img:
            rgb_img = img.convert("RGB")
            buf = BytesIO()
            rgb_img.save(buf, format="JPEG", quality=jpeg_quality)
            return buf.getvalue(), f"{stem}.jpg", "image/jpeg"

    raise ValueError(f"Неподдерживаемый формат изображения: {ext}")