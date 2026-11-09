# apps/api/app/deps.py

import logging
from typing import Callable, Set

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.application.annotation_service import AnnotationService
from core.application.auth_service import AuthService
from core.application.dataset_service import DatasetService
from core.application.export_service import ExportService
from core.application.import_service import ImportService
from core.application.review_service import ReviewService
from core.infrastructure.auth.tokens import decode_access_token
from core.infrastructure.email.smtp import SMTPEmailService
from core.infrastructure.s3.client import S3Client
from core.infrastructure.sql.base import get_db


logger = logging.getLogger(__name__)


security = HTTPBearer()

# Глобальный инстанс S3-клиента (поднимается один раз при старте)
_s3_client = S3Client()


# --- Инфраструктура ---

def get_s3_client() -> S3Client:
    return _s3_client


def get_email_service() -> SMTPEmailService:
    return SMTPEmailService.from_env()


def get_db_connection():
    """Генератор сессии БД для FastAPI Depends."""
    yield from get_db()


# --- Репозитории ---

def get_user_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.users import UserRepository
    return UserRepository(db)


def get_dataset_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.datasets import DatasetRepository
    return DatasetRepository(db)


def get_sample_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.samples import SampleRepository
    return SampleRepository(db)


def get_annotation_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.annotations import AnnotationRepository
    return AnnotationRepository(db)


def get_class_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.classes import ClassRepository
    return ClassRepository(db)


def get_membership_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.memberships import MembershipRepository
    return MembershipRepository(db)


def get_export_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.exports import ExportRepository
    return ExportRepository(db)

def get_event_repo(db=Depends(get_db_connection)):
    from core.infrastructure.sql.repos.events import EventRepository
    return EventRepository(db)


# --- Аутентификация ---

class CurrentUser:
    def __init__(self, id: int):
        self.id = id


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> CurrentUser:
    """Декодирует JWT из заголовка Authorization и возвращает текущего пользователя."""
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен авторизации",
        )
    return CurrentUser(id=user_id)


# --- Авторизация ---

def require_dataset_role(allowed_roles: Set[str]) -> Callable:
    """
    Фабрика зависимости FastAPI: проверяет, что пользователь состоит в датасете
    и его роль входит в разрешённый набор ('owner', 'labeler', 'observer').
    """
    def role_dependency(
        dataset_id: int,
        user: CurrentUser = Depends(get_current_user),
        membership_repo=Depends(get_membership_repo),
    ) -> CurrentUser:
        role = membership_repo.get_user_role(dataset_id=dataset_id, user_id=user.id)
        if role is None or role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения операции в этом датасете",
            )
        return user

    return role_dependency


def get_dataset_or_404(dataset_id: int,
                       user: CurrentUser = Depends(get_current_user),
                       dataset_repo=Depends(get_dataset_repo)):
    """Проверяет существование датасета (защита от IDOR)."""
    dataset = dataset_repo.get_by_id(dataset_id=dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Датасет не найден",
        )
    return dataset


# --- Сервисы (Application layer) ---

def get_auth_service(user_repo=Depends(get_user_repo)) -> AuthService:
    return AuthService(user_repo=user_repo)


def get_dataset_service(dataset_repo=Depends(get_dataset_repo),
                        class_repo=Depends(get_class_repo),
                        membership_repo=Depends(get_membership_repo),) -> DatasetService:
    return DatasetService(
        dataset_repo=dataset_repo,
        class_repo=class_repo,
        membership_repo=membership_repo,
    )


def get_import_service(
    s3: S3Client = Depends(get_s3_client),
    sample_repo=Depends(get_sample_repo),
    class_repo=Depends(get_class_repo),
    annotation_repo=Depends(get_annotation_repo),
) -> ImportService:
    return ImportService(
        s3_client=s3,
        sample_repo=sample_repo,
        class_repo=class_repo,
        annotation_repo=annotation_repo,
    )


def get_annotation_service(s3: S3Client = Depends(get_s3_client),
                           sample_repo=Depends(get_sample_repo),
                           annotation_repo=Depends(get_annotation_repo),
                           class_repo=Depends(get_class_repo),
                           membership_repo=Depends(get_membership_repo)) -> AnnotationService:
    return AnnotationService(
        s3_client=s3,
        sample_repo=sample_repo,
        annotation_repo=annotation_repo,
        class_repo=class_repo,
        membership_repo=membership_repo,
    )


def get_export_service(s3: S3Client = Depends(get_s3_client),
                       sample_repo=Depends(get_sample_repo),
                       class_repo=Depends(get_class_repo),
                       export_repo=Depends(get_export_repo),
                       membership_repo=Depends(get_membership_repo)) -> ExportService:
    return ExportService(
        s3_client=s3,
        sample_repo=sample_repo,
        class_repo=class_repo,
        export_repo=export_repo,
        membership_repo=membership_repo,
    )


def get_review_service(sample_repo=Depends(get_sample_repo),
                       membership_repo=Depends(get_membership_repo),
                       event_repo=Depends(get_event_repo)) -> ReviewService:
    return ReviewService(
        sample_repo=sample_repo,
        membership_repo=membership_repo,
        event_repo=event_repo,
    )
