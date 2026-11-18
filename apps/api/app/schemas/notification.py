from datetime import datetime

from pydantic import BaseModel


class NotificationDTO(BaseModel):
    id: int
    type: str
    title: str
    message: str
    dataset_id: str | None
    is_read: bool
    created_at: datetime


class NotificationPageDTO(BaseModel):
    items: list[NotificationDTO]
    total: int
    unread_count: int
    page: int
    page_size: int


class MarkAllNotificationsReadDTO(BaseModel):
    updated_count: int
