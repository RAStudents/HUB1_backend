from fastapi import APIRouter, Depends, HTTPException, status

from acmenra_cv import TaskType
from apps.api.app.deps import (
    CurrentUser,
    get_annotation_service,
    get_current_user,
    get_dataset_or_404,
)
from apps.api.app.schemas.annotation import FrameAnnotationsDTO
from core.application.annotation_service import AnnotationService

router = APIRouter(
    prefix="/datasets/{dataset_id}/samples/{sample_id}/annotations",
    tags=["annotations"],
)


@router.get("", response_model=FrameAnnotationsDTO)
def get_annotations(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(get_current_user),
    dataset=Depends(get_dataset_or_404),
    service: AnnotationService = Depends(get_annotation_service),
) -> FrameAnnotationsDTO:
    """Отдаёт нормализованную разметку кадра (Box / OBB в градусах / Polygon)."""
    try:
        return service.get_frame_annotations(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
            task=TaskType(dataset.task),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        # 404 на чужой датасет, чтобы не раскрывать существование приватных id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put("", response_model=FrameAnnotationsDTO)
def save_annotations(
    dataset_id: int,
    sample_id: int,
    payload: FrameAnnotationsDTO,
    user: CurrentUser = Depends(get_current_user),
    dataset=Depends(get_dataset_or_404),
    service: AnnotationService = Depends(get_annotation_service),
) -> FrameAnnotationsDTO:
    """
    Принимает сохранение из редактора, перезаписывает .txt через LabelWriter
    и перерисовывает тумбу с масками через Drawer.
    """
    try:
        return service.save_frame_annotations(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
            task=TaskType(dataset.task),
            items=payload.items,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))