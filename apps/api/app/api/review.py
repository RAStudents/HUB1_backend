# apps/api/app/api/review.py
from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.app.deps import (
    CurrentUser,
    get_dataset_or_404,
    get_review_service,
    require_dataset_role,
)
from apps.api.app.schemas.review import ReviewDecisionDTO, ReviewStatusDTO
from core.application.review_service import ReviewService

router = APIRouter(
    prefix="/datasets/{dataset_id}/samples",
    tags=["review"],
)


@router.post(
    "/{sample_id}/submit-review",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def submit_sample_for_review(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    service: ReviewService = Depends(get_review_service),
) -> ReviewStatusDTO:
    try:
        new_status = service.submit_for_review(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{sample_id}/review",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def decide_sample_review(
    dataset_id: int,
    sample_id: int,
    payload: ReviewDecisionDTO,
    user: CurrentUser = Depends(require_dataset_role({"owner"})),
    service: ReviewService = Depends(get_review_service),
) -> ReviewStatusDTO:
    try:
        new_status = service.decide(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
            decision=payload.decision,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{sample_id}/reopen",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def reopen_sample_for_revision(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    service: ReviewService = Depends(get_review_service),
) -> ReviewStatusDTO:
    try:
        new_status = service.reopen_for_revision(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
