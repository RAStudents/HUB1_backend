# apps/api/app/api/classes.py

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.app.deps import (
    DatasetId,
    CurrentUser,
    get_class_repo,
    get_dataset_or_404,
    require_dataset_role,
)
from apps.api.app.errors import client_error

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/datasets/{dataset_id}/classes",
    tags=["classes"],
)


class ClassNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.get("")
def list_classes(dataset_id: DatasetId,
                 _user: CurrentUser = Depends(
                     require_dataset_role({"owner", "labeler", "observer"})
                 ),
                 _dataset=Depends(get_dataset_or_404),
                 class_repo=Depends(get_class_repo)):
    return {
        "items": [
            {"id": row.class_index, "name": row.name}
            for row in class_repo.list_for_dataset(dataset_id)
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def add_class(dataset_id: DatasetId,
              payload: ClassNameRequest,
              _user: CurrentUser = Depends(
                  require_dataset_role({"owner", "labeler"})
              ),
              _dataset=Depends(get_dataset_or_404),
              class_repo=Depends(get_class_repo)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Название класса не может быть пустым")
    try:
        class_index = class_repo.add_class(dataset_id=dataset_id, name=name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=client_error(exc),
        ) from exc
    return {"id": class_index, "name": name}


@router.patch("/{class_index}")
def rename_class(dataset_id: DatasetId,
                 class_index: int,
                 payload: ClassNameRequest,
                 _user: CurrentUser = Depends(
                     require_dataset_role({"owner", "labeler"})
                 ),
                 _dataset=Depends(get_dataset_or_404),
                 class_repo=Depends(get_class_repo)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Название класса не может быть пустым")
    try:
        renamed = class_repo.rename_class(
            dataset_id=dataset_id,
            class_index=class_index,
            name=name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=client_error(exc),
        ) from exc
    return {"id": class_index, "name": renamed}