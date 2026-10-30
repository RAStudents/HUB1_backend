# core/application/export_service.py
import zipfile
from pathlib import Path
from typing import Any

import yaml
from acmenra_cv import TaskType
from acmenra_ds import DatasetLayout

from core.infrastructure.media.scratch import scratch_dir
from core.infrastructure.s3.keys import export_zip_key, image_key, label_key

_SPLITS = ("train", "val", "test")


class ExportService:
    def __init__(
        self,
        s3_client: Any,
        sample_repo: Any,
        class_repo: Any,
        export_repo: Any,
        membership_repo: Any,
    ):
        self.s3 = s3_client
        self.samples = sample_repo
        self.classes = class_repo
        self.exports = export_repo
        self.memberships = membership_repo

    def build_export_zip(
        self,
        dataset_id: int,
        user_id: int,
        task: TaskType,
        layout: DatasetLayout = DatasetLayout.DIRECT,
    ) -> dict:
        """
        Собирает архив датасета только из сэмплов со статусом 'accepted',
        загружает ZIP в S3 и возвращает статус и ссылку на скачивание.
        """
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role is None:
            raise PermissionError("Доступ к датасету запрещён")

        export_record = self.exports.create_export(dataset_id=dataset_id, user_id=user_id)
        export_id = export_record.id

        try:
            accepted_samples = self.samples.list_by_status(
                dataset_id=dataset_id, status="accepted"
            )
            class_names = self.classes.get_names(dataset_id=dataset_id)

            with scratch_dir(prefix=f"export_ds_{dataset_id}_") as tmp_dir:
                ds_root = tmp_dir / "dataset"
                ds_root.mkdir(parents=True, exist_ok=True)

                for split_name in _SPLITS:
                    img_dir, lbl_dir = self._resolve_split_dirs(ds_root, split_name, layout)
                    img_dir.mkdir(parents=True, exist_ok=True)
                    lbl_dir.mkdir(parents=True, exist_ok=True)

                for sample in accepted_samples:
                    split_name = (sample.split or "train").lower()
                    img_dir, lbl_dir = self._resolve_split_dirs(ds_root, split_name, layout)

                    s3_img_key = getattr(sample, "image_key", None) or image_key(
                        dataset_id, split_name, f"{sample.stem}.jpg"
                    )
                    s3_lbl_key = getattr(sample, "label_key", None) or label_key(
                        dataset_id, split_name, sample.stem
                    )

                    img_bytes = self.s3.get_bytes(s3_img_key)
                    if not img_bytes:
                        continue

                    img_ext = Path(s3_img_key).suffix or ".jpg"
                    (img_dir / f"{sample.stem}{img_ext}").write_bytes(img_bytes)

                    lbl_bytes = self.s3.get_bytes(s3_lbl_key) or b""
                    (lbl_dir / f"{sample.stem}.txt").write_bytes(lbl_bytes)

                # Генерация конфига data.yaml для экспорта
                yaml_data = self._build_yaml_dict(
                    class_names=class_names, task=task, layout=layout
                )
                (ds_root / "data.yaml").write_text(
                    yaml.safe_dump(yaml_data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )

                zip_path = tmp_dir / f"dataset_{dataset_id}_export_{export_id}.zip"
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for file_path in ds_root.rglob("*"):
                        if file_path.is_file():
                            zf.write(file_path, arcname=str(file_path.relative_to(ds_root)))

                s3_zip = export_zip_key(dataset_id=dataset_id, export_id=export_id)
                self.s3.put_bytes(
                    s3_zip, zip_path.read_bytes(), content_type="application/zip"
                )

            self.exports.mark_completed(export_id=export_id, s3_key=s3_zip)
            download_url = self.s3.get_presigned_url(s3_zip)

            return {
                "export_id": export_id,
                "status": "completed",
                "exported_samples": len(accepted_samples),
                "download_url": download_url,
            }

        except Exception as exc:
            self.exports.mark_failed(export_id=export_id, error=str(exc))
            raise

    @staticmethod
    def _resolve_split_dirs(
        root: Path, split_name: str, layout: DatasetLayout
    ) -> tuple[Path, Path]:
        if layout == DatasetLayout.REVERSE:
            return root / "images" / split_name, root / "labels" / split_name
        return root / split_name / "images", root / split_name / "labels"

    @staticmethod
    def _build_yaml_dict(
        class_names: list[str],
        task: TaskType,
        layout: DatasetLayout,
    ) -> dict:
        paths = (
            {
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
            }
            if layout == DatasetLayout.REVERSE
            else {
                "train": "train/images",
                "val": "val/images",
                "test": "test/images",
            }
        )
        return {
            **paths,
            "nc": len(class_names),
            "names": list(class_names),
            "task": task.value,
        }