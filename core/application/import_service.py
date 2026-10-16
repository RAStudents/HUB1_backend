from pathlib import Path
from typing import Any, List
import yaml

from acmenra_cv import TaskType
from acmenra_ds import Config, Dataset, DatasetLayout, DataSplit

from core.infrastructure.cv.labels import build_category_enum, parse_label_file
from core.infrastructure.cv.thumbs import render_thumbnail_bytes
from core.infrastructure.media.convert import normalize_image_file
from core.infrastructure.media.scratch import extract_zip_safely, scratch_dir
from core.infrastructure.s3.keys import image_key, label_key, thumb_key


def detect_layout(root: Path) -> DatasetLayout:
    """
    Угадывает раскладку датасета (две раскладки из DATA_CONTRACT.md):
    - DIRECT: root / train / images  (или valid/images, test/images)
    - REVERSE: root / images / train
    """
    if (root / "images").is_dir() and any(
        (root / "images" / s).is_dir() for s in ("train", "val", "valid", "test")
    ):
        return DatasetLayout.REVERSE
    return DatasetLayout.DIRECT


def find_yaml_file(root: Path) -> Path | None:
    """Ищет конфигурационный yaml-файл в корне датасета."""
    for name in ("data.yaml", "dataset.yaml", "config.yaml"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    yaml_files = list(root.glob("*.yaml")) + list(root.glob("*.yml"))
    return yaml_files[0] if yaml_files else None


def build_acmenra_dataset(
    root: Path,
    task: TaskType,
    fallback_names: List[str] | None = None,
) -> Dataset:
    """
    Создаёт объект Dataset из acmenra-ds, автоматически определяя раскладку
    (DIRECT / REVERSE) и подтягивая имена классов из yaml (если он есть).
    """
    layout = detect_layout(root)
    yaml_path = find_yaml_file(root)

    names = fallback_names or []
    val_leaf = "valid" if (root / "valid").exists() or (root / "images" / "valid").exists() else "val"

    if yaml_path is not None:
        raw_cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        yaml_names = raw_cfg.get("names")
        if isinstance(yaml_names, dict):
            names = [yaml_names[k] for k in sorted(yaml_names.keys())]
        elif isinstance(yaml_names, list):
            names = [str(x) for x in yaml_names]

    category_enum = build_category_enum(names)

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

    # is_strict=False позволяет не падать в середине импорта, если один .txt битый,
    # а записать parse_error в конкретный сэмпл БД
    return Dataset(config=config, category=category_enum, is_cache=False, is_strict=False)


class ImportService:
    def __init__(self, s3_client: Any, sample_repo: Any, class_repo: Any):
        self.s3 = s3_client
        self.samples = sample_repo
        self.classes = class_repo

    def import_zip(
        self,
        dataset_id: int,
        task: TaskType,
        zip_source: bytes | Path,
        existing_classes: List[str] | None = None,
    ) -> dict:
        """
        Полный цикл импорта архива:
        1. Распаковывает zip во временную папку (scratch_dir).
        2. Инициализирует acmenra_ds.Dataset.
        3. Проходит циклом по train / val / test.
        4. Парсит разметку, генерирует превью с масками (thumbs.py) и заливает в S3 + БД.
        """
        imported_count = 0
        errors_count = 0

        with scratch_dir(prefix=f"import_ds_{dataset_id}_") as tmp_dir:
            root = extract_zip_safely(zip_source, tmp_dir)
            ds = build_acmenra_dataset(root=root, task=task, fallback_names=existing_classes)

            # Если в датасете были классы в data.yaml — синхронизируем их с БД
            class_names = ds.names or existing_classes or []
            if class_names and self.classes is not None:
                self.classes.ensure_classes(dataset_id=dataset_id, names=class_names)

            # Цикл поочерёдно по train / val / test, как требуется в задаче
            for split_enum in (DataSplit.TRAIN, DataSplit.VAL, DataSplit.TEST):
                split_obj = ds.split(split_enum)
                if split_obj is None:
                    continue

                split_name = split_enum.value.lower()  # 'train', 'val', 'test'

                for idx, sample in enumerate(split_obj.samples):
                    parse_error: str | None = None
                    instances = []

                    # 1. Читаем разметку кадра (или фиксируем ошибку парсинга)
                    if sample.label_path is not None and sample.label_path.exists():
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

                    # 2. Конвертируем картинку при необходимости (heic/webp -> jpg)
                    img_bytes, img_filename, content_type = normalize_image_file(sample.image_path)

                    # 3. Рисуем превьюшку с масками/боксами через Drawer (thumbs.py)
                    # Для кривых форматов сохраняем нормализованный jpg во временный файл перед чтением ImageParser
                    norm_img_path = tmp_dir / img_filename
                    norm_img_path.write_bytes(img_bytes)
                    thumb_bytes = render_thumbnail_bytes(
                        image_path=norm_img_path,
                        instances=instances,
                        task=task,
                    )
                    norm_img_path.unlink(missing_ok=True)

                    # 4. Загружаем в S3: оригинал, .txt и тумбу с масками
                    s3_img_key = image_key(dataset_id, split_name, img_filename)
                    s3_lbl_key = label_key(dataset_id, split_name, sample.stem)
                    s3_thb_key = thumb_key(dataset_id, split_name, sample.stem)

                    self.s3.put_bytes(s3_img_key, img_bytes, content_type=content_type)
                    self.s3.put_bytes(s3_thb_key, thumb_bytes, content_type="image/jpeg")

                    raw_txt = (
                        sample.label_path.read_bytes()
                        if (sample.label_path and sample.label_path.exists())
                        else b""
                    )
                    self.s3.put_bytes(s3_lbl_key, raw_txt, content_type="text/plain")

                    # 5. Записываем сэмпл в Postgres
                    if self.samples is not None:
                        self.samples.create_sample(
                            dataset_id=dataset_id,
                            stem=sample.stem,
                            split=split_name,
                            image_key=s3_img_key,
                            label_key=s3_lbl_key,
                            thumb_key=s3_thb_key,
                            is_labeled=bool(instances),
                            parse_error=parse_error,
                        )

                    imported_count += 1

        return {
            "dataset_id": dataset_id,
            "imported_samples": imported_count,
            "parse_errors": errors_count,
            "classes": class_names,
        }