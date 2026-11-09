# core/application/export_service.py

import yaml
import shutil
import zipfile
import logging
from typing import Any
from pathlib import Path
from acmenra_cv import TaskType
from acmenra_ds import Config, Dataset, DatasetLayout, make_category_enum

from core.infrastructure.media.convert import normalize_image_file
from core.infrastructure.media.scratch import scratch_dir, scratch_file
from core.infrastructure.s3.keys import export_zip_key, image_key, label_key


logger = logging.getLogger(__name__)


class ExportService:
    def __init__(self,
                 s3_client: Any,
                 sample_repo: Any,
                 class_repo: Any,
                 export_repo: Any,
                 membership_repo: Any):
        self.s3 = s3_client
        self.samples = sample_repo
        self.classes = class_repo
        self.exports = export_repo
        self.memberships = membership_repo

    def build_export_zip(self,
                         dataset_id: int,
                         user_id: int,
                         task: TaskType,
                         export_id: int | None = None,
                         accepted_samples: list | None = None) -> dict:
        """
        Собирает архив датасета только из сэмплов со статусом 'accepted',
        проверяет его через acmenra-ds, сохраняет в прямой раскладке, загружает ZIP
        в S3 и возвращает статус и ссылку на скачивание.
        """
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role is None:
            if export_id is not None:
                self.exports.mark_failed(
                    export_id=export_id,
                    error="Доступ к датасету запрещён",
                )
            raise PermissionError("Доступ к датасету запрещён")

        if accepted_samples is None:
            accepted_samples = self.samples.list_by_status(
                dataset_id=dataset_id, status="accepted"
            )
        if export_id is None:
            export_record = self.exports.create_export(
                dataset_id=dataset_id,
                user_id=user_id,
                total_samples=len(accepted_samples),
            )
            export_id = export_record.id

        try:
            class_names = self.classes.get_names(dataset_id=dataset_id)

            with scratch_dir(prefix=f"export_ds_{dataset_id}_") as tmp_dir:
                ds_root = tmp_dir / "dataset"
                ds_root.mkdir(parents=True, exist_ok=True)

                config = Config(
                    root=ds_root,
                    train="train/images",
                    val="val/images",
                    test="test/images",
                    names=class_names,
                    task=task,
                    layout=DatasetLayout.DIRECT,
                    val_leaf="val",
                )
                split_dirs = {
                    "train": (config.get_train_images(), config.get_train_labels()),
                    "val": (config.get_val_images(), config.get_val_labels()),
                    "test": (config.get_test_images(), config.get_test_labels()),
                }

                for img_dir, lbl_dir in split_dirs.values():
                    img_dir.mkdir(parents=True, exist_ok=True)
                    lbl_dir.mkdir(parents=True, exist_ok=True)

                exported_samples = 0
                exported_stems: set[tuple[str, str]] = set()
                populated_splits: set[str] = set()
                progress_interval = max(1, (len(accepted_samples) + 99) // 100)
                for sample in accepted_samples:
                    split_name = (sample.split or "train").lower()
                    if split_name not in split_dirs:
                        raise ValueError(
                            f"Неизвестный split '{split_name}' у сэмпла {sample.stem}"
                        )
                    if (
                        Path(sample.stem).name != sample.stem
                        or "/" in sample.stem
                        or "\\" in sample.stem
                    ):
                        raise ValueError(f"Некорректное имя сэмпла: {sample.stem}")
                    stem_key = (split_name, sample.stem)
                    if stem_key in exported_stems:
                        raise ValueError(
                            f"Повторяется имя сэмпла '{sample.stem}' в сплите '{split_name}'"
                        )
                    exported_stems.add(stem_key)
                    img_dir, lbl_dir = split_dirs[split_name]

                    s3_img_key = getattr(sample, "image_key", None) or image_key(
                        dataset_id, split_name, f"{sample.stem}.jpg"
                    )
                    s3_lbl_key = getattr(sample, "label_key", None) or label_key(
                        dataset_id, split_name, sample.stem
                    )

                    img_bytes = self.s3.get_bytes(s3_img_key)
                    if not img_bytes:
                        raise ValueError(
                            f"Не найден файл изображения для сэмпла {sample.stem}"
                        )

                    with scratch_file(
                        suffix=Path(s3_img_key).suffix or ".jpg",
                        data=img_bytes,
                    ) as image_path:
                        normalized_bytes, normalized_filename, _ = normalize_image_file(
                            image_path
                        )

                    image_ext = Path(normalized_filename).suffix.lower()
                    if image_ext not in {".png", ".jpg", ".jpeg"}:
                        raise ValueError(
                            f"Неподдерживаемый формат изображения в сэмпле {sample.stem}"
                        )
                    (img_dir / f"{sample.stem}{image_ext}").write_bytes(normalized_bytes)

                    lbl_bytes = self.s3.get_bytes(s3_lbl_key) or b""
                    (lbl_dir / f"{sample.stem}.txt").write_bytes(lbl_bytes)
                    exported_samples += 1
                    populated_splits.add(split_name)
                    if (
                        exported_samples % progress_interval == 0
                        or exported_samples == len(accepted_samples)
                    ):
                        self.exports.update_progress(
                            export_id=export_id,
                            exported_samples=exported_samples,
                            stage="processing",
                        )

                self.exports.update_stage(export_id=export_id, stage="validating")
                dataset = Dataset(
                    config=config,
                    category=make_category_enum(class_names, allow_empty=True),
                    is_cache=False,
                    is_strict=True,
                )
                health = dataset.health()
                if not health["is_healthy"]:
                    raise ValueError(
                        f"acmenra-ds обнаружила ошибки в экспорте: {health['errors']}"
                    )
                if len(dataset) != exported_samples:
                    raise ValueError(
                        "acmenra-ds загрузила не все экспортируемые изображения "
                        f"({len(dataset)} из {exported_samples})"
                    )

                for split_name in split_dirs:
                    if split_name not in populated_splits:
                        shutil.rmtree(ds_root / split_name)

                self.exports.update_stage(export_id=export_id, stage="packaging")
                yaml_data = self._build_yaml_dict(
                    class_names=class_names,
                    task=task,
                    splits=populated_splits,
                )
                (ds_root / "data.yaml").write_text(
                    yaml.safe_dump(yaml_data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )

                zip_path = tmp_dir / f"dataset_{dataset_id}_export_{export_id}.zip"
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for file_path in sorted(ds_root.rglob("*")):
                        arcname = file_path.relative_to(ds_root).as_posix()
                        if file_path.is_dir():
                            zf.writestr(f"{arcname}/", "")
                        else:
                            zf.write(file_path, arcname=arcname)

                s3_zip = export_zip_key(dataset_id=dataset_id, export_id=export_id)
                self.exports.update_stage(export_id=export_id, stage="uploading")
                self.s3.put_bytes(
                    s3_zip, zip_path.read_bytes(), content_type="application/zip"
                )
                self.exports.update_stage(export_id=export_id, stage="finalizing")

            self.exports.mark_completed(
                export_id=export_id,
                s3_key=s3_zip,
                exported_samples=exported_samples,
                total_samples=len(accepted_samples),
            )
            download_url = self.s3.get_presigned_url(s3_zip)

            return {
                "export_id": export_id,
                "status": "completed",
                "exported_samples": exported_samples,
                "download_url": download_url,
            }

        except Exception as exc:
            self.exports.mark_failed(export_id=export_id, error=str(exc))
            raise

    @staticmethod
    def _build_yaml_dict(class_names: list[str],
                         task: TaskType,
                         splits: set[str]) -> dict:
        yaml_data = {
            split_name: f"{split_name}/images"
            for split_name in ("train", "val", "test")
            if split_name in splits
        }
        yaml_data.update(
            nc=len(class_names),
            names=list(class_names),
            task=task.value,
        )
        return yaml_data