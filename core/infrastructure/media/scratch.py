# core/infrastructure/media/scratch.py

import os
import shutil
import tempfile
import zipfile
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


logger = logging.getLogger(__name__)


@contextmanager
def scratch_dir(prefix: str = "hub_") -> Iterator[Path]:
    """
    Создаёт временную директорию и гарантированно удаляет её при выходе из блока with.
    Используется для распаковки zip-архивов и сборки экспортов.
    """
    tmp_path = Path(tempfile.mkdtemp(prefix=prefix))
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


def extract_zip_safely(zip_bytes_or_path: bytes | Path,
                       dest_dir: Path) -> Path:
    """
    Распаковывает ZIP-архив в dest_dir с защитой от Zip Slip-атаки.

    Если архив содержит одну корневую папку (типичный случай при архивации датасета),
    возвращает путь прямо к ней; иначе — путь к директории с распакованным содержимым.
    """
    if isinstance(zip_bytes_or_path, bytes):
        zip_file_path = dest_dir / "_upload.zip"
        zip_file_path.write_bytes(zip_bytes_or_path)
    else:
        zip_file_path = zip_bytes_or_path

    extract_root = dest_dir / "extracted"
    extract_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_file_path, "r") as zf:
        for member in zf.infolist():
            # Пропускаем системный мусор macOS
            if "__MACOSX" in member.filename or Path(member.filename).name.startswith("._"):
                continue

            # Защита от Zip Slip: целевой путь должен оставаться внутри extract_root
            target_path = (extract_root / member.filename).resolve()
            if not str(target_path).startswith(str(extract_root.resolve())):
                raise ValueError(f"Небезопасный путь в архиве: {member.filename}")

            zf.extract(member, extract_root)

    if isinstance(zip_bytes_or_path, bytes):
        zip_file_path.unlink(missing_ok=True)

    # Если всё упаковано в одну вложенную папку — спускаемся в неё
    subdirs = [p for p in extract_root.iterdir() if not p.name.startswith(".")]
    if len(subdirs) == 1 and subdirs[0].is_dir():
        return subdirs[0]

    return extract_root
