# apps/api/app/api/locks.py

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.app.deps import CurrentUser, get_dataset_or_404, get_lock_service, require_dataset_role
from apps.api.app.errors import client_error
from core.application.lock_service import LockService


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/datasets/{dataset_id}/samples", tags=["locks"])


@router.post("/{sample_id}/lock")
def acquire_lock(dataset_id: int,
                 sample_id: int,
                 user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                 dataset=Depends(get_dataset_or_404),
                 service: LockService = Depends(get_lock_service)):
    try:
        until = service.acquire(dataset_id=dataset_id, sample_id=sample_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc)) from exc
    return {"sample_id": sample_id, "lock_user": user.id, "lock_until": until}


@router.delete("/{sample_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
def release_lock(dataset_id: int,
                 sample_id: int,
                 user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                 dataset=Depends(get_dataset_or_404),
                 service: LockService = Depends(get_lock_service)):
    try:
        service.release(dataset_id=dataset_id, sample_id=sample_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc)) from exc