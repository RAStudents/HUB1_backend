# core/application/import_service.py

import yaml
import shutil
import logging
from pathlib import Path
from typing import Any, List
from acmenra_cv import TaskType

from acmenra_ds import Config, Dataset, DatasetLayout, DataSplit, make_category_enum

from core.infrastructure.cv.labels import parse_label_file
from core.infrastructure.cv.mapper import instances_to_dtos
from core.infrastructure.cv.thumbs import render_thumbnail_bytes

from core.infrastructure.media.convert import CONVERT_EXTENSIONS, normalize_image_file
from core.infrastructure.media.scratch import extract_zip_safely, scratch_dir
from core.infrastructure.s3.keys import image_key, label_key, thumb_key


logger = logging.getLogger(__name__)


STORAGE_DIR = Path("storage")
_YAML_NAMES = ("data.yaml", "dataset.yaml", "config.yaml", "data.yml", "dataset.yml")


def resolve_dataset_root(root: Path) -> Path:
    """Находит корень датасета по наличию конфига или структуры сплитов."""
    for yaml_name in _YAML_NAMES:
        found = list(root.rglob(yaml_name))
        if found:
            return found[0].parent

    for split_dir in ("train", "valid", "val", "images"):
        found_splits = [p for p in root.rglob(split_dir) if p.is_dir()]
        if found_splits:
            parent = found_splits[0].parent
            if parent.name in ("images", "labels"):
                return parent.parent
            return parent

    return root


def detect_layout(root: Path) -> DatasetLayout:
    """Определяет раскладку датасета (DIRECT или REVERSE) с помощью acmenra-ds."""
    root = resolve_dataset_root(root)
    if (root / "images" / "train").is_dir() or (root / "images").is_dir():
        return DatasetLayout.REVERSE
    return DatasetLayout.DIRECT


def find_yaml_file(root: Path) -> Path | None:
    root = resolve_dataset_root(root)
    for name in _YAML_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    yaml_files = list(root.glob("*.yaml")) + list(root.glob("*.yml"))
    return yaml_files[0] if yaml_files else None


def normalize_dataset_images(root: Path) -> None:
    for source_path in root.rglob("*"):
        if not source_path.is_file() or source_path.suffix.lower() not in CONVERT_EXTENSIONS:
            continue

        image_bytes, normalized_name, _ = normalize_image_file(source_path)
        normalized_path = source_path.with_name(normalized_name)
        if normalized_path.exists():
            raise ValueError(
                f"Невозможно нормализовать {source_path.name}: "
                f"файл {normalized_path.name} уже существует"
            )

        normalized_path.write_bytes(image_bytes)
        source_path.unlink()


def build_acmenra_dataset(root: Path,
                          task: TaskType,
                          fallback_names: List[str] | None = None) -> Dataset:
    root = resolve_dataset_root(root)
    yaml_path = find_yaml_file(root)

    names = fallback_names or []
    raw_cfg = {}

    if yaml_path is not None:
        try:
            raw_cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            raw_names = raw_cfg.get("names") or raw_cfg.get("classes") or []
            
            if isinstance(raw_names, dict):
                names = [str(raw_names[k]) for k in sorted(raw_names.keys())]
            elif isinstance(raw_names, list):
                names = [str(x) for x in raw_names]
            elif isinstance(raw_names, str):
                names = [x.strip() for x in raw_names.split(",")]
        except Exception:
            pass

    if not names:
        names = ["object"]

    category_enum = make_category_enum(names)
    layout = detect_layout(root)
    val_leaf = (
        "valid"
        if (root / "valid").is_dir() or (root / "images" / "valid").is_dir()
        else "val"
    )
    has_val = (root / val_leaf).is_dir() or (root / "images" / val_leaf).is_dir()
    has_test = (root / "test").is_dir() or (root / "images" / "test").is_dir()

    task_str = raw_cfg.get("task")
    try:
        resolved_task = TaskType(task_str) if task_str else task
    except ValueError:
        resolved_task = task

    # Передаем конфигурацию напрямую в acmenra-ds, без ручных симлинков
    config = Config(
        root=root,
        train="train",
        val=val_leaf if has_val else None,
        test="test" if has_test else None,
        names=names,
        task=resolved_task,
        layout=layout,
        val_leaf=val_leaf,
    )

    return Dataset(config=config,
                   category=category_enum,
                   is_cache=False,
                   is_strict=False)


