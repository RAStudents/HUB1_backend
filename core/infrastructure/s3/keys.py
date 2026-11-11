# core/infrastructure/s3/keys.py

import logging
from pathlib import Path


logger = logging.getLogger(__name__)

_SPLITS = {"train", "val", "test"}


def clean_split(split: str) -> str:
    value = (split or "").strip().lower()
    if value == "valid":
        value = "val"
    if value not in _SPLITS:
        raise ValueError("Некорректный split")
    return value


def clean_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Некорректное имя файла")
    if "/" in filename or "\\" in filename:
        raise ValueError("Некорректное имя файла")
    name = Path(filename).name
    if name != filename or name in {".", ".."}:
        raise ValueError("Некорректное имя файла")
    return name


def clean_stem(stem: str) -> str:
    return clean_filename(stem)


def image_key(dataset_id: int, split: str, filename: str) -> str:
    return f"datasets/{int(dataset_id)}/{clean_split(split)}/images/{clean_filename(filename)}"


def label_key(dataset_id: int, split: str, stem: str) -> str:
    return f"datasets/{int(dataset_id)}/{clean_split(split)}/labels/{clean_stem(stem)}.txt"


def thumb_key(dataset_id: int, split: str, stem: str) -> str:
    return f"datasets/{int(dataset_id)}/{clean_split(split)}/thumbs/{clean_stem(stem)}.jpg"


def incoming_key(dataset_id: int, split: str, filename: str) -> str:
    return f"datasets/{int(dataset_id)}/_incoming/{clean_split(split)}/{clean_filename(filename)}"


def export_zip_key(dataset_id: int, export_id: int) -> str:
    return f"datasets/{int(dataset_id)}/exports/{int(export_id)}.zip"


def user_avatar_key(user_id: int) -> str:
    return f"avatars/{int(user_id)}.webp"
