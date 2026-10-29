# core/application/visualizer.py
import shutil
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

import cv2
import numpy as np
import yaml
from acmenra_cv import TaskType
from acmenra_ds import Config, Dataset

from core.application.import_service import detect_layout
from core.infrastructure.cv.labels import build_category_enum
from core.infrastructure.cv.thumbs import DEFAULT_PALETTE
from core.infrastructure.media.scratch import scratch_file

STORAGE_DIR = Path("storage")


def read_text_safe(path: Path) -> str:
    """Читает текстовый файл (yaml/txt), поддерживая UTF-8, UTF-8-SIG и Windows-1251."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_image_unicode(path: Path) -> np.ndarray | None:
    """Надёжное чтение изображения с поддержкой Unicode/кириллицы в пути (Windows)."""
    try:
        path_obj = Path(path)
        if not path_obj.is_file():
            return None
        raw_bytes = path_obj.read_bytes()
        if not raw_bytes:
            return None
        buf = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def write_image_unicode(path: Path, img: np.ndarray) -> bool:
    """Надёжное сохранение изображения с поддержкой Unicode в пути (Windows)."""
    try:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        ext = path_obj.suffix.lower() or ".png"
        success, encoded = cv2.imencode(ext, img)
        if success:
            path_obj.write_bytes(encoded.tobytes())
        return bool(success)
    except Exception:
        return False


def parse_label_unicode(ds: Dataset, label_path: Path) -> list:
    """
    Безопасно парсит .txt разметку через acmenra-ds, даже если путь
    содержит кириллицу или пробелы (через временный ASCII-файл).
    """
    if not label_path or not label_path.is_file():
        return []

    path_str = str(label_path)
    if path_str.isascii():
        return ds.label_parser.parse(path=label_path, is_strict=False) or []

    text_content = read_text_safe(label_path)
    with scratch_file(suffix=".txt", data=text_content.encode("utf-8")) as tmp_txt:
        return ds.label_parser.parse(path=tmp_txt, is_strict=False) or []


def resolve_yaml_path(path_input: str | Path) -> Path:
    """Находит yaml-конфиг датасета, даже если передан путь к папке."""
    p = Path(path_input)
    if p.is_file() and p.suffix.lower() in (".yaml", ".yml"):
        return p

    if p.is_dir():
        for name in ("data.yaml", "data.yml", "dataset.yaml", "dataset.yml"):
            candidate = p / name
            if candidate.exists():
                return candidate
        found = list(p.rglob("*.yaml")) + list(p.rglob("*.yml"))
        if found:
            return found[0]

    raise ValueError(f"Файл конфигурации датасета не найден по пути: {path_input}")


def load_acmenra_dataset(yaml_path: Path, default_task: TaskType = TaskType.SEGMENT) -> Dataset:
    """Инициализирует Dataset из acmenra-ds по yaml-конфигу."""
    yaml_path = resolve_yaml_path(yaml_path)
    raw_cfg = yaml.safe_load(read_text_safe(yaml_path)) or {}

    root = yaml_path.parent
    cfg_path = raw_cfg.get("path")
    if cfg_path:
        candidate_root = Path(cfg_path)
        if not candidate_root.is_absolute():
            candidate_root = (yaml_path.parent / candidate_root).resolve()
        if candidate_root.exists():
            root = candidate_root

    yaml_names = raw_cfg.get("names", [])
    names = (
        [str(yaml_names[k]) for k in sorted(yaml_names.keys())]
        if isinstance(yaml_names, dict)
        else [str(x) for x in yaml_names]
    )

    category_enum = build_category_enum(names)

    task_str = raw_cfg.get("task")
    try:
        task = TaskType(task_str) if task_str else default_task
    except ValueError:
        task = default_task

    layout = detect_layout(root)
    val_leaf = "valid" if (root / "valid").exists() or (root / "images" / "valid").exists() else "val"
    val_exists = (root / val_leaf).exists() or (root / "images" / val_leaf).exists()
    test_exists = (root / "test").exists() or (root / "images" / "test").exists()

    config = Config(
        root=root,
        train="train",
        val=val_leaf if val_exists else None,
        test="test" if test_exists else None,
        names=names,
        task=task,
        layout=layout,
        train_leaf="train",
        val_leaf=val_leaf,
        test_leaf="test",
    )
    return Dataset(config=config, category=category_enum, is_cache=False, is_strict=False)


def render_rgba_mask_from_instances(
    shape: tuple[int, int],
    instances: list,
    task: TaskType,
) -> np.ndarray:
    """Рисует прозрачную RGBA-маску поверх изображения по инстансам из acmenra-cv."""
    h, w = shape[:2]
    bgra = np.zeros((h, w, 4), dtype=np.uint8)

    if not instances:
        return bgra

    for inst in instances:
        class_id = getattr(inst, "class_id", 0) or 0
        color_bgr = DEFAULT_PALETTE[class_id % len(DEFAULT_PALETTE)]

        if task == TaskType.SEGMENT and getattr(inst, "polygon", None) is not None:
            pts = np.array(
                [[int(p.X * w), int(p.Y * h)] for p in inst.polygon.points],
                dtype=np.int32,
            )
            if len(pts) >= 3:
                overlay = bgra.copy()
                cv2.fillPoly(overlay, [pts], color=(*color_bgr, 90))
                cv2.addWeighted(overlay, 0.5, bgra, 0.5, 0, bgra)
                cv2.polylines(bgra, [pts], isClosed=True, color=(*color_bgr, 255), thickness=2)

        elif task == TaskType.DETECT and getattr(inst, "box", None) is not None:
            x1, y1, x2, y2 = inst.box.to_xyxyn()
            pt1 = (int(x1 * w), int(y1 * h))
            pt2 = (int(x2 * w), int(y2 * h))
            overlay = bgra.copy()
            cv2.rectangle(overlay, pt1, pt2, color=(*color_bgr, 90), thickness=-1)
            cv2.addWeighted(overlay, 0.5, bgra, 0.5, 0, bgra)
            cv2.rectangle(bgra, pt1, pt2, color=(*color_bgr, 255), thickness=2)

    return bgra


def _resolve_split(ds: Dataset, split_name: str) -> tuple[Any, str]:
    """
    Возвращает (split_object, actual_split_name).
    Пробует 'val'/'valid' как синонимы; если ничего нет — берёт первый доступный сплит.
    """
    split = ds.split(split_name)
    if split and len(split) > 0:
        return split, split_name

    # Синонимы val / valid
    if split_name in ("val", "valid"):
        alt = "valid" if split_name == "val" else "val"
        split = ds.split(alt)
        if split and len(split) > 0:
            return split, alt

    # Первый доступный сплит
    for candidate in ("train", "val", "test"):
        split = ds.split(candidate)
        if split and len(split) > 0:
            return split, candidate

    return None, split_name


def build_dataset_gallery(
    dataset_id: int,
    yaml_path: str | Path,
    split_name: str = "train",
    limit: int = 50,
    base_url: str = "http://127.0.0.1:8000",
) -> List[Dict[str, Any]]:
    """
    Строит галерею превью датасета с оверлеями масок.
    Изображения и маски кешируются в storage/ для раздачи через StaticFiles.
    """
    resolved_yaml = resolve_yaml_path(yaml_path)
    ds = load_acmenra_dataset(resolved_yaml, default_task=TaskType.SEGMENT)
    target_split, actual_split = _resolve_split(ds, split_name)

    if target_split is None:
        return []

    base_dir = STORAGE_DIR / f"dataset_{dataset_id}" / actual_split
    img_out_dir = base_dir / "images"
    mask_out_dir = base_dir / "masks"
    img_out_dir.mkdir(parents=True, exist_ok=True)
    mask_out_dir.mkdir(parents=True, exist_ok=True)

    base_url = base_url.rstrip("/")
    gallery_items = []

    for idx, sample in enumerate(target_split):
        if idx >= limit:
            break

        img_path = Path(sample.image_path)
        label_path = Path(sample.label_path) if sample.label_path else None
        stem = img_path.stem

        dest_img_path = img_out_dir / img_path.name
        dest_mask_path = mask_out_dir / f"{stem}_mask.png"

        img_array = read_image_unicode(img_path)
        if img_array is None:
            try:
                img_array = ds.image_parser.parse(path=img_path, is_strict=False)
            except Exception:
                img_array = None

        if img_array is None:
            continue

        instances = []
        if label_path and label_path.exists():
            try:
                instances = parse_label_unicode(ds, label_path)
            except Exception as exc:
                print(f"[WARNING] Ошибка парсинга {label_path.name}: {exc}")

        if not dest_img_path.exists():
            try:
                shutil.copy2(img_path, dest_img_path)
            except Exception:
                write_image_unicode(dest_img_path, img_array)

        mask_bgra = render_rgba_mask_from_instances(
            shape=img_array.shape, instances=instances, task=ds.task
        )
        write_image_unicode(dest_mask_path, mask_bgra)

        gallery_items.append({
            "id": idx + 1,
            "filename": img_path.name,
            "image_url": (
                f"{base_url}/storage/dataset_{dataset_id}"
                f"/{actual_split}/images/{quote(img_path.name)}"
            ),
            "mask_url": (
                f"{base_url}/storage/dataset_{dataset_id}"
                f"/{actual_split}/masks/{quote(f'{stem}_mask.png')}"
            ),
            "objects_count": len(instances),
            "task": str(ds.task),
        })

    return gallery_items