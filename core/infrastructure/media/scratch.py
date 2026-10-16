import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def scratch_dir(prefix: str = "hub_") -> Iterator[Path]:
    """
    Создаёт временную директорию (например, для распаковки zip или сборки экспорта)
    и гарантированно удаляет её вместе со всем содержимым после выхода из with.
    """
    tmp_path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield tmp_path
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


@contextmanager
def scratch_file(suffix: str = "", data: bytes | None = None) -> Iterator[Path]:
    """
    Создаёт временный файл (например, чтобы скормить байты из S3 в LabelParser или ImageParser)
    и удаляет его сразу после завершения работы.
    """
    import os

    fd, raw_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)  # Важно для Windows: сразу освобождаем дескриптор ОС!
    path = Path(raw_path)
    try:
        if data is not None:
            path.write_bytes(data)
        yield path
    finally:
        path.unlink(missing_ok=True)


def extract_zip_safely(zip_bytes_or_path: bytes | Path, dest_dir: Path) -> Path:
    """
    Распаковывает архив во временную папку. Защищает от Zip Slip (выхода за пределы папки).
    Если внутри архива лежит одна корневая папка (частый случай при архивации датасета),
    возвращает путь прямо к ней.
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
            # Игнорируем системный мусор macOS
            if "__MACOSX" in member.filename or Path(member.filename).name.startswith("._"):
                continue
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