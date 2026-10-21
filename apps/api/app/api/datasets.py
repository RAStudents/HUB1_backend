from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import APIRouter, File, UploadFile, HTTPException
from apps.api.app.deps import CurrentUser, get_current_user, get_dataset_service
from core.application.dataset_service import DatasetService
from core.application.visualizer import build_dataset_gallery
from core.domain.enums import TaskTypeEnum
from core.infrastructure.media.scratch import scratch_file

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    """Создание нового датасета."""
    task_str = payload.get("task", "detect")
    task_enum = TaskTypeEnum(task_str) if isinstance(task_str, str) else task_str

    dataset_id = service.create_dataset(
        name=payload.get("name", "Unnamed Dataset"),
        task=task_enum,
        owner_id=user.id,
        description=payload.get("description"),
        is_private=payload.get("is_private", True),
        initial_classes=payload.get("classes"),
    )
    return {"dataset_id": dataset_id, "message": "Датасет успешно создан"}


@router.post("/{dataset_id}/gallery-file")
async def get_dataset_gallery_by_file(
    dataset_id: int,
    file: UploadFile = File(...),
    split: str = "train",
    limit: int = 50 
):
    # Сохраняем загруженный yaml во временный файл на диске
    content = await file.read()
    with scratch_file(suffix=".yaml", data=content) as tmp_yaml:
        try:
            # Передаем временный путь в ваш визуализатор
            items = build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=tmp_yaml,
                split_name=split,
                limit=limit
            )
            return items
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))