class ImportService:
    def __init__(
        self,
        s3_client: Any,
        sample_repo: Any,
        class_repo: Any,
        annotation_repo: Any | None = None,
    ):
        self.s3 = s3_client
        self.samples = sample_repo
        self.classes = class_repo
        self.annotations = annotation_repo

    def import_zip(self,
                   dataset_id: int,
                   task: TaskType,
                   zip_source: bytes | Path,
                   existing_classes: List[str] | None = None) -> dict:
        imported_count = 0
        errors_count = 0

        with scratch_dir(prefix=f"import_ds_{dataset_id}_") as tmp_dir:
            raw_root = extract_zip_safely(zip_source, tmp_dir)
            root = resolve_dataset_root(raw_root)
            normalize_dataset_images(root)

            persistent_raw_dir = STORAGE_DIR / f"dataset_{dataset_id}" / "raw"
            if persistent_raw_dir.exists():
                shutil.rmtree(persistent_raw_dir, ignore_errors=True)
            persistent_raw_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, persistent_raw_dir, dirs_exist_ok=True)

            ds = build_acmenra_dataset(root=persistent_raw_dir, task=task, fallback_names=existing_classes)
            class_names = ds.names or existing_classes or []

            if class_names and self.classes is not None:
                self.classes.ensure_classes(dataset_id=dataset_id, names=class_names)

            for split_enum in (DataSplit.TRAIN, DataSplit.VAL, DataSplit.TEST):
                try:
                    split_obj = ds.split(split_enum)
                except Exception:
                    continue

                if split_obj is None:
                    continue

                split_name = split_enum.value.lower()

                for idx, sample in enumerate(split_obj.samples):
                    parse_error: str | None = None
                    instances = []

                    if getattr(sample, "label_path", None) is not None and sample.label_path.exists():
                        try:
                            instances = parse_label_file(
                                path=sample.label_path,
                                class_names=class_names,
                                task=task,
                                is_strict=True,
                            )
                        except Exception as exc:
                            parse_error = str(exc)
                            errors_count += 1

                    img_bytes, img_filename, content_type = normalize_image_file(sample.image_path)

                    ext = Path(img_filename).suffix or ".jpg"
                    norm_img_path = tmp_dir / f"_tmp_thumb_{idx}{ext}"
                    norm_img_path.write_bytes(img_bytes)
                    thumb_bytes = render_thumbnail_bytes(
                        image_path=norm_img_path,
                        instances=instances,
                        task=task,
                    )
                    norm_img_path.unlink(missing_ok=True)

                    s3_img_key = image_key(dataset_id, split_name, img_filename)
                    s3_lbl_key = label_key(dataset_id, split_name, sample.stem)
                    s3_thb_key = thumb_key(dataset_id, split_name, sample.stem)

                    self.s3.put_bytes(s3_img_key, img_bytes, content_type=content_type)
                    self.s3.put_bytes(s3_thb_key, thumb_bytes, content_type="image/jpeg")

                    raw_txt = (
                        sample.label_path.read_bytes()
                        if (getattr(sample, "label_path", None) and sample.label_path.exists())
                        else b""
                    )
                    self.s3.put_bytes(s3_lbl_key, raw_txt, content_type="text/plain")

                    if self.samples is not None:
                        created_sample = self.samples.create_sample(
                            dataset_id=dataset_id,
                            stem=sample.stem,
                            split=split_name,
                            image_key=s3_img_key,
                            label_key=s3_lbl_key,
                            thumb_key=s3_thb_key,
                            is_labeled=bool(instances),
                            parse_error=parse_error,
                            status=(
                                "accepted"
                                if instances and parse_error is None
                                else "unlabeled"
                            ),
                        )
                        if self.annotations is not None:
                            self.annotations.replace_sample_annotations(
                                sample_id=created_sample.id,
                                class_ids=[instance.class_id for instance in instances],
                                user_id=None,
                                commit=False,
                            )
                        self.samples.set_geometries(
                            sample_id=created_sample.id,
                            geometries=[
                                item.model_dump(mode="json")
                                for item in instances_to_dtos(instances, task)
                            ],
                            commit=False,
                        )
                        self.samples.commit()

                    imported_count += 1

        return {
            "dataset_id": dataset_id,
            "imported_samples": imported_count,
            "parse_errors": errors_count,
            "classes": class_names,
            "local_gallery_ready": True,
        }