from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.app.deps import (
    CurrentUser,
    get_comment_repo,
    get_dataset_or_404,
    get_membership_repo,
    get_sample_repo,
    require_dataset_role,
)
from apps.api.app.schemas.sample_comment import SampleCommentCreateDTO, SampleCommentDTO


router = APIRouter(
    prefix="/datasets/{dataset_id}/samples/{sample_id}/comments",
    tags=["comments"],
)


def _dto(row) -> SampleCommentDTO:
    return SampleCommentDTO(
        id=row.id,
        sample_id=row.sample_id,
        user_id=row.user_id,
        author_name=getattr(row, "author_name", "Пользователь"),
        body=row.body,
        parent_id=row.parent_id,
        annotation_index=row.annotation_index,
        resolved=row.resolved,
        created_at=row.created_at,
    )


@router.get("", response_model=list[SampleCommentDTO])
def list_comments(dataset_id: int,
                  sample_id: int,
                  _user: CurrentUser = Depends(require_dataset_role({"owner", "labeler", "observer"})),
                  _dataset=Depends(get_dataset_or_404),
                  sample_repo=Depends(get_sample_repo),
                  comment_repo=Depends(get_comment_repo)):
    if sample_repo.get_by_id(dataset_id, sample_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден")
    return [_dto(row) for row in comment_repo.list_for_sample(dataset_id, sample_id)]


@router.post("", response_model=SampleCommentDTO, status_code=status.HTTP_201_CREATED)
def add_comment(dataset_id: int,
                sample_id: int,
                payload: SampleCommentCreateDTO,
                user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                _dataset=Depends(get_dataset_or_404),
                sample_repo=Depends(get_sample_repo),
                comment_repo=Depends(get_comment_repo),
                membership_repo=Depends(get_membership_repo)):
    if sample_repo.get_by_id(dataset_id, sample_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Комментарий не может быть пустым")
    if payload.parent_id is not None:
        parent = comment_repo.get_by_id(dataset_id, sample_id, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий для ответа не найден")
        if parent.parent_id is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ответы на ответы не поддерживаются")
    row = comment_repo.create(
        dataset_id=dataset_id,
        sample_id=sample_id,
        user_id=user.id,
        body=body,
        parent_id=payload.parent_id,
        annotation_index=payload.annotation_index,
    )
    return _dto(comment_repo.get_by_id(dataset_id, sample_id, row.id))


@router.post("/{comment_id}/resolve", response_model=SampleCommentDTO)
def resolve_comment(dataset_id: int,
                    sample_id: int,
                    comment_id: int,
                    resolved: bool = True,
                    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                    _dataset=Depends(get_dataset_or_404),
                    comment_repo=Depends(get_comment_repo),
                    membership_repo=Depends(get_membership_repo)):
    row = comment_repo.get_by_id(dataset_id, sample_id, comment_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден")
    role = membership_repo.get_user_role(dataset_id=dataset_id, user_id=user.id)
    if row.user_id != user.id and role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Изменить статус может автор или владелец")
    comment_repo.set_resolved(comment_id, resolved)
    row = comment_repo.get_by_id(dataset_id, sample_id, comment_id)
    return _dto(row)
