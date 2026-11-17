"""上传文件的类型与质量校验。"""

from __future__ import annotations

from dataclasses import dataclass
from mimetypes import guess_type
from pathlib import Path

from services.api.app.config import settings

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
    "text/markdown",
    "text/plain",
}

MIN_UPLOAD_BYTES = 16

_EXTENSION_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


@dataclass(frozen=True)
class QualityResult:
    ok: bool
    reason: str | None = None


def normalize_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def resolve_content_type(filename: str | None, content_type: str | None) -> str:
    declared = normalize_content_type(content_type)
    if declared in ALLOWED_CONTENT_TYPES:
        return declared
    suffix = Path(filename or "").suffix.lower()
    if suffix in _EXTENSION_TYPES:
        return _EXTENSION_TYPES[suffix]
    guessed = normalize_content_type(guess_type(filename or "")[0])
    if guessed in ALLOWED_CONTENT_TYPES:
        return guessed
    return declared or "application/octet-stream"


def check_upload(filename: str | None, content_type: str | None, size: int, data: bytes | None) -> QualityResult:
    resolved = resolve_content_type(filename, content_type)
    if not (filename or "").strip() or resolved not in ALLOWED_CONTENT_TYPES:
        return QualityResult(False, "UNSUPPORTED_TYPE")

    payload = data or b""
    actual_size = size if isinstance(size, int) and size >= 0 else len(payload)
    limit = settings.max_upload_bytes
    if actual_size > limit or len(payload) > limit:
        return QualityResult(False, "TOO_LARGE")
    if actual_size == 0 or not payload:
        return QualityResult(False, "EMPTY")
    if min(actual_size, len(payload)) < MIN_UPLOAD_BYTES:
        return QualityResult(False, "TOO_SMALL")
    return QualityResult(True)