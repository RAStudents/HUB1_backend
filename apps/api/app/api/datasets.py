# apps/api/app/api/datasets.py
import shutil
import traceback
from pathlib import Path
from typing import Optional

from acmenra_cv import TaskType
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from apps.api.app.deps import (
    CurrentUser,
    get_current_user,
    get_dataset_or_404,
    get_dataset_service,
    get_import_service,
    get_sample_repo,
    get_s3_client,
    require_dataset_role,
)
from core.application.dataset_service import DatasetService
from core.application.import_service import ImportService, resolve_dataset_root
from core.application.visualizer import (
    STORAGE_DIR,
    build_dataset_gallery,
    find_dataset_gallery_image,
    load_acmenra_dataset,
    resolve_yaml_path,
)
from core.domain.enums import TaskTypeEnum
from core.infrastructure.media.scratch import extract_zip_safely, scratch_dir
from core.infrastructure.s3.client import S3Client

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("/")
def list_my_datasets(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    base_url = str(request.base_url).rstrip("/")
    items = service.list_user_datasets(user_id=user.id, base_url=base_url)
    return {"total": len(items), "items": items}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    task_str = payload.get("task", "segment")
    task_enum = TaskTypeEnum(task_str) if isinstance(task_str, str) else task_str

    dataset_id = service.create_dataset(
        name=payload.get("name", "Unnamed Dataset"),
        task=task_enum,
        owner_id=user.id,
        description=payload.get("description"),
        is_private=payload.get("is_private", True),
        initial_classes=payload.get("classes"),
    )
    return {"dataset_id": dataset_id, "message": "Датасет успешно создан в БД"}


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner"})),
    dataset=Depends(get_dataset_or_404),
    service: DatasetService = Depends(get_dataset_service),
    s3: S3Client = Depends(get_s3_client),
) -> None:
    """Удаляет датасет владельца, его файлы и связанные записи."""
    s3.delete_prefix(f"datasets/{dataset_id}/")

    legacy_storage = STORAGE_DIR / f"dataset_{dataset_id}"
    if legacy_storage.exists():
        shutil.rmtree(legacy_storage)

    service.delete_dataset(dataset_id=dataset_id)


