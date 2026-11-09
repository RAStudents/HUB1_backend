# core/infrastructure/sql/schema.py

import logging
from sqlalchemy import (
    Index, MetaData, Table, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.sql import func


logger = logging.getLogger(__name__)


metadata = MetaData()

users_table = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(255), unique=True, nullable=False, index=True),
    Column("password_hash", String(255), nullable=False),
    Column("name", String(255), nullable=False),
    Column("yandex_id", String(255), unique=True, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

datasets_table = Table(
    "datasets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(255), nullable=False),
    Column("task", String(50), nullable=False),  # detect / obb / segment
    Column("owner_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("description", Text, nullable=True),
    Column("is_private", Boolean, default=True, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

classes_table = Table(
    "classes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset_id", Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("class_index", Integer, nullable=False),
    UniqueConstraint("dataset_id", "class_index", name="uq_dataset_class_index"),
)

memberships_table = Table(
    "memberships",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset_id", Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role", String(50), nullable=False),  # owner / labeler / observer
    UniqueConstraint("dataset_id", "user_id", name="uq_dataset_user_membership"),
)

samples_table = Table(
    "samples",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset_id", Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
    Column("stem", String(255), nullable=False),
    Column("split", String(50), nullable=False),  # train / val / test
    Column("status", String(50), server_default="unlabeled", nullable=False),
    Column("is_labeled", Boolean, default=False, nullable=False),
    Column("image_key", Text, nullable=False),
    Column("label_key", Text, nullable=False),
    Column("thumb_key", Text, nullable=False),
    Column("lock_user", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("lock_until", DateTime(timezone=True), nullable=True),
    Column("parse_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index(
    "ix_samples_gallery_dataset_split_id",
    samples_table.c.dataset_id,
    samples_table.c.split,
    samples_table.c.id,
)
Index(
    "ix_samples_gallery_dataset_status_id",
    samples_table.c.dataset_id,
    samples_table.c.status,
    samples_table.c.id,
)

sample_geometries_table = Table(
    "sample_geometries",
    metadata,
    Column(
        "sample_id",
        Integer,
        ForeignKey("samples.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("geometry_json", Text, nullable=False),
)

annotations_table = Table(
    "annotations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sample_id", Integer, ForeignKey("samples.id", ondelete="CASCADE"), nullable=False),
    Column("class_id", Integer, nullable=False),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("updated_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
)
Index(
    "ix_annotations_sample_class",
    annotations_table.c.sample_id,
    annotations_table.c.class_id,
)
Index(
    "ix_annotations_class_sample",
    annotations_table.c.class_id,
    annotations_table.c.sample_id,
)

events_table = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset_id", Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
    Column("sample_id", Integer, ForeignKey("samples.id", ondelete="CASCADE"), nullable=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("action", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

exports_table = Table(
    "exports",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset_id", Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("status", String(50), server_default="processing", nullable=False),  # processing / completed / failed
    Column("stage", String(50), server_default="processing", nullable=False),
    Column("exported_samples", Integer, default=0, nullable=False),
    Column("total_samples", Integer, default=0, nullable=False),
    Column("s3_key", Text, nullable=True),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

import_jobs_table = Table(
    "import_jobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dataset_id", Integer, nullable=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(50), server_default="queued", nullable=False),
    Column("stage", String(50), server_default="queued", nullable=False),
    Column("progress", Integer, default=0, nullable=False),
    Column("total_samples", Integer, default=0, nullable=False),
    Column("processed_samples", Integer, default=0, nullable=False),
    Column("imported_samples", Integer, default=0, nullable=False),
    Column("parse_errors", Integer, default=0, nullable=False),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)