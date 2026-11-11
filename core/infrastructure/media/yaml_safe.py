# core/infrastructure/media/yaml_safe.py

import logging
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)

_MAX_YAML_BYTES = 1_000_000


def _has_alias(node) -> bool:
    if node is None:
        return False
    if isinstance(node, yaml.nodes.AliasNode):
        return True
    children = []
    if isinstance(node, yaml.nodes.SequenceNode):
        children = list(node.value)
    elif isinstance(node, yaml.nodes.MappingNode):
        children = [item for pair in node.value for item in pair]
    return any(_has_alias(child) for child in children)


def load_yaml_file(path: Path) -> dict:
    """Читает yaml без якорей-алиасов и без многомегабайтного файла."""
    raw = Path(path).read_bytes()
    if len(raw) > _MAX_YAML_BYTES:
        raise ValueError("Файл конфигурации слишком большой")
    text = raw.decode("utf-8-sig")
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        if _has_alias(node):
            raise ValueError("Псевдонимы YAML запрещены")
        document = loader.construct_document(node) if node is not None else {}
    finally:
        loader.dispose()
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError("Конфиг должен быть словарём")
    return document