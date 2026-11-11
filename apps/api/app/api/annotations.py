# apps/api/app/api/annotations.py

import logging
from acmenra_cv import TaskType
from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.app.deps import (
    CurrentUser,
    get_annotation_service,
    get_dataset_or_404,
    require_dataset_role,
)
from apps.api.app.errors import client_error
from apps.api.app.schemas.annotation import FrameAnnotationsDTO
from core.application.annotation_service import AnnotationService


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/datasets/{dataset_id}/samples/{sample_id}/annotations",
    tags=["annotations"],
)


@router.get("", response_model=FrameAnnotationsDTO)
def get_annotations(dataset_id: int,
                    sample_id: int,
                    user: CurrentUser = Depends(
                        require_dataset_role({"owner", "labeler", "observer"})
                    ),
                    dataset=Depends(get_dataset_or_404),
                    service: AnnotationService = Depends(get_annotation_service)) -> FrameAnnotationsDTO:
    """Отдаёт нормализованную разметку кадра (Box / OBB в градусах / Polygon)."""
    try:
        return service.get_frame_annotations(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
            task=TaskType(dataset.task),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc))
    except PermissionError as exc:
        # 404 на чужой датасет, чтобы не раскрывать существование приватных id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc))


@router.put("", response_model=FrameAnnotationsDTO)
def save_annotations(dataset_id: int,
                     sample_id: int,
                     payload: FrameAnnotationsDTO,
                     user: CurrentUser = Depends(
                         require_dataset_role({"owner", "labeler"})
                     ),
                     dataset=Depends(get_dataset_or_404),
                     service: AnnotationService = Depends(get_annotation_service)) -> FrameAnnotationsDTO:
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=client_error(exc))