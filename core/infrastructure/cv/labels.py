from enum import Enum
from pathlib import Path
from typing import List, Sequence

from acmenra_cv import Instance, TaskType
from acmenra_ds import LabelParser, LabelWriter


def build_category_enum(class_names: Sequence[str]) -> type[Enum]:
    """
    Создаёт динамический Enum для acmenra-ds / acmenra-cv.
    Если список классов пуст, создаёт технический класс, чтобы парсер не падал на пустых файлах.
    """
    if not class_names:
        return Enum("DatasetCategory", {"_EMPTY": 0})
    
    # Ключи Enum не могут дублироваться или быть пустыми, подстраховываемся индексом при коллизиях
    members = {}
    for idx, name in enumerate(class_names):
        safe_key = name.strip() or f"CLASS_{idx}"
        if safe_key in members:
            safe_key = f"{safe_key}_{idx}"
        members[safe_key] = idx
    return Enum("DatasetCategory", members)


def parse_label_file(
    path: Path,
    class_names: Sequence[str],
    task: TaskType,
    is_strict: bool = True,
) -> List[Instance]:
    """
    Читает YOLO .txt файл и возвращает список Instance.
    Пустой файл или отсутствие файла корректно возвращает [].
    """
    if not path.exists() or path.stat().st_size == 0:
        return []

    category = build_category_enum(class_names)
    nc = max(len(class_names), 1)
    parser = LabelParser(nc=nc, task_type=task, category=category)
    return parser.parse(path=path, is_strict=is_strict)


def write_label_file(
    path: Path,
    instances: List[Instance],
    class_names: Sequence[str],
    task: TaskType,
    is_strict: bool = True,
) -> None:
    """
    Записывает список Instance в YOLO .txt файл.
    Если instances пуст — создаёт пустой .txt файл (согласно DATA_CONTRACT.md).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not instances:
        path.write_text("", encoding="utf-8")
        return

    category = build_category_enum(class_names)
    nc = max(len(class_names), 1)
    writer = LabelWriter(nc=nc, task_type=task, category=category)
    writer.write(path=path, instances=instances, is_strict=is_strict)