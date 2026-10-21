import shutil
import cv2
import numpy as np
import yaml
from pathlib import Path
from typing import List, Dict, Any

from acmenra_cv import Drawer, TaskType
from acmenra_ds import Config, Dataset
from core.infrastructure.cv.labels import build_category_enum
from core.infrastructure.cv.thumbs import build_default_style, DEFAULT_PALETTE
from core.application.import_service import detect_layout

STORAGE_DIR = Path("storage")


def load_acmenra_dataset(yaml_path: Path, default_task: TaskType = TaskType.SEGMENT) -> Dataset:
    """Правильная инициализация Dataset из acmenra-ds со всеми Enum и путями."""
    root = yaml_path.parent
    raw_cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

    yaml_names = raw_cfg.get("names", [])
    if isinstance(yaml_names, dict):
        names = [yaml_names[k] for k in sorted(yaml_names.keys())]
    else:
        names = [str(x) for x in yaml_names]

    category_enum = build_category_enum(names)

    task_str = raw_cfg.get("task")
    task = TaskType(task_str) if task_str else default_task

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
) -> List[Dict[str, Any]]:
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise ValueError(f"Файл не найден: {yaml_path}")

    ds = load_acmenra_dataset(yaml_path, default_task=TaskType.SEGMENT)
    target_split = ds.split(split_name)

    if target_split is None or len(target_split) == 0:
        available = [s for s in ["train", "val", "test"] if ds.split(s) is not None and len(ds.split(s)) > 0]
        raise ValueError(f"Сплит '{split_name}' пуст или не найден. Доступные сплиты: {available}")

    base_dir = STORAGE_DIR / f"dataset_{dataset_id}" / split_name
    img_out_dir = base_dir / "images"
    mask_out_dir = base_dir / "masks"
    img_out_dir.mkdir(parents=True, exist_ok=True)
    mask_out_dir.mkdir(parents=True, exist_ok=True)

    gallery_items = []

    for idx, sample in enumerate(target_split):
        if idx >= limit:
            break

        img_path: Path = sample.image_path
        label_path: Path = sample.label_path
        stem = img_path.stem

        dest_img_path = img_out_dir / img_path.name
        dest_mask_path = mask_out_dir / f"{stem}_mask.png"

        img_array = ds.image_parser.parse(path=img_path, is_strict=False)
        if img_array is None:
            continue

        # Парсим разметку штатным LabelParser из acmenra-ds
        instances = []
        if label_path and label_path.exists():
            try:
                instances = ds.label_parser.parse(path=label_path, is_strict=False)
            except Exception as e:
                print(f"[WARNING] Ошибка парсинга {label_path.name}: {e}")

        if not dest_img_path.exists():
            shutil.copy2(img_path, dest_img_path)

        mask_bgra = render_rgba_mask_from_instances(
            shape=img_array.shape,
            instances=instances,
            task=ds.task,
        )
        cv2.imwrite(str(dest_mask_path), mask_bgra)

        gallery_items.append({
            "id": idx + 1,
            "filename": img_path.name,
            "image_url": f"http://127.0.0.1:8000/storage/dataset_{dataset_id}/{split_name}/images/{img_path.name}",
            "mask_url": f"http://127.0.0.1:8000/storage/dataset_{dataset_id}/{split_name}/masks/{stem}_mask.png",
            "objects_count": len(instances),
            "task": str(ds.task),
        })

    return gallery_items