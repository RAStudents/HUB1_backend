# apps/api/app/errors.py

import logging


logger = logging.getLogger(__name__)


def client_error(exc: Exception) -> str:
    """Наружу только короткие наши сообщения, без путей и трейсбека."""
    if isinstance(exc, (ValueError, PermissionError, LookupError)):
        text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        if text and len(text) <= 200 and "Traceback" not in text and "/" not in text and "\\" not in text:
            return text
    return "Не удалось выполнить операцию"
