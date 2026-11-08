# core/application/annotation_service.py

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from acmenra_cv import TaskType
from apps.api.app.schemas.annotation import AnnotationItemDTO, FrameAnnotationsDTO
from core.infrastructure.cv.labels import parse_label_file, write_label_file
from core.infrastructure.cv.mapper import dtos_to_instances, instances_to_dtos
from core.infrastructure.cv.thumbs import render_thumbnail_bytes
from core.infrastructure.media.scratch import scratch_file
from core.infrastructure.s3.keys import image_key, label_key, thumb_key


logger = logging.getLogger(__name__)


class AnnotationService:
    def __init__(
        self,
        s3_client: Any,
        sample_repo: Any,
        annotation_repo: Any,
        class_repo: Any,
        membership_repo: Any,
        event_repo: Any | None = None,
    ):
        self.s3 = s3_client
        self.samples = sample_repo
        self.annotations = annotation_repo
        self.classes = class_repo
        self.memberships = membership_repo
        self.events = event_repo

    def get_frame_annotations(
        self,
        dataset_id: int,
        sample_id: int,
        user_id: int,
        task: TaskType,
    ) -> FrameAnnotationsDTO:
        """
        Возвращает разметку кадра фронтенду:
        проверяет доступ → скачивает .txt из S3 → парсит через acmenra-cv → возвращает DTO.
        """
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role is None:
            raise PermissionError("Доступ к датасету запрещён")

        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")

        class_names = self.classes.get_names(dataset_id=dataset_id)
        s3_lbl_key = getattr(sample, "label_key", None) or label_key(
            dataset_id, sample.split, sample.stem
        )

        raw_txt = self.s3.get_bytes(s3_lbl_key)
        if not raw_txt:
            return FrameAnnotationsDTO(sample_id=sample_id, items=[])

        with scratch_file(suffix=".txt", data=raw_txt) as tmp_txt:
            instances = parse_label_file(
                path=tmp_txt,
                class_names=class_names,
                task=task,
                is_strict=False,
            )

        dtos = instances_to_dtos(instances=instances, task=task)
        return FrameAnnotationsDTO(sample_id=sample_id, items=dtos)

    def save_frame_annotations(
        self,
        dataset_id: int,
        sample_id: int,
        user_id: int,
        task: TaskType,
        items: List[AnnotationItemDTO],
    ) -> FrameAnnotationsDTO:
        """
        Сохраняет разметку из редактора:
        1. Проверяет роль (owner | labeler) и активный lock на кадре.
        2. Конвертирует DTO → Instance и записывает .txt через LabelWriter.
        3. Перерисовывает превью с масками через Drawer.
        4. Загружает .txt и превью в S3, обновляет Postgres.
        """
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role not in ("owner", "labeler"):
            raise PermissionError("Недостаточно прав для сохранения разметки")

        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")

        now = datetime.now(timezone.utc)
        lock_expired = sample.lock_until and sample.lock_until < now
        if sample.lock_user != user_id or lock_expired:
            raise PermissionError("Кадр не заблокирован вами или время блокировки истекло")

        class_names = self.classes.get_names(dataset_id=dataset_id)
        instances = dtos_to_instances(dtos=items, task=task, class_names=class_names)

        # Сериализуем инстансы в .txt и читаем байты
        with scratch_file(suffix=".txt") as tmp_txt:
            write_label_file(
                path=tmp_txt,
                instances=instances,
                class_names=class_names,
                task=task,
                is_strict=True,
            )
            new_txt_bytes = tmp_txt.read_bytes()

        # Скачиваем оригинал из S3 и перерисовываем превью
        s3_img_key = getattr(sample, "image_key", None) or image_key(
            dataset_id, sample.split, f"{sample.stem}.jpg"
        )
        img_bytes = self.s3.get_bytes(s3_img_key)
        if not img_bytes:
            raise RuntimeError(f"Оригинал изображения не найден в S3: {s3_img_key}")

        img_ext = Path(s3_img_key).suffix or ".jpg"
        with scratch_file(suffix=img_ext, data=img_bytes) as tmp_img:
            new_thumb_bytes = render_thumbnail_bytes(
                image_path=tmp_img,
                instances=instances,
                task=task,
            )

        # Загружаем обновлённый .txt и превью в S3
        s3_lbl_key = getattr(sample, "label_key", None) or label_key(
            dataset_id, sample.split, sample.stem
        )
        s3_thb_key = getattr(sample, "thumb_key", None) or thumb_key(
            dataset_id, sample.split, sample.stem
        )
        self.s3.put_bytes(s3_lbl_key, new_txt_bytes, content_type="text/plain")
        self.s3.put_bytes(s3_thb_key, new_thumb_bytes, content_type="image/jpeg")

        # Обновляем метаданные аннотаций в БД
        if self.annotations is not None:
            self.annotations.replace_sample_annotations(
                sample_id=sample_id,
                class_ids=[inst.class_id for inst in instances],
                user_id=user_id,
            )

        self.samples.mark_updated(
            sample_id=sample_id,
            is_labeled=bool(instances),
            parse_error=None,
        )
        self.samples.set_status(sample_id=sample_id, status="in_progress")

        if self.events is not None:
            self.events.log(
                dataset_id=dataset_id,
                sample_id=sample_id,
                user_id=user_id,
                action="annotations_saved",
            )

        return FrameAnnotationsDTO(
            sample_id=sample_id,
            items=instances_to_dtos(instances=instances, task=task),
        )
