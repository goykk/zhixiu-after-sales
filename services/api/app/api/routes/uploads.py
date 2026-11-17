"""案例上传接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import Case, User
from core.multimodal.quality import check_upload, resolve_content_type
from core.multimodal.uploads import Upload, upload_out
from core.policy.rbac import Actor, can_access_case
from core.storage import get_object_store
from services.api.app.config import settings
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["uploads"])


def _load_case(db: Session, case_id: str, actor: Actor) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise ApiError(status_code=404, code="NOT_FOUND", message="案例不存在")
    if not can_access_case(actor, case_user_id=case.user_id):
        raise ApiError(status_code=403, code="FORBIDDEN", message="无权访问该案例")
    return case


@router.post("/cases/{case_id}/uploads", status_code=201)
def create_upload(
    case_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    case = _load_case(db, case_id, actor_of(user))

    data = file.file.read(settings.max_upload_bytes + 1)
    filename = (file.filename or "").strip()
    content_type = resolve_content_type(filename, file.content_type)
    quality = check_upload(filename, file.content_type, len(data), data)
    if not quality.ok:
        raise ApiError(
            status_code=422,
            code="UPLOAD_REJECTED",
            message="上传文件未通过校验",
            details={"reason": quality.reason},
        )

    try:
        stored = get_object_store().put(data, filename, content_type)
    except OSError as exc:
        raise ApiError(status_code=500, code="STORAGE_ERROR", message="对象存储写入失败") from exc

    upload = Upload(
        case_id=case.id,
        filename=filename[:255],
        content_type=content_type,
        size=stored.size,
        sha256=stored.sha256,
        object_key=stored.object_key,
        status="stored",
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload_out(upload)


@router.get("/cases/{case_id}/uploads")
def list_uploads(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    case = _load_case(db, case_id, actor_of(user))
    rows = (
        db.execute(select(Upload).where(Upload.case_id == case.id).order_by(Upload.created_at.asc()))
        .scalars()
        .all()
    )
    return {"items": [upload_out(row) for row in rows]}