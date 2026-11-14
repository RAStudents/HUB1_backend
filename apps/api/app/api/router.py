# apps/api/app/api/router.py

import logging
from fastapi import APIRouter

from apps.api.app.api import (
    auth,
    datasets,
    samples,
    annotations,
    export,
    review,
    locks,
    media,
    members,
    notifications,
    invitations,
    consent,
    privacy_policy,
)


logger = logging.getLogger(__name__)


api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(datasets.router)
api_router.include_router(samples.router)
api_router.include_router(annotations.router)
api_router.include_router(export.router)
api_router.include_router(review.router)
api_router.include_router(locks.router)
api_router.include_router(media.router)
api_router.include_router(members.router)
api_router.include_router(notifications.router)
api_router.include_router(invitations.router)
api_router.include_router(consent.router)
api_router.include_router(privacy_policy.router)
