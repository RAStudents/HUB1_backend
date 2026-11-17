# apps/api/app/api/review.py

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.app.deps import (
    CurrentUser,
    get_dataset_or_404,
    get_review_service,
    require_dataset_role,
)
from apps.api.app.errors import client_error
from apps.api.app.schemas.review import ReviewDecisionDTO, ReviewStatusDTO, SampleStatusUpdateDTO
from core.application.review_service import ReviewService


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/datasets/{dataset_id}/samples",
    tags=["review"],
)


@router.post(
    "/{sample_id}/submit-review",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def submit_sample_for_review(dataset_id: int,
                             sample_id: int,
                             user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                             service: ReviewService = Depends(get_review_service)) -> ReviewStatusDTO:
    try:
        new_status = service.submit_for_review(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=client_error(exc)) from exc


@router.post(
    "/{sample_id}/review",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def decide_sample_review(dataset_id: int,
                         sample_id: int,
                         payload: ReviewDecisionDTO,
                         user: CurrentUser = Depends(require_dataset_role({"owner"})),
                         service: ReviewService = Depends(get_review_service)) -> ReviewStatusDTO:
    try:
        new_status = service.decide(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
            decision=payload.decision,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=client_error(exc)) from exc


@router.post(
    "/{sample_id}/reopen",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def reopen_sample_for_revision(dataset_id: int,
                               sample_id: int,
                               user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                               service: ReviewService = Depends(get_review_service)) -> ReviewStatusDTO:
    try:
        new_status = service.reopen_for_revision(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=client_error(exc)) from exc


@router.patch(
    "/{sample_id}/status",
    response_model=ReviewStatusDTO,
    dependencies=[Depends(get_dataset_or_404)],
)
def change_sample_status(dataset_id: int,
                         sample_id: int,
                         payload: SampleStatusUpdateDTO,
                         user: CurrentUser = Depends(require_dataset_role({"owner"})),
                         service: ReviewService = Depends(get_review_service)) -> ReviewStatusDTO:
    try:
        new_status = service.change_status(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user.id,
            new_status=payload.status,
        )
        return ReviewStatusDTO(sample_id=sample_id, status=new_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=client_error(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=client_error(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=client_error(exc)) from exc
