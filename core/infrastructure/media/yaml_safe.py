# core/infrastructure/media/yaml_safe.py

import yaml
import logging
from pathlib import Path


logger = logging.getLogger(__name__)

_MAX_YAML_BYTES = 1_000_000


def load_yaml_file(path: Path) -> dict:
    """Читает yaml без якорей-алиасов и без многомегабайтного файла."""
    raw = Path(path).read_bytes()
    if len(raw) > _MAX_YAML_BYTES:
        raise ValueError("Файл конфигурации слишком большой")
    text = raw.decode("utf-8-sig")
    try:
        events = list(yaml.parse(text))
    except yaml.YAMLError as exc:
        raise ValueError("Некорректный YAML") from exc
    for event in events:
        if isinstance(event, yaml.AliasEvent):
            raise ValueError("Псевдонимы YAML запрещены")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("Некорректный YAML") from exc
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError("Конфиг должен быть словарём")
    return document