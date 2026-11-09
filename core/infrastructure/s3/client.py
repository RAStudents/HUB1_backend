# core/infrastructure/s3/client.py

import os
import shutil
import logging
from pathlib import Path
from urllib.parse import quote


logger = logging.getLogger(__name__)


class S3Client:
    """
    Локальная заглушка S3-клиента: сохраняет файлы на диск вместо облачного хранилища.
    Для перехода на настоящий MinIO/S3 — раскомментировать boto3-реализацию ниже.
    """

    def __init__(self,
                 endpoint: str | None = None,
                 access_key: str | None = None,
                 secret_key: str | None = None,
                 bucket: str = "hub"):
        self.bucket = bucket
        self.storage_dir = Path("./local_s3_storage") / bucket
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def ensure_bucket(self) -> None:
        """Создаёт локальную директорию вместо S3-бакета (для разработки)."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(self,
                  key: str,
                  data: bytes,
                  content_type: str = "application/octet-stream") -> str:
        """Сохраняет байты в файл на диске (аналог S3 put_object)."""
        file_path = self.storage_dir / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return f"http://localhost:8000/storage/{self.bucket}/{key}"

    def get_bytes(self,
                  key: str) -> bytes | None:
        """Читает файл с диска. Возвращает None, если файл не найден."""
        file_path = self.storage_dir / key
        if not file_path.exists():
            return None
        return file_path.read_bytes()

    def delete(self,
               key: str) -> None:
        """Удаляет файл с диска."""
        file_path = self.storage_dir / key
        file_path.unlink(missing_ok=True)

    def delete_many(self,
                    keys: list[str]) -> None:
        """Пакетное удаление файлов."""
        for key in keys:
            if key:
                self.delete(key)

    def delete_prefix(self,
                      prefix: str) -> None:
        """Удаляет все файлы локального S3-хранилища под заданным префиксом."""
        relative_prefix = Path(prefix)
        if relative_prefix.is_absolute() or ".." in relative_prefix.parts:
            raise ValueError("Invalid storage prefix")

        root = self.storage_dir.resolve()
        target = (root / relative_prefix).resolve()
        if root not in target.parents:
            raise ValueError("Invalid storage prefix")

        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        base_url: str = "http://localhost:8000",
    ) -> str:
        """Возвращает локальный URL (аналог presigned URL в S3)."""
        return f"{base_url.rstrip('/')}/storage/{self.bucket}/{quote(key, safe='/')}"

    def get_presigned_upload_url(self,
                                 key: str,
                                 content_type: str = "application/octet-stream",
                                 expires_in: int = 900) -> str:
        """Возвращает локальный URL для загрузки файла (заглушка)."""
        return f"http://localhost:8000/storage/{self.bucket}/{key}"
