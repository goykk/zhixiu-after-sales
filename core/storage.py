"""内容寻址的不可变本地对象存储。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.api.app.config import settings

_UNSAFE_FILENAME = re.compile(r"[^\w.\-]+", re.UNICODE)


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    sha256: str
    size: int
    content_type: str | None = None


def safe_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    name = _UNSAFE_FILENAME.sub("_", name).strip("._")
    return (name or "upload")[:96]


class LocalObjectStore:
    """以 sha256 为键的不可变存储：同一内容永远落在同一对象键上。"""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root or settings.upload_dir)

    def object_key(self, sha256: str, filename: str | None) -> str:
        return f"uploads/{sha256[:2]}/{sha256}/{safe_filename(filename)}"

    def _path(self, object_key: str) -> Path:
        root = self.root.resolve()
        path = (root / object_key.lstrip("/")).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"object key escapes store root: {object_key}")
        return path

    def put(self, data: bytes, filename: str | None = None, content_type: str | None = None) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        key = self.object_key(digest, filename)
        path = self._path(key)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
            except OSError:
                Path(tmp).unlink(missing_ok=True)
                raise
        return StoredObject(
            object_key=key,
            sha256=digest,
            size=len(data),
            content_type=content_type,
        )

    def get(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()

    def exists(self, object_key: str) -> bool:
        return self._path(object_key).is_file()


def get_object_store() -> LocalObjectStore:
    return LocalObjectStore()