# core/infrastructure/s3/keys.py

import logging


logger = logging.getLogger(__name__)



def image_key(dataset_id: int,
              split: str,
              filename: str) -> str:
    """Ключ оригинала изображения в S3."""
    return f"datasets/{dataset_id}/{split}/images/{filename}"


def label_key(dataset_id: int,
              split: str,
              stem: str) -> str:
    """Ключ файла разметки .txt в S3."""
    return f"datasets/{dataset_id}/{split}/labels/{stem}.txt"


def thumb_key(dataset_id: int,
              split: str,
              stem: str) -> str:
    """Ключ превьюшки с отрисованными масками в S3."""
    return f"datasets/{dataset_id}/{split}/thumbs/{stem}.jpg"


def export_zip_key(dataset_id: int,
                   export_id: int) -> str:
    """Ключ готового архива экспорта датасета."""
    return f"datasets/{dataset_id}/exports/{export_id}.zip"
