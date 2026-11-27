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
_TASK_LABELS = {TaskType.DETECT: "Detect", TaskType.OBB: "OBB", TaskType.SEGMENT: "Polygon"}


class ImportConfirmationRequired(ValueError):
    def __init__(self, message: str, total_samples: int, parse_errors: int):
        super().__init__(message)
        self.total_samples = total_samples
        self.parse_errors = parse_errors


def read_import_label(path: Path, class_names: list[str], task: TaskType):
    try:
        return parse_label_file(path, class_names, task, is_strict=True), None
    except Exception as exc:
        message = next(iter(str(exc).splitlines()), "Ошибка разбора разметки")[:200]
        if "/" in message or "\\" in message:
            message = "Ошибка разбора разметки"
        return [], message


def resolve_dataset_root(root: Path) -> Path:
    """Находит корень датасета по наличию конфига или структуры сплитов."""
    for yaml_name in _YAML_NAMES:
        found = list(root.rglob(yaml_name))
        if found:
            return found[0].parent

    if root.name in {"train", "valid", "val", "test"} and (root / "images").is_dir():
        return root.parent

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
        resolved_task = TaskType(task_str.strip().lower()) if isinstance(task_str, str) and task_str else task
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


def load_split_samples(config: Config,
                       split: DataSplit) -> list[Sample]:
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
    def __init__(self,
                 s3_client: Any,
                 sample_repo: Any,
                 class_repo: Any,
                 annotation_repo: Any | None = None):
        self.s3 = s3_client
        self.samples = sample_repo
        self.classes = class_repo
        self.annotations = annotation_repo

    def import_zip(self,
                   dataset_id: int,
                   task: TaskType,
                   zip_source: bytes | Path,
                   *,
                   storage_prefix: str,
                   existing_classes: List[str] | None = None,
                   append: bool = False,
                   allow_unlabeled: bool = False,
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

            if append:
                existing_classes = self.classes.get_names(dataset_id)
            config = build_acmenra_dataset(
                root=root,
                task=task,
                fallback_names=existing_classes,
            )
            class_names = config.names or existing_classes or []

            split_samples = [
                (split_enum, split_enum.value.lower(), load_split_samples(config, split_enum))
                for split_enum in (DataSplit.TRAIN, DataSplit.VAL, DataSplit.TEST)
            ]
            total_samples = sum(len(samples) for _, _, samples in split_samples)
            label_errors: dict[Path, str] = {}
            class_ids: dict[int, int] = {}
            if append:
                split_samples = self._skip_existing_samples(dataset_id, split_samples)
                mismatch = config.task != task
                if mismatch:
                    source = _TASK_LABELS.get(config.task, config.task.value)
                    target = _TASK_LABELS.get(task, task.value)
                    warning = f"В архиве разметка {source}, а датасет ожидает {target}."
                for _, _, samples in split_samples:
                    for sample in samples:
                        path = sample.label_path
                        if path is None:
                            continue
                        if mismatch:
                            error = warning if path.read_bytes().strip() else None
                        else:
                            _, error = read_import_label(path, class_names, task)
                        if error is not None:
                            label_errors[path] = error
                if (mismatch or label_errors) and not allow_unlabeled:
                    if not mismatch:
                        warning = "Часть разметки в архиве не удалось прочитать."
                    raise ImportConfirmationRequired(warning, total_samples, len(label_errors))
                if not mismatch and any(samples for _, _, samples in split_samples):
                    class_ids = self._append_class_ids(dataset_id, class_names)
            elif class_names and self.classes is not None:
                self.classes.ensure_classes(dataset_id=dataset_id, names=class_names)

            importable_count = sum(len(samples) for _, _, samples in split_samples)
            report("importing", 20)
            progress_interval = max(1, (importable_count + 99) // 100)

            for _, split_name, samples in split_samples:
                for idx, sample in enumerate(samples):
                    parse_error: str | None = None
                    instances = []
                    raw_txt = b""
                    if sample.label_path is not None:
                        parse_error = label_errors.get(sample.label_path)
                        if parse_error is None:
                            raw_txt = sample.label_path.read_bytes()
                            if not append or class_ids:
                                instances, parse_error = read_import_label(sample.label_path, class_names, task)
                        if parse_error is not None:
                            errors_count += 1
                            if append:
                                raw_txt = b""
                        elif class_ids and any(item.class_id != class_ids[item.class_id] for item in instances):
                            lines = [line.split(maxsplit=1) for line in raw_txt.decode("utf-8").splitlines() if line.strip()]
                            raw_txt = "".join(f"{class_ids[int(class_id)]} {coords}\n" for class_id, coords in lines).encode("utf-8")
                            for item in instances:
                                item.class_id = class_ids[item.class_id]

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

                    s3_img_key = image_key(storage_prefix, split_name, img_filename)
                    s3_lbl_key = label_key(storage_prefix, split_name, sample.stem)
                    s3_thb_key = thumb_key(storage_prefix, split_name, sample.stem)

                    self.s3.put_bytes(s3_img_key, img_bytes, content_type=content_type)
                    self.s3.put_bytes(s3_thb_key, thumb_bytes, content_type="image/jpeg")

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
                            or processed_count == importable_count
                    ):
                        report(
                            "importing",
                            20 + int(processed_count * 75 / max(1, importable_count)),
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

    def _skip_existing_samples(
        self, dataset_id: int, split_samples: list[tuple[DataSplit, str, list[Sample]]],
    ) -> list[tuple[DataSplit, str, list[Sample]]]:
        result = []
        for split, name, samples in split_samples:
            if not samples:
                continue
            existing = {sample.stem.casefold() for sample in self.samples.list_for_split(dataset_id, name)}
            if name == "val":
                existing.update(sample.stem.casefold() for sample in self.samples.list_for_split(dataset_id, "valid"))
            new_samples = []
            for sample in samples:
                stem = sample.stem.casefold()
                if stem not in existing:
                    new_samples.append(sample)
                    existing.add(stem)
            result.append((split, name, new_samples))
        return result

    def _append_class_ids(self, dataset_id: int, class_names: list[str]) -> dict[int, int]:
        target_ids = {row.name.casefold(): row.class_index for row in self.classes.list_for_dataset(dataset_id)}
        mapped = {}
        for source_id, name in enumerate(class_names):
            key = name.strip().casefold()
            if key not in target_ids:
                target_ids[key] = self.classes.add_class(dataset_id, name)
            mapped[source_id] = target_ids[key]
        return mapped
