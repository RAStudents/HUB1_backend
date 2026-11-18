class FrameLockConflict(PermissionError):
    """The caller cannot edit because the frame lease is unavailable."""


FRAME_BUSY_MESSAGE = "Этот кадр уже редактируется другим пользователем. Редактирование недоступно."
FRAME_LOCK_EXPIRED_MESSAGE = "Блокировка кадра отсутствует или истекла. Повторно откройте кадр для редактирования."
