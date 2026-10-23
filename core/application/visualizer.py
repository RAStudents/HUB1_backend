import shutil
import cv2
import numpy as np
import yaml
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import quote

from acmenra_cv import Drawer, TaskType
from acmenra_ds import Config, Dataset
from core.infrastructure.cv.labels import build_category_enum
from core.infrastructure.cv.thumbs import build_default_style, DEFAULT_PALETTE
from core.application.import_service import detect_layout

STORAGE_DIR = Path("storage")


def read_image_unicode(path: Path) -> np.ndarray | None:
    """Надежное чтение изображений с поддержкой Unicode/кириллицы на Windows."""
    try:
        if not path.exists():
            return None
        stream = np.fromfile(str(path), dtype=np.uint8)
        if stream.size == 0:
            return None
        return cv2.imdecode(stream, cv2.IMREAD_COLOR)
    except Exception:
        return None


def write_image_unicode(path: Path, img: np.ndarray) -> bool:
    """Надежное сохранение изображений (включая RGBA-маски) с поддержкой Unicode на Windows."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix if path.suffix else ".png"
        success, encoded = cv2.imencode(ext, img)
        if success:
            encoded.tofile(str(path))
            return True
        return False
    except Exception:
        return False


def resolve_yaml_path(path_input: str | Path) -> Path:
    """Находит YAML-конфиг датасета, даже если передан путь к папке или вложенному архиву."""
    p = Path(path_input)
    if p.is_file() and p.suffix in (".yaml", ".yml"):
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
    """Правильная инициализация Dataset из acmenra-ds со всеми Enum и путями."""
    yaml_path = resolve_yaml_path(yaml_path)
    raw_cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

    # Если в самом YAML указан корневой путь 'path', используем его (если он существует)
    root = yaml_path.parent
    cfg_path = raw_cfg.get("path")
    if cfg_path:
        candidate_root = Path(cfg_path)
        if not candidate_root.is_absolute():
            candidate_root = (yaml_path.parent / candidate_root).resolve()
        if candidate_root.exists():
            root = candidate_root

    yaml_names = raw_cfg.get("names", [])
    if isinstance(yaml_names, dict):
        names = [yaml_names[k] for k in sorted(yaml_names.keys())]
    else:
        names = [str(x) for x in yaml_names]

    category_enum = build_category_enum(names)

    task_str = raw_cfg.get("task")
    if task_str:
        try:
            task = TaskType(task_str)
        except ValueError:
            task = default_task
    else:
        task = default_task

    layout = detect_layout(root)
    val_leaf = "valid" if (root / "valid").exists() or (root / "images" / "valid").exists() else "val"

    config = Config(
        root=root,
        train="train",
        val=val_leaf if ((root / val_leaf).exists() or (root / "images" / val_leaf).exists()) else None,
        test="test" if ((root / "test").exists() or (root / "images" / "test").exists()) else None,
        names=names,
        task=task,
        layout=layout,
        train_leaf="train",
        val_leaf=val_leaf,
        test_leaf="test",
    )

    return Dataset(config=config, category=category_enum, is_cache=False, is_strict=False)


def render_rgba_mask_from_instances(shape: tuple[int, int], instances: list, task: TaskType) -> np.ndarray:
    """Рисует прозрачную RGBA-маску по объектам Instance из acmenra-cv."""
    h, w = shape[:2]
    bgra = np.zeros((h, w, 4), dtype=np.uint8)

    if not instances:
        return bgra

    for inst in instances:
        class_id = getattr(inst, "class_id", 0) or 0
        color_bgr = DEFAULT_PALETTE[class_id % len(DEFAULT_PALETTE)]

        # 1. Если это полигон (SEGMENT)
        if task == TaskType.SEGMENT and getattr(inst, "polygon", None) is not None:
            pts = np.array([[int(p.X * w), int(p.Y * h)] for p in inst.polygon.points], dtype=np.int32)
            if len(pts) >= 3:
                overlay = bgra.copy()
                cv2.fillPoly(overlay, [pts], color=(*color_bgr, 90))
                cv2.addWeighted(overlay, 0.5, bgra, 0.5, 0, bgra)
                cv2.polylines(bgra, [pts], isClosed=True, color=(*color_bgr, 255), thickness=2)

        # 2. Если это бокс (DETECT)
        elif task == TaskType.DETECT and getattr(inst, "box", None) is not None:
            x1, y1, x2, y2 = inst.box.to_xyxyn()
            pt1, pt2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
            overlay = bgra.copy()
            cv2.rectangle(overlay, pt1, pt2, color=(*color_bgr, 90), thickness=-1)
            cv2.addWeighted(overlay, 0.5, bgra, 0.5, 0, bgra)
            cv2.rectangle(bgra, pt1, pt2, color=(*color_bgr, 255), thickness=2)

    return bgra


def build_dataset_gallery(
    dataset_id: int,
    yaml_path: str | Path,
    split_name: str = "train",
    limit: int = 50,
    base_url: str = "http://127.0.0.1:8000",
) -> List[Dict[str, Any]]:
    resolved_yaml = resolve_yaml_path(yaml_path)

    ds = load_acmenra_dataset(resolved_yaml, default_task=TaskType.SEGMENT)
    
    actual_split = split_name
    target_split = ds.split(actual_split)
    if (target_split is None or len(target_split) == 0) and split_name == "val":
        target_split = ds.split("valid")
        if target_split is not None and len(target_split) > 0:
            actual_split = "valid"
    elif (target_split is None or len(target_split) == 0) and split_name == "valid":
        target_split = ds.split("val")
        if target_split is not None and len(target_split) > 0:
            actual_split = "val"

    if target_split is None or len(target_split) == 0:
        available = [s for s in ["train", "val", "test"] if ds.split(s) is not None and len(ds.split(s)) > 0]
        if not available:
            return []
        actual_split = available[0]
        target_split = ds.split(actual_split)

    base_dir = STORAGE_DIR / f"dataset_{dataset_id}" / actual_split
    img_out_dir = base_dir / "images"
    mask_out_dir = base_dir / "masks"
    img_out_dir.mkdir(parents=True, exist_ok=True)
    mask_out_dir.mkdir(parents=True, exist_ok=True)

    gallery_items = []
    base_url = base_url.rstrip("/")

    for idx, sample in enumerate(target_split):
        if idx >= limit:
            break

        img_path: Path = Path(sample.image_path)
        label_path: Path | None = Path(sample.label_path) if sample.label_path else None
        stem = img_path.stem

        dest_img_path = img_out_dir / img_path.name
        dest_mask_path = mask_out_dir / f"{stem}_mask.png"

        # Сначала пробуем наше надежное Unicode-чтение, затем фоллбэк на парсер
        img_array = read_image_unicode(img_path)
        if img_array is None:
            try:
                img_array = ds.image_parser.parse(path=img_path, is_strict=False)
            except Exception:
                img_array = None

        if img_array is None:
            continue

        # Парсим разметку штатным LabelParser из acmenra-ds
        instances = []
        if label_path and label_path.exists():
            try:
                instances = ds.label_parser.parse(path=label_path, is_strict=False) or []
            except Exception as e:
                print(f"[WARNING] Ошибка парсинга {label_path.name}: {e}")

        if not dest_img_path.exists():
            try:
                shutil.copy2(img_path, dest_img_path)
            except Exception:
                write_image_unicode(dest_img_path, img_array)

        mask_bgra = render_rgba_mask_from_instances(
            shape=img_array.shape,
            instances=instances,
            task=ds.task,
        )
        write_image_unicode(dest_mask_path, mask_bgra)

        safe_img_name = quote(img_path.name)
        safe_mask_name = quote(f"{stem}_mask.png")

        gallery_items.append({
            "id": idx + 1,
            "filename": img_path.name,
            "image_url": f"{base_url}/storage/dataset_{dataset_id}/{actual_split}/images/{safe_img_name}",
            "mask_url": f"{base_url}/storage/dataset_{dataset_id}/{actual_split}/masks/{safe_mask_name}",
            "objects_count": len(instances),
            "task": str(ds.task),
        })

    return gallery_items