# core/domain/annotation.py

import logging


logger = logging.getLogger(__name__)


class AnnotationMetadata:
    def __init__(
        self,
        id: int | None,
        sample_id: int,
        class_id: int,
        created_by: int,
        updated_by: int,
    ):
        self.id = id
        self.sample_id = sample_id
        self.class_id = class_id
        self.created_by = created_by
        self.updated_by = updated_by