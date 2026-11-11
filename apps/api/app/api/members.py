import smtplib

import logging
import smtplib

from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.api.app.deps import (
    CurrentUser,
    get_dataset_or_404,
    get_invitation_notification_service,
    get_membership_service,
    require_dataset_role,
)
from apps.api.app.schemas.member import (
    AddDatasetMemberDTO,
    DatasetMemberDTO,
    UpdateDatasetMemberRoleDTO,
)
from core.application.invitation_notification_service import (
    InvitationNotificationService,
)
from core.application.membership_service import MembershipService


router = APIRouter(
    prefix="/datasets/{dataset_id}/members",
    tags=["members"],
)
logger = logging.getLogger(__name__)


@router.get("", response_model=list[DatasetMemberDTO])
def list_dataset_members(
    dataset_id: int,
    _user: CurrentUser = Depends(require_dataset_role({"owner"})),
    _dataset=Depends(get_dataset_or_404),
    service: MembershipService = Depends(get_membership_service),
) -> list[DatasetMemberDTO]:
    return service.list_members(dataset_id=dataset_id)


@router.post(
    "",
    response_model=DatasetMemberDTO,
    status_code=status.HTTP_201_CREATED,
)
def add_dataset_member(
    dataset_id: int,
    payload: AddDatasetMemberDTO,
    user: CurrentUser = Depends(require_dataset_role({"owner"})),
    dataset=Depends(get_dataset_or_404),
    service: MembershipService = Depends(get_membership_service),
    notifications: InvitationNotificationService = Depends(
        get_invitation_notification_service
    ),
) -> DatasetMemberDTO:
    try:
        member = service.add_member(
            dataset_id=dataset_id,
            email=payload.email,
            role=payload.role,
            dataset_name=dataset.name,
            inviter_user_id=user.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    inviter_name = member.pop("inviter_name")
    try:
        notifications.send_dataset_invitation(
            to_email=member["email"],
            dataset_name=dataset.name,
            role=member["role"],
            inviter_name=inviter_name,
        )
        member["email_notification_sent"] = True
    except (OSError, RuntimeError, ValueError, smtplib.SMTPException) as exc:
        logger.exception(
            "In-app invitation was created but email delivery failed "
            "(dataset_id=%s, user_id=%s)",
            dataset_id,
            member["user_id"],
        )
        member["email_notification_sent"] = False

    return member


@router.put(
    "/{member_user_id}",
    response_model=DatasetMemberDTO,
)
def update_dataset_member_role(
    dataset_id: int,
    member_user_id: int,
    payload: UpdateDatasetMemberRoleDTO,
    _user: CurrentUser = Depends(require_dataset_role({"owner"})),
    _dataset=Depends(get_dataset_or_404),
    service: MembershipService = Depends(get_membership_service),
) -> DatasetMemberDTO:
    try:
        return service.update_member_role(
            dataset_id=dataset_id,
            user_id=member_user_id,
            role=payload.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_dataset_member(
    dataset_id: int,
    member_user_id: int,
    _user: CurrentUser = Depends(require_dataset_role({"owner"})),
    _dataset=Depends(get_dataset_or_404),
    service: MembershipService = Depends(get_membership_service),
) -> Response:
    try:
        service.remove_member(dataset_id=dataset_id, user_id=member_user_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)