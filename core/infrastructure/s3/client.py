# import os
# from typing import Iterable
# import boto3
# from botocore.config import Config as BotoConfig
# from botocore.exceptions import ClientError


# class S3Client:
#     def __init__(
#         self,
#         endpoint_url: str | None = None,
#         public_endpoint_url: str | None = None,
#         access_key: str | None = None,
#         secret_key: str | None = None,
#         bucket_name: str | None = None,
#         region_name: str = "us-east-1",
#     ):
#         self.endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
#         # Внешний URL нужен, чтобы presigned-ссылки открывались в браузере хоста
#         self.public_endpoint_url = public_endpoint_url or os.getenv(
#             "S3_PUBLIC_ENDPOINT_URL", self.endpoint_url
#         )
#         self.access_key = access_key or os.getenv("S3_ACCESS_KEY", "minioadmin")
#         self.secret_key = secret_key or os.getenv("S3_SECRET_KEY", "minioadmin")
#         self.bucket = bucket_name or os.getenv("S3_BUCKET", "hub")

#         boto_cfg = BotoConfig(
#             signature_version="s3v4",
#             s3={"addressing_style": "path"},
#         )

#         # Клиент для внутренних операций (put / get / delete внутри docker-сети)
#         self._client = boto3.client(
#             "s3",
#             endpoint_url=self.endpoint_url,
#             aws_access_key_id=self.access_key,
#             aws_secret_access_key=self.secret_key,
#             region_name=region_name,
#             config=boto_cfg,
#         )

#         # Отдельный клиент для подписи внешних URL (чтобы совпадал Host в подписи S3v4)
#         self._signer = boto3.client(
#             "s3",
#             endpoint_url=self.public_endpoint_url,
#             aws_access_key_id=self.access_key,
#             aws_secret_access_key=self.secret_key,
#             region_name=region_name,
#             config=boto_cfg,
#         )

#     def ensure_bucket(self) -> None:
#         """Создаёт бакет при старте приложения, если его ещё нет."""
#         try:
#             self._client.head_bucket(Bucket=self.bucket)
#         except ClientError:
#             self._client.create_bucket(Bucket=self.bucket)

#     def put_bytes(
#         self,
#         key: str,
#         data: bytes,
#         content_type: str = "application/octet-stream",
#     ) -> None:
#         """Загружает байты в бакет по ключу."""
#         self._client.put_object(
#             Bucket=self.bucket,
#             Key=key,
#             Body=data,
#             ContentType=content_type,
#         )

#     def get_bytes(self, key: str) -> bytes | None:
#         """Скачивает байты из бакета. Если объекта нет (404) — возвращает None."""
#         try:
#             resp = self._client.get_object(Bucket=self.bucket, Key=key)
#             return resp["Body"].read()
#         except ClientError as exc:
#             code = exc.response.get("Error", {}).get("Code", "")
#             if code in ("NoSuchKey", "404", "NotFound"):
#                 return None
#             raise

#     def delete(self, key: str) -> None:
#         """Удаляет один объект из S3."""
#         self._client.delete_object(Bucket=self.bucket, Key=key)

#     def delete_many(self, keys: Iterable[str]) -> None:
#         """Пакетное удаление объектов (например, при удалении сэмпла или датасета)."""
#         objects = [{"Key": k} for k in keys if k]
#         if not objects:
#             return
#         self._client.delete_objects(
#             Bucket=self.bucket,
#             Delete={"Objects": objects, "Quiet": True},
#         )

#     def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
#         """Генерирует ссылку на скачивание/просмотр (картинки, тумбы, zip-экспорта)."""
#         return self._signer.generate_presigned_url(
#             ClientMethod="get_object",
#             Params={"Bucket": self.bucket, "Key": key},
#             ExpiresIn=expires_in,
#         )

#     def get_presigned_upload_url(
#         self,
#         key: str,
#         content_type: str = "application/octet-stream",
#         expires_in: int = 900,
#     ) -> str:
#         """Генерирует presigned PUT ссылку для прямой загрузки файла с фронтенда."""
#         return self._signer.generate_presigned_url(
#             ClientMethod="put_object",
#             Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
#             ExpiresIn=expires_in,
#         )
import os
from pathlib import Path

class S3Client:
    def __init__(self, endpoint=None, access_key=None, secret_key=None, bucket="hub"):
        self.bucket = bucket
        self.storage_dir = Path("./local_s3_storage") / bucket
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def ensure_bucket(self):
        """Создает локальную директорию вместо бакета."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        """Сохраняет файлы локально на диск вместо S3."""
        file_path = self.storage_dir / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
        return f"http://localhost:8000/storage/{self.bucket}/{key}"

    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Возвращает локальный путь."""
        return f"http://localhost:8000/storage/{self.bucket}/{key}"