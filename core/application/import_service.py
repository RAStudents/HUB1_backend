# core/application/import_service.py

import logging
from pathlib import Path
from typing import Any, Callable, List
from acmenra_cv import TaskType

from acmenra_ds import Config, DatasetLayout, DataSplit
from acmenra_ds.data.sample import Sample

from core.infrastructure.cv.labels import parse_label_file
from core.infrastructure.cv.mapper import instances_to_dtos
from core.infrastructure.cv.thumbs import read_image_unicode, render_thumbnail_bytes

from core.infrastructure.media.convert import CONVERT_EXTENSIONS, normalize_image_file
from core.infrastructure.media.yaml_safe import load_yaml_file
from core.infrastructure.media.scratch import extract_zip_safely, scratch_dir
from core.infrastructure.s3.keys import image_key, label_key, thumb_key

logger = logging.getLogger(__name__)

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
                          fallback_names: List[str] | None = None) -> Config:
    root = resolve_dataset_root(root)
    yaml_path = find_yaml_file(root)

    names = fallback_names or []
    raw_cfg = {}

    if yaml_path is not None:
        try:
            raw_cfg = load_yaml_file(yaml_path)
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

    return config


def load_split_samples(config: Config, split: DataSplit) -> list[Sample]:
    if split == DataSplit.TRAIN:
        image_dir = config.get_train_images()
        label_dir = config.get_train_labels()
    elif split == DataSplit.VAL:
        image_dir = config.get_val_images()
        label_dir = config.get_val_labels()
    else:
        image_dir = config.get_test_images()
        label_dir = config.get_test_labels()

    if image_dir is None or not image_dir.is_dir():
        return []

    samples = []
    for image_path in sorted(image_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in {
            ".jpg", ".jpeg", ".png",
        }:
            continue

        frame = read_image_unicode(image_path)
        if frame is None or min(frame.shape[:2]) <= 1:
            continue

        label_path = label_dir / f"{image_path.stem}.txt" if label_dir else None
        samples.append(Sample(
            stem=image_path.stem,
            image_path=image_path,
            label_path=label_path if label_path and label_path.is_file() else None,
        ))

    return samples


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
                   existing_classes: List[str] | None = None,
                   progress_callback: Callable[..., None] | None = None) -> dict:
        imported_count = 0
        errors_count = 0
        processed_count = 0
        total_samples = 0

        def report(stage: str, progress: int) -> None:
            if progress_callback is not None:
                progress_callback(
                    stage=stage,
                    progress=progress,
                    total_samples=total_samples,
                    processed_samples=processed_count,
                    imported_samples=imported_count,
                    parse_errors=errors_count,
                )

        with scratch_dir(prefix=f"import_ds_{dataset_id}_") as tmp_dir:
            report("extracting", 2)
            raw_root = extract_zip_safely(zip_source, tmp_dir)
            root = resolve_dataset_root(raw_root)
            report("normalizing", 8)
            normalize_dataset_images(root)

            report("discovering", 18)

            config = build_acmenra_dataset(
                root=root,
                task=task,
                fallback_names=existing_classes,
            )
            class_names = config.names or existing_classes or []

            if class_names and self.classes is not None:
                self.classes.ensure_classes(dataset_id=dataset_id, names=class_names)

            split_samples = [
                (split_enum, split_enum.value.lower(), load_split_samples(config, split_enum))
                for split_enum in (DataSplit.TRAIN, DataSplit.VAL, DataSplit.TEST)
            ]
            total_samples = sum(len(samples) for _, _, samples in split_samples)
            report("importing", 20)
            progress_interval = max(1, (total_samples + 99) // 100)

            for _, split_name, samples in split_samples:
                for idx, sample in enumerate(samples):
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
                            parse_error = str(exc).splitlines()[0][:200]
                            if "/" in parse_error or "\\" in parse_error:
                                parse_error = "Ошибка разбора разметки"
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
                    processed_count += 1
                    if (
                            processed_count % progress_interval == 0
                            or processed_count == total_samples
                    ):
                        report(
                            "importing",
                            20 + int(processed_count * 75 / max(1, total_samples)),
                        )

            report("finalizing", 98)
        return {
            "dataset_id": dataset_id,
            "imported_samples": imported_count,
            "total_samples": total_samples,
            "parse_errors": errors_count,
            "classes": class_names,
            "local_gallery_ready": False,
        }