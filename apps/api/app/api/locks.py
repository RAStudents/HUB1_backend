from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.app.deps import (
    CurrentUser,
    get_dataset_or_404,
    get_lock_service,
    require_dataset_role,
)
from apps.api.app.schemas.lock import SampleLockDTO
from core.application.lock_service import LockService


router = APIRouter(
    prefix="/datasets/{dataset_id}/samples",
    tags=["locks"],
)


@router.post(
    "/{sample_id}/lock",
    response_model=SampleLockDTO,
)
def acquire_sample_lock(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    _dataset=Depends(get_dataset_or_404),
    service: LockService = Depends(get_lock_service),
) -> SampleLockDTO:
    try:
        return service.acquire(dataset_id, sample_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put(
    "/{sample_id}/lock",
    response_model=SampleLockDTO,
)
def renew_sample_lock(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    _dataset=Depends(get_dataset_or_404),
    service: LockService = Depends(get_lock_service),
) -> SampleLockDTO:
    try:
        return service.renew(dataset_id, sample_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/{sample_id}/lock",
    response_model=SampleLockDTO,
)
def release_sample_lock(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    _dataset=Depends(get_dataset_or_404),
    service: LockService = Depends(get_lock_service),
) -> SampleLockDTO:
    try:
        return service.release(dataset_id, sample_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{sample_id}/lock/force-release",
    response_model=SampleLockDTO,
)
def force_release_sample_lock(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner"})),
    _dataset=Depends(get_dataset_or_404),
    service: LockService = Depends(get_lock_service),
) -> SampleLockDTO:
    try:
        return service.force_release(dataset_id, sample_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc