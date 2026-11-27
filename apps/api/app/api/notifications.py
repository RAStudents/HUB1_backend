# apps/api/app/api/notifications.py

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.app.deps import CurrentUser, get_current_user, get_notification_repo
from apps.api.app.schemas.notification import MarkAllNotificationsReadDTO, NotificationPageDTO


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPageDTO)
def list_notifications(page: int = Query(1, ge=1),
                       page_size: int = Query(20, ge=1, le=100),
                       user: CurrentUser = Depends(get_current_user),
                       notification_repo=Depends(get_notification_repo)) -> NotificationPageDTO:
    rows, total, unread_count = notification_repo.list_for_user(
        user_id=user.id,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return NotificationPageDTO(
        items=rows,
        total=total,
        unread_count=unread_count,
        page=page,
        page_size=page_size,
    )


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(notification_id: int,
                           user: CurrentUser = Depends(get_current_user),
                           notification_repo=Depends(get_notification_repo)) -> None:
    if not notification_repo.mark_read(
        user_id=user.id,
        notification_id=notification_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Уведомление не найдено",
        )


@router.post("/read-all", response_model=MarkAllNotificationsReadDTO)
def mark_all_notifications_read(user: CurrentUser = Depends(get_current_user),
                                notification_repo=Depends(get_notification_repo)) -> MarkAllNotificationsReadDTO:
    return MarkAllNotificationsReadDTO(
        updated_count=notification_repo.mark_all_read(user_id=user.id)
    )
