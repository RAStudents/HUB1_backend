# core/application/visualizer.py
import shutil
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote
import cv2
import numpy as np
import yaml
from acmenra_cv import TaskType
from acmenra_ds import Config, Dataset, DatasetLayout

from core.infrastructure.cv.labels import build_category_enum
from core.infrastructure.cv.thumbs import render_thumbnail_array

STORAGE_DIR = Path("storage")
_YAML_NAMES = ("data.yaml", "dataset.yaml", "config.yaml", "data.yml", "dataset.yml")


def read_text_safe(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_image_unicode(path: Path) -> np.ndarray | None:
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


def resolve_dataset_root(root: Path) -> Path:
    for y_name in _YAML_NAMES:
        found = list(root.rglob(y_name))
        if found:
            return found[0].parent

    for split_dir in ("train", "valid", "val", "images"):
        found_splits = [p for p in root.rglob(split_dir) if p.is_dir()]
        if found_splits:
            parent = found_splits[0].parent
            return parent.parent if parent.name in ("images", "labels") else parent

    return root


def resolve_yaml_path(path_input: str | Path) -> Path:
    p = Path(path_input)
    if p.is_file() and p.suffix.lower() in (".yaml", ".yml"):
        return p

    if p.is_dir():
        for name in _YAML_NAMES:
            candidate = p / name
            if candidate.exists():
                return candidate
        found = list(p.rglob("*.yaml")) + list(p.rglob("*.yml"))
        if found:
            return found[0]

    raise ValueError(f"Файл конфигурации датасета не найден по пути: {path_input}")


def parse_label_unicode(ds: Dataset, label_path: Path) -> list:
    """Строгий нативный парсинг разметки без хаков и автоматических подгонок."""
    if not label_path or not label_path.is_file():
        return []

    try:
        return ds.label_parser.parse(path=label_path, is_strict=False) or []
    except Exception as e:
        print(f"[WARNING] Ошибка парсинга {label_path.name}: {e}")

    return []


def load_acmenra_dataset(
    yaml_or_dir_path: Path,
    fallback_task: TaskType | None = None,
) -> Dataset:
    path_obj = Path(yaml_or_dir_path)
    if path_obj.is_dir():
        yaml_path = resolve_yaml_path(path_obj)
    else:
        yaml_path = path_obj

    root = resolve_dataset_root(yaml_path.parent)

    raw_cfg = yaml.safe_load(read_text_safe(yaml_path)) or {}
    raw_names = raw_cfg.get("names") or raw_cfg.get("classes") or []
    names = []
    
    if isinstance(raw_names, dict):
        names = [str(raw_names[k]) for k in sorted(raw_names.keys())]
    elif isinstance(raw_names, list):
        names = [str(x) for x in raw_names]
    elif isinstance(raw_names, str):
        names = [x.strip() for x in raw_names.split(",")]

    if not names:
        names = ["object"]

    category_enum = build_category_enum(names)
    
    # Строгое чтение task из конфига, без дефолтов и попыток угадывания
    task_str = raw_cfg.get("task")
    if not task_str and fallback_task is None:
        raise ValueError(f"В конфигурационном файле '{yaml_path.name}' обязательно должен быть явно указан параметр 'task'.")
    
    try:
        task = TaskType(task_str) if task_str else fallback_task
    except ValueError:
        raise ValueError(f"Неизвестный тип задачи '{task_str}' в файле '{yaml_path.name}'.")

    layout = DatasetLayout.REVERSE if (root / "images" / "train").exists() or (root / "images").exists() else DatasetLayout.DIRECT
    
    train_path = raw_cfg.get("train", "train")
    if isinstance(train_path, str):
        train_path = train_path.strip().lstrip("./")
        if train_path.startswith("images/"):
            train_path = train_path.replace("images/", "", 1)

    val_candidate = "valid" if (root / "valid").exists() else "val"
    has_val = (root / val_candidate).exists() or (root / "images" / val_candidate).exists()
    has_test = (root / "test").exists() or (root / "images" / "test").exists()

    config = Config(
        root=root,
        train=train_path if (root / train_path).exists() or (root / "images" / train_path).exists() else "train",
        val=val_candidate if has_val else None,
        test="test" if has_test else None,
        names=names,
        task=task,
        layout=layout,
        val_leaf=val_candidate,
    )

    return Dataset(config=config, category=category_enum, is_cache=False, is_strict=False)


def _find_samples_fallback(root: Path, split_name: str) -> list[tuple[Path, Path | None]]:
    img_candidates = [
        root / split_name / "images",
        root / "images" / split_name,
        root / split_name,
    ]
    images_dir = None
    for cand in img_candidates:
        if cand.is_dir():
            images_dir = cand
            break

    if not images_dir:
        return []

    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    img_files = [p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    img_files.sort()

    lbl_candidates = [
        root / split_name / "labels",
        root / "labels" / split_name,
    ]
    labels_dir = None
    for cand in lbl_candidates:
        if cand.is_dir():
            labels_dir = cand
            break

    result = []
    for img_p in img_files:
        lbl_p = None
        if labels_dir:
            cand_lbl = labels_dir / f"{img_p.stem}.txt"
            if cand_lbl.exists():
                lbl_p = cand_lbl
        result.append((img_p, lbl_p))

    return result


def find_dataset_gallery_image(
    root: Path,
    split_name: str,
    filename: str,
) -> tuple[Path, Path | None] | None:
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise ValueError("Некорректное имя файла")

    split_names = (split_name,)
    if split_name == "valid":
        split_names = ("valid", "val")
    elif split_name == "val":
        split_names = ("val", "valid")

    for candidate_split in split_names:
        for image_path, label_path in _find_samples_fallback(root, candidate_split):
            if image_path.name == filename:
                return image_path, label_path

    return None


def build_dataset_gallery(
    dataset_id: int,
    yaml_path: str | Path,
    split_name: str = "train",
    limit: int = 50,
    offset: int = 0,
    base_url: str = "http://127.0.0.1:8000",
    class_ids: set[int] | None = None,
    fallback_task: TaskType | None = None,
) -> List[Dict[str, Any]]:
    resolved_yaml = resolve_yaml_path(yaml_path)
    root = resolve_dataset_root(resolved_yaml.parent)

    ds = load_acmenra_dataset(resolved_yaml, fallback_task=fallback_task)
    class_names = ds.names or []

    samples_to_process = []
    try:
        split_obj = ds.split(split_name)
        if split_obj and len(split_obj) > 0:
            for s in split_obj.samples:
                l_path = Path(s.label_path) if getattr(s, "label_path", None) else None
                samples_to_process.append((Path(s.image_path), l_path))
    except Exception:
        pass

    if not samples_to_process:
        samples_to_process = _find_samples_fallback(root, split_name)

    if not samples_to_process:
        return []

    base_dir = STORAGE_DIR / f"dataset_{dataset_id}" / split_name
    img_out_dir = base_dir / "images"
    mask_out_dir = base_dir / "masks"
    img_out_dir.mkdir(parents=True, exist_ok=True)
    mask_out_dir.mkdir(parents=True, exist_ok=True)

    base_url = base_url.rstrip("/")
    gallery_items = []

    for idx, (img_path, label_path) in enumerate(samples_to_process):
        if idx < offset:
            continue
        if idx >= offset + limit:
            break

        stem = img_path.stem
        dest_img_path = img_out_dir / img_path.name

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
            instances = parse_label_unicode(ds, label_path)

        annotation_counts: dict[int, int] = {}
        for instance in instances:
            annotation_counts[instance.class_id] = (
                annotation_counts.get(instance.class_id, 0) + 1
            )
        visible_instances = (
            instances
            if class_ids is None
            else [instance for instance in instances if instance.class_id in class_ids]
        )
        class_suffix = (
            "_classes_" + "_".join(str(class_id) for class_id in sorted(class_ids))
            if class_ids is not None
            else ""
        )
        dest_mask_path = mask_out_dir / f"{stem}_mask{class_suffix}.png"

        try:
            shutil.copy2(img_path, dest_img_path)
        except Exception:
            write_image_unicode(dest_img_path, img_array)

        masked_array = render_thumbnail_array(
            frame=img_array,
            instances=visible_instances,
            task=ds.task,
        )
        write_image_unicode(dest_mask_path, masked_array)

        cache_bust = int(dest_mask_path.stat().st_mtime) if dest_mask_path.exists() else 1

        gallery_items.append({
            "id": idx + 1,
            "filename": img_path.name,
            "image_url": (
                f"{base_url}/storage/dataset_{dataset_id}"
                f"/{split_name}/images/{quote(img_path.name)}?v={cache_bust}"
            ),
            "mask_url": (
                f"{base_url}/storage/dataset_{dataset_id}"
                f"/{split_name}/masks/{quote(dest_mask_path.name)}?v={cache_bust}"
            ),
            "objects_count": len(instances),
            "visible_objects_count": len(visible_instances),
            "annotation_classes": [
                {
                    "id": class_id,
                    "name": (
                        class_names[class_id]
                        if 0 <= class_id < len(class_names)
                        else f"Класс {class_id}"
                    ),
                    "count": count,
                }
                for class_id, count in sorted(annotation_counts.items())
            ],
            "task": str(ds.task),
        })

    return gallery_items