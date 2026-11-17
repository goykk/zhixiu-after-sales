"""配置安全自检（CI / 生产环境用）。

复用 `check_jwt_secret`：`ENV=prod|production` 且密钥不足 → 失败退出码 1；否则输出 CONFIG OK。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app.config import settings  # noqa: E402
from services.api.app.hardening import check_jwt_secret  # noqa: E402


def main() -> int:
    try:
        strong = check_jwt_secret(settings)
    except RuntimeError as exc:
        print(f"CONFIG FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"CONFIG OK env={settings.env} jwt_strong={strong}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())