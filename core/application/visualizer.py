import os
import shutil
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any

from acmenra_ds.data.dataset import Dataset

STORAGE_DIR = Path("storage")


def generate_mask_with_opencv(shape: tuple[int, int], instances: list) -> np.ndarray:
    """Генерация полупрозрачной RGBA маски с помощью чистого OpenCV"""
    h, w = shape[:2]
    # Создаем пустой холст RGBA (размеры: высота, ширина, 4 канала)
    bgra = np.zeros((h, w, 4), dtype=np.uint8)

    if not instances:
        return bgra

    # Базовая палитра цветов для разных классов (BGR)
    palette = [
        (0, 255, 0),    # Зеленый
        (255, 0, 0),    # Синий
        (0, 0, 255),    # Красный
        (255, 255, 0),  # Голубой
        (0, 255, 255),  # Желтый
        (255, 0, 255)   # Пурпурный
    ]

    for inst in instances:
        class_id = inst.get("class_id", 0)
        polygon = inst.get("polygon")
        
        if polygon is None or len(polygon) < 3:
            continue

        color_bgr = palette[class_id % len(palette)]
        
        # Преобразуем полигон в формат, который понимает OpenCV (int32)
        pts = np.array(polygon, dtype=np.int32)

        # 1. Рисуем полупрозрачную заливку полигона
        overlay = bgra.copy()
        cv2.fillPoly(overlay, [pts], color=(*color_bgr, 90)) # 90 — альфа-канал заливки
        cv2.addWeighted(overlay, 0.5, bgra, 0.5, 0, bgra)

        # 2. Рисуем яркий контур вокруг полигона для четкости
        cv2.polylines(bgra, [pts], isClosed=True, color=(*color_bgr, 255), thickness=2)

    return bgra


def parse_yolo_segmentation_txt(label_path: Path, img_shape: tuple[int, int]) -> list:
    """Безопасное чтение YOLO segment txt-файла"""
    instances = []
    if not label_path.exists():
        return instances

    h, w = img_shape[:2]
    try:
        with open(label_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 7:
                    continue
                class_id = int(parts[0])
                coords = [float(x) for x in parts[1:]]
                
                abs_points = []
                for i in range(0, len(coords), 2):
                    px = coords[i] * w
                    py = coords[i+1] * h
                    abs_points.append([px, py])
                
                instances.append({
                    "class_id": class_id,
                    "polygon": abs_points
                })
    except Exception as e:
        print(f"[WARNING] Ошибка чтения разметки {label_path.name}: {e}")
        
    return instances


def build_dataset_gallery(dataset_id: int, yaml_path: str | Path, split_name: str = "train", limit: int = 50) -> List[Dict[str, Any]]:
    print(f"\n[DEBUG] Загрузка датасета из: {yaml_path}")
    ds = Dataset.from_yaml(yaml_path, is_strict=False)
    
    target_split = ds.split(split_name)
    print(f"[DEBUG] Сплит '{split_name}': найдено элементов = {len(target_split) if target_split else 0}")

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

        img_array = ds.image_parser.parse(path=img_path, is_strict=ds.is_strict)
        if img_array is None:
            continue

        instances = parse_yolo_segmentation_txt(label_path, img_array.shape)

        if not dest_img_path.exists():
            shutil.copy2(img_path, dest_img_path)

        # Пересоздаем маску заново, чтобы старые пустые файлы перезаписались
        mask_bgra = generate_mask_with_opencv(shape=img_array.shape, instances=instances)
        cv2.imwrite(str(dest_mask_path), mask_bgra)

        gallery_items.append({
            "id": idx + 1,
            "filename": img_path.name,
            "image_url": f"http://127.0.0.1:8000/storage/dataset_{dataset_id}/{split_name}/images/{img_path.name}",
            "mask_url": f"http://127.0.0.1:8000/storage/dataset_{dataset_id}/{split_name}/masks/{stem}_mask.png",
            "objects_count": len(instances),
            "task": str(ds.task)
        })

    return gallery_items