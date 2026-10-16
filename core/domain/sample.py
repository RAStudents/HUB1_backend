from datetime import datetime
from core.domain.enums import SplitEnum, SampleStatusEnum


class Sample:
    def __init__(
        self,
        id: int | None,
        dataset_id: int,
        stem: str,
        split: SplitEnum | str,
        status: SampleStatusEnum | str = SampleStatusEnum.UNLABELED,
        is_labeled: bool = False,
        image_key: str = "",
        label_key: str = "",
        thumb_key: str = "",
        lock_user: int | None = None,
        lock_until: datetime | None = None,
        parse_error: str | None = None,
    ):
        self.id = id
        self.dataset_id = dataset_id
        self.stem = stem
        self.split = SplitEnum(split) if isinstance(split, str) else split
        self.status = SampleStatusEnum(status) if isinstance(status, str) else status
        self.is_labeled = is_labeled
        self.image_key = image_key
        self.label_key = label_key
        self.thumb_key = thumb_key
        self.lock_user = lock_user
        self.lock_until = lock_until
        self.parse_error = parse_error