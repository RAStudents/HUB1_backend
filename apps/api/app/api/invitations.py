from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.api.app.deps import CurrentUser, get_current_user, get_membership_service
from apps.api.app.schemas.invitation import DatasetInvitationDTO
from core.application.membership_service import MembershipService


router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.get("", response_model=list[DatasetInvitationDTO])
def list_invitations(user: CurrentUser = Depends(get_current_user),
                     service: MembershipService = Depends(get_membership_service)) -> list[dict]:
    return service.list_pending_invitations(user_id=user.id)


@router.post("/{dataset_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_invitation(dataset_id: int,
                      user: CurrentUser = Depends(get_current_user),
                      service: MembershipService = Depends(get_membership_service)) -> Response:
    try:
        service.accept_invitation(dataset_id=dataset_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{dataset_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_invitation(dataset_id: int,
                       user: CurrentUser = Depends(get_current_user),
                       service: MembershipService = Depends(get_membership_service)) -> Response:
    try:
        service.decline_invitation(dataset_id=dataset_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
