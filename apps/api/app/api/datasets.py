from fastapi import APIRouter, Depends, status
from apps.api.app.deps import get_dataset_service, CurrentUser, get_current_user
from core.application.dataset_service import DatasetService
from core.domain.enums import TaskTypeEnum
from fastapi import APIRouter, Query, HTTPException
from core.application.visualizer import build_dataset_gallery



router = APIRouter(prefix="/datasets", tags=["datasets"])

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service)
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
        initial_classes=payload.get("classes")
    )
    return {"dataset_id": dataset_id, "message": "Датасет успешно создан"}



router = APIRouter(prefix="/datasets", tags=["Datasets"])

@router.get("/{dataset_id}/gallery")
async def get_dataset_gallery(
    dataset_id: int,
    yaml_path: str = Query(..., description="Абсолютный путь к data.yaml на компьютере"),
    split: str = Query("train", description="train, val или test"),
    limit: int = Query(50)
):
    try:
        items = build_dataset_gallery(
            dataset_id=dataset_id,
            yaml_path=yaml_path,
            split_name=split,
            limit=limit
        )
        return items
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))