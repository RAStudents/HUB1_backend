# apps/api/app/import_tasks.py

import shutil
import logging
from pathlib import Path

from acmenra_cv import TaskType

from apps.api.app.deps import get_s3_client
from apps.api.app.errors import client_error

from core.application.dataset_service import DatasetService
from core.application.import_service import ImportService, resolve_dataset_root
from core.application.visualizer import load_acmenra_dataset

from core.infrastructure.media.scratch import extract_zip_safely, scratch_dir
from core.infrastructure.sql.base import SessionLocal
from core.infrastructure.sql.repos.annotations import AnnotationRepository
from core.infrastructure.sql.repos.classes import ClassRepository
from core.infrastructure.sql.repos.datasets import DatasetRepository
from core.infrastructure.sql.repos.import_jobs import ImportJobRepository
from core.infrastructure.sql.repos.memberships import MembershipRepository
from core.infrastructure.sql.repos.samples import SampleRepository


logger = logging.getLogger(__name__)


def _update_progress(import_repo, import_id: int, dataset_id: int | None = None):
    def update(**progress) -> None:
        import_repo.update_progress(import_id, dataset_id=dataset_id, **progress)

    return update


def _make_import_service(db) -> ImportService:
    return ImportService(
        s3_client=get_s3_client(),
        sample_repo=SampleRepository(db),
        class_repo=ClassRepository(db),
        annotation_repo=AnnotationRepository(db),
    )


def run_existing_dataset_import(import_id: int,
                                zip_path: str,
                                dataset_id: int,
                                task: str) -> None:
    try:
        with SessionLocal() as db:
            import_repo = ImportJobRepository(db)
            import_repo.update_progress(
                import_id,
                stage="processing",
                progress=1,
                total_samples=0,
                processed_samples=0,
                imported_samples=0,
                parse_errors=0,
            )
            result = _make_import_service(db).import_zip(
                dataset_id=dataset_id,
                task=TaskType(task),
                zip_source=Path(zip_path),
                progress_callback=_update_progress(import_repo, import_id, dataset_id),
            )
            import_repo.update_progress(
                import_id,
                dataset_id=dataset_id,
                status="completed",
                stage="completed",
                progress=100,
                total_samples=result["total_samples"],
                processed_samples=result["total_samples"],
                imported_samples=result["imported_samples"],
                parse_errors=result["parse_errors"],
            )
    except Exception as exc:
        logger.exception("Import job %s failed for dataset %s", import_id, dataset_id)
        with SessionLocal() as db:
            db.rollback()
            ImportJobRepository(db).mark_failed(import_id, client_error(exc))
    finally:
        Path(zip_path).unlink(missing_ok=True)


def run_new_dataset_import(import_id: int,
                           zip_path: str,
                           user_id: int,
                           name: str,
                           task: str,
                           is_private: bool,
                           base_url: str) -> None:
    dataset_id: int | None = None
    try:
        with SessionLocal() as db:
            import_repo = ImportJobRepository(db)
            dataset_repo = DatasetRepository(db)
            class_repo = ClassRepository(db)
            sample_repo = SampleRepository(db)
            import_repo.update_progress(
                import_id,
                stage="extracting",
                progress=2,
                total_samples=0,
                processed_samples=0,
                imported_samples=0,
                parse_errors=0,
            )

            with scratch_dir(prefix=f"validate_import_{import_id}_") as tmp_dir:
                extracted_root = extract_zip_safely(Path(zip_path), tmp_dir)
                real_root = resolve_dataset_root(extracted_root)
                selected_task = TaskType(task)
                dataset = load_acmenra_dataset(real_root, fallback_task=selected_task)
                if dataset.task.value != selected_task.value:
                    raise ValueError(
                        f"Выбранный тип задачи '{task}' не совпадает с task "
                        f"в data.yaml ('{dataset.task.value}')"
                    )

            dataset_service = DatasetService(
                dataset_repo=dataset_repo,
                class_repo=class_repo,
                membership_repo=MembershipRepository(db),
                sample_repo=sample_repo,
            )
            dataset_id = dataset_service.create_dataset(
                name=name,
                task=dataset.task,
                owner_id=user_id,
                is_private=is_private,
                initial_classes=dataset.names,
            )

            result = _make_import_service(db).import_zip(
                dataset_id=dataset_id,
                task=dataset.task,
                zip_source=Path(zip_path),
                existing_classes=dataset.names,
                progress_callback=_update_progress(import_repo, import_id, dataset_id),
            )

            import_repo.update_progress(
                import_id,
                dataset_id=dataset_id,
                status="completed",
                stage="completed",
                progress=100,
                total_samples=result["total_samples"],
                processed_samples=result["total_samples"],
                imported_samples=result["imported_samples"],
                parse_errors=result["parse_errors"],
            )
    except Exception as exc:
        logger.exception("Import job %s failed while creating a dataset", import_id)
        if dataset_id is not None:
            try:
                get_s3_client().delete_prefix(f"datasets/{dataset_id}/")
                storage_path = Path("storage") / f"dataset_{dataset_id}"
                if storage_path.exists():
                    shutil.rmtree(storage_path, ignore_errors=True)
                with SessionLocal() as db:
                    DatasetRepository(db).delete(dataset_id)
            except Exception:
                logger.exception("Failed to clean up dataset %s after import failure", dataset_id)
        with SessionLocal() as db:
            db.rollback()
            ImportJobRepository(db).mark_failed(import_id, client_error(exc))
    finally:
        Path(zip_path).unlink(missing_ok=True)