@router.delete("/{dataset_id}/gallery-item", status_code=status.HTTP_204_NO_CONTENT)
def delete_gallery_item(
    dataset_id: int,
    filename: str = Query(...),
    split: str = Query("train"),
    user: CurrentUser = Depends(require_dataset_role({"owner"})),
    dataset=Depends(get_dataset_or_404),
    s3: S3Client = Depends(get_s3_client),
    sample_repo=Depends(get_sample_repo),
) -> None:
    """Удаляет картинку и связанные файлы из legacy-галереи датасета."""
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректное имя файла")

    normalized_split = split.lower()
    if normalized_split not in {"train", "val", "valid", "test"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный split")

    raw_dir = STORAGE_DIR / f"dataset_{dataset_id}" / "raw"
    if not raw_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")

    try:
        sample_paths = find_dataset_gallery_image(raw_dir, normalized_split, filename)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if sample_paths is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")

    image_path, label_path = sample_paths
    image_path.unlink(missing_ok=True)
    if label_path is not None:
        label_path.unlink(missing_ok=True)

    cached_split = STORAGE_DIR / f"dataset_{dataset_id}" / normalized_split
    (cached_split / "images" / filename).unlink(missing_ok=True)
    (cached_split / "masks" / f"{Path(filename).stem}_mask.png").unlink(missing_ok=True)

    for sample in sample_repo.list_by_stem(
        dataset_id=dataset_id,
        split=normalized_split,
        stem=Path(filename).stem,
    ):
        s3.delete_many([sample.image_key, sample.label_key, sample.thumb_key])
        sample_repo.delete(sample_id=sample.id)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_and_save_dataset(
    request: Request,
    name: str = Form(...),
    task: str = Form(...),
    is_private: bool = Form(True),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
    import_service: ImportService = Depends(get_import_service),
    s3: S3Client = Depends(get_s3_client),
):
    if not file.filename or Path(file.filename).suffix.lower() != ".zip":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Загрузите ZIP-архив со всем датасетом",
        )

    dataset_id: int | None = None
    try:
        content = file.file.read()
        with scratch_dir(prefix="upload_dataset_") as tmp_dir:
            extracted_root = extract_zip_safely(content, tmp_dir)
            real_root = resolve_dataset_root(extracted_root)
            selected_task = TaskType(task)
            ds = load_acmenra_dataset(real_root, fallback_task=selected_task)
            if ds.task.value != selected_task.value:
                raise ValueError(
                    f"Выбранный тип задачи '{task}' не совпадает с task в data.yaml ('{ds.task.value}')"
                )

            dataset_id = service.create_dataset(
                name=name,
                task=ds.task,
                owner_id=user.id,
                is_private=is_private,
                initial_classes=ds.names,
            )

            import_result = import_service.import_zip(
                dataset_id=dataset_id,
                task=ds.task,
                zip_source=content,
                existing_classes=ds.names,
            )

            persistent_raw_dir = STORAGE_DIR / f"dataset_{dataset_id}" / "raw"
            resolved_yaml = resolve_yaml_path(persistent_raw_dir)
            base_url = str(request.base_url).rstrip("/")
            build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=resolved_yaml,
                split_name="train",
                limit=50,
                base_url=base_url,
                fallback_task=ds.task,
            )

            return {
                "dataset_id": dataset_id,
                "name": name,
                "task": str(ds.task),
                "classes": ds.names,
                "imported_samples": import_result["imported_samples"],
                "parse_errors": import_result["parse_errors"],
            }
    except HTTPException:
        raise
    except Exception as exc:
        if dataset_id is not None:
            s3.delete_prefix(f"datasets/{dataset_id}/")
            service.delete_dataset(dataset_id=dataset_id)
            shutil.rmtree(STORAGE_DIR / f"dataset_{dataset_id}", ignore_errors=True)
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{dataset_id}/gallery")
def get_dataset_gallery(
    dataset_id: int,
    request: Request,
    yaml_path: Optional[str] = Query(None),
    split: str = Query("train"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    class_ids: list[int] | None = Query(None),
    dataset=Depends(get_dataset_or_404),
    sample_repo=Depends(get_sample_repo),
):
    base_url = str(request.base_url).rstrip("/")
    persistent_dir = STORAGE_DIR / f"dataset_{dataset_id}"
    raw_dir = persistent_dir / "raw"

    try:
        target_dir = Path(yaml_path) if yaml_path else raw_dir
        if not target_dir.exists():
            target_dir = persistent_dir

        if not target_dir.exists():
            return []

        resolved_yaml = resolve_yaml_path(target_dir)

        normalized_split = split.lower()
        if normalized_split == "all":
            split_names = ("train", "val", "test")
        elif normalized_split in {"train", "val", "valid", "test"}:
            split_names = ("val",) if normalized_split == "valid" else (normalized_split,)
        else:
            raise ValueError(f"Неизвестный split: {split}")

        selected_class_ids = set(class_ids) if class_ids else None
        items = []
        for split_name in split_names:
            split_items = build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=resolved_yaml,
                split_name=split_name,
                limit=limit,
                offset=offset,
                base_url=base_url,
                class_ids=selected_class_ids,
                fallback_task=TaskType(dataset.task),
            )
            sample_splits = (
                ("val", "valid")
                if split_name == "val"
                else (split_name,)
            )
            samples_by_stem = {
                sample.stem: sample
                for sample_split in sample_splits
                for sample in sample_repo.list_for_split(
                    dataset_id=dataset_id,
                    split=sample_split,
                )
            }
            for item in split_items:
                sample = samples_by_stem.get(Path(item["filename"]).stem)
                if sample is not None:
                    item.update(
                        id=sample.id,
                        sample_id=sample.id,
                        split=sample.split,
                        status=sample.status,
                        is_labeled=sample.is_labeled,
                    )
            items.extend(split_items)
        return items[:limit] if normalized_split != "all" else items
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))