# core/infrastructure/cv/labels.py

import logging
from enum import Enum
from pathlib import Path
from typing import List, Sequence

from acmenra_cv import Instance, TaskType
from acmenra_ds import LabelParser, LabelWriter, make_category_enum

logger = logging.getLogger(__name__)


def parse_label_file(path: Path,
                     class_names: Sequence[str],
                     task: TaskType,
                     is_strict: bool = False) -> List[Instance]:
    """
    Читает YOLO .txt файл напрямую через LabelParser из acmenra-ds.
    """
    if not path.exists() or path.stat().st_size == 0:
        return []

    category = make_category_enum(class_names)
    nc = max(len(class_names), 1)
    
    parser = LabelParser(nc=nc, task_type=task, category=category)
    
    try:
        return parser.parse(path=path, is_strict=is_strict) or []
    except Exception as e:
        print(f"[WARNING] Ошибка парсинга разметки в {path.name}: {e}")
        return []


def write_label_file(path: Path,
                     instances: List[Instance],
                     class_names: Sequence[str],
                     task: TaskType,
                     is_strict: bool = True) -> None:
    """
    Записывает список Instance в YOLO .txt файл через LabelWriter из acmenra-ds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if not instances:
        path.write_text("", encoding="utf-8")
        return

    category = make_category_enum(class_names)
    nc = max(len(class_names), 1)
    
    writer = LabelWriter(nc=nc, task_type=task, category=category)
    writer.write(path=path, instances=instances, is_strict=is_strict)