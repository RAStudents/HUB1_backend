# apps/api/app/api/datasets.py
import shutil
import traceback
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from apps.api.app.deps import CurrentUser, get_current_user, get_dataset_service
from core.application.dataset_service import DatasetService
from core.application.import_service import resolve_dataset_root
from core.application.visualizer import (
    STORAGE_DIR,
    build_dataset_gallery,
    load_acmenra_dataset,
    resolve_yaml_path,
)
from core.domain.enums import TaskTypeEnum
from core.infrastructure.media.scratch import extract_zip_safely, scratch_dir

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _locate_local_dataset_source(yaml_file_path: Path, filename: str) -> Path | None:
    """
    Если через браузер загружен только одиночный .yaml файл, ищет реальную папку с датасетом
    на локальном компьютере (по путям внутри yaml или в стандартных папках пользователя).
    """
    try:
        raw_cfg = yaml.safe_load(yaml_file_path.read_text(encoding="utf-8")) or {}
    except Exception:
        raw_cfg = {}

    for key in ("path", "train", "val"):
        val = raw_cfg.get(key)
        if isinstance(val, str) and val.strip():
            p = Path(val.strip())
            if p.is_absolute() and p.exists():
                if key == "path":
                    return p
                if p.name in ("train", "val", "valid", "test") and p.parent.name in ("images", "labels"):
                    return p.parent.parent
                if p.name in ("images", "labels") and p.parent.name in ("train", "val", "valid", "test"):
                    return p.parent.parent
                return p.parent

    stem = Path(filename).stem
    search_roots = [
        Path("D:/User/Desktop"),
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path("D:/"),
        Path.cwd().parent,
    ]
    for base in search_roots:
        if not base.exists():
            continue
        candidate = base / stem
        if candidate.is_dir() and ((candidate / "images").is_dir() or (candidate / "train").is_dir()):
            return candidate

    return None


@router.get("/")
def list_my_datasets(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    base_url = str(request.base_url).rstrip("/")
    items = service.list_user_datasets(user_id=user.id, base_url=base_url)
    return {"total": len(items), "items": items}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    task_str = payload.get("task", "segment")
    task_enum = TaskTypeEnum(task_str) if isinstance(task_str, str) else task_str

    dataset_id = service.create_dataset(
        name=payload.get("name", "Unnamed Dataset"),
        task=task_enum,
        owner_id=user.id,
        description=payload.get("description"),
        is_private=payload.get("is_private", True),
        initial_classes=payload.get("classes"),
    )
    return {"dataset_id": dataset_id, "message": "Датасет успешно создан в БД"}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_save_dataset(
    request: Request,
    name: str = Form("Новый датасет"),
    task: str = Form("segment"),
    description: Optional[str] = Form(None),
    yaml_path: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    dataset_id = service.create_dataset(
        name=name,
        task=task,
        owner_id=user.id,
        description=description,
    )

    persistent_raw_dir = STORAGE_DIR / f"dataset_{dataset_id}" / "raw"
    persistent_raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        if file is not None and file.filename:
            content = await file.read()
            suffix = Path(file.filename).suffix.lower()
            if suffix == ".zip":
                with scratch_dir(prefix=f"upload_ds_{dataset_id}_") as tmp_dir:
                    extracted_root = extract_zip_safely(content, tmp_dir)
                    real_root = resolve_dataset_root(extracted_root)
                    shutil.copytree(real_root, persistent_raw_dir, dirs_exist_ok=True)
            else:
                saved_yaml = persistent_raw_dir / file.filename
                saved_yaml.write_bytes(content)
                local_src = _locate_local_dataset_source(saved_yaml, file.filename)
                if local_src and local_src.is_dir():
                    shutil.copytree(local_src, persistent_raw_dir, dirs_exist_ok=True)
                    saved_yaml.write_bytes(content)
        elif yaml_path:
            resolved_yaml = resolve_yaml_path(yaml_path)
            shutil.copytree(resolved_yaml.parent, persistent_raw_dir, dirs_exist_ok=True)

        # Загружаем датасет через acmenra-ds
        ds = load_acmenra_dataset(persistent_raw_dir)
        if ds.names:
            service.classes.ensure_classes(dataset_id=dataset_id, names=ds.names)

        # Сразу строим галерею
        resolved_yaml = resolve_yaml_path(persistent_raw_dir)
        base_url = str(request.base_url).rstrip("/")
        build_dataset_gallery(
            dataset_id=dataset_id,
            yaml_path=resolved_yaml,
            split_name="train",
            limit=50,
            base_url=base_url,
        )

        return {
            "dataset_id": dataset_id,
            "name": name,
            "task": str(ds.task),
            "classes": ds.names,
        }
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{dataset_id}/gallery")
def get_dataset_gallery(
    dataset_id: int,
    request: Request,
    yaml_path: Optional[str] = Query(None),
    split: str = Query("train"),
    limit: int = Query(50, ge=1, le=500),
):
    base_url = str(request.base_url).rstrip("/")
    persistent_dir = STORAGE_DIR / f"dataset_{dataset_id}"
    raw_dir = persistent_dir / "raw"

    try:
        target_dir = Path(yaml_path) if yaml_path else raw_dir
        if not target_dir.exists():
            target_dir = persistent_dir

        if not target_dir.exists():
            return []

        resolved_yaml = resolve_yaml_path(target_dir)

        return build_dataset_gallery(
            dataset_id=dataset_id,
            yaml_path=resolved_yaml,
            split_name=split,
            limit=limit,
            base_url=base_url,
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))