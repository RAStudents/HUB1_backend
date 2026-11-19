# core/infrastructure/media/scratch.py

import os
import shutil
import zipfile
import logging
import tempfile

from pathlib import Path
from typing import Iterator
from contextlib import contextmanager


logger = logging.getLogger(__name__)

MAX_ZIP_FILES = 2_000_000
MAX_ZIP_BYTES = 5 * 1024 * 1024 * 1024
_SYMLINK_MODE = 0o120000



def _scratch_root() -> Path:
    if os.name == "nt":
        windows_temp = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"
        if windows_temp.is_dir() and str(windows_temp).isascii():
            return windows_temp
        raise OSError(
            "Не удалось найти временную папку с ASCII-путём. "
            "Экспорт датасета не может быть проверен OpenCV по Unicode-пути."
        )
    return Path(tempfile.gettempdir())


@contextmanager
def scratch_dir(prefix: str = "hub_") -> Iterator[Path]:
    """
    Создаёт временную директорию и гарантированно удаляет её при выходе из блока with.
    Используется для распаковки zip-архивов и сборки экспортов.
    """
    tmp_path = Path(tempfile.mkdtemp(prefix=prefix, dir=_scratch_root()))
    try:
        yield tmp_path
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


@contextmanager
def scratch_file(suffix: str = "",
                 data: bytes | None = None) -> Iterator[Path]:
    """
    Создаёт временный файл и удаляет его при выходе из блока with.
    Если передан data — записывает байты сразу после создания файла.

    Note: Файловый дескриптор закрывается немедленно (важно для Windows).
    """
    fd, raw_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)  # Сразу освобождаем дескриптор ОС (обязательно на Windows)
    path = Path(raw_path)
    try:
        if data is not None:
            path.write_bytes(data)
        yield path
    finally:
        path.unlink(missing_ok=True)


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return ((member.external_attr >> 16) & 0o170000) == _SYMLINK_MODE


def extract_zip_safely(zip_bytes_or_path: bytes | Path,
                       dest_dir: Path) -> Path:
    """Распаковывает ZIP внутри dest_dir. Без выхода из каталога, бомб и симлинков."""
    if isinstance(zip_bytes_or_path, bytes):
        zip_file_path = dest_dir / "_upload.zip"
        zip_file_path.write_bytes(zip_bytes_or_path)
    else:
        zip_file_path = zip_bytes_or_path

    extract_root = dest_dir / "extracted"
    extract_root.mkdir(parents=True, exist_ok=True)
    root = extract_root.resolve()
    total = 0
    count = 0

    with zipfile.ZipFile(zip_file_path, "r") as zf:
        for member in zf.infolist():
            if "__MACOSX" in member.filename or Path(member.filename).name.startswith("._"):
                continue
            count += 1
            if count > MAX_ZIP_FILES:
                raise ValueError("Слишком много файлов в архиве")
            if _is_symlink(member):
                raise ValueError(f"Симлинки в архиве запрещены: {member.filename}")
            total += member.file_size
            if total > MAX_ZIP_BYTES:
                raise ValueError("Архив слишком большой")
            target_path = (extract_root / member.filename).resolve()
            if not target_path.is_relative_to(root):
                raise ValueError(f"Небезопасный путь в архиве: {member.filename}")
            zf.extract(member, extract_root)

    if isinstance(zip_bytes_or_path, bytes):
        zip_file_path.unlink(missing_ok=True)

    subdirs = [p for p in extract_root.iterdir() if not p.name.startswith(".")]
    if len(subdirs) == 1 and subdirs[0].is_dir():
        return subdirs[0]
    return extract_root