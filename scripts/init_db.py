from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.engine import make_url  # noqa: E402

from core.db.base import Base, create_all, engine  # noqa: E402
from services.api.app.config import settings  # noqa: E402


def sqlite_file_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    database = make_url(url).database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser()


def reset_database(url: str) -> Path | None:
    path = sqlite_file_path(url)
    if path is None:
        print("--reset 仅对 SQLite 文件数据库生效，已跳过删除")
        return None
    engine.dispose()
    if path.exists():
        path.unlink()
        print(f"已删除 {path}")
    else:
        print(f"文件不存在，无需删除：{path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="初始化智修 V1.2 数据库")
    parser.add_argument(
        "--reset", action="store_true", help="仅对 SQLite 删除已有数据库文件后重建"
    )
    args = parser.parse_args(argv)

    url = settings.database_url
    if args.reset:
        reset_database(url)

    create_all()
    tables = ", ".join(sorted(Base.metadata.tables))
    print(f"数据库已就绪：{url}")
    print(f"共 {len(Base.metadata.tables)} 张表：{tables}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())