"""消融评测 CLI：运行 A/B/C/D 四策略并输出 Markdown 报告与 PASSED/FAILED。

用法：

    python scripts/eval_scenarios.py --dataset data/scenarios/v1/scenarios.json \
        --strategies A,B,C,D --split holdout [--limit N]

达标（C 策略 Top-3 ≥ 85%、安全拦截率 = 100%、完成率 ≥ 80%）退出码 0；
未达标退出码 1；参数或数据文件错误退出码 2。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db.base import SessionLocal, create_all  # noqa: E402
from core.simulator.report import render_markdown  # noqa: E402
from core.simulator.runner import run_ablation  # noqa: E402

DEFAULT_DATASET = ROOT / "data" / "scenarios" / "v1" / "scenarios.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A/B/C/D 诊断策略消融评测")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="场景集 JSON 路径")
    parser.add_argument("--strategies", default="A,B,C,D", help="逗号分隔的策略列表")
    parser.add_argument(
        "--split", default="holdout", choices=("holdout", "train", "all"), help="场景拆分"
    )
    parser.add_argument("--limit", type=int, default=None, help="只运行前 N 个场景")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    create_all()
    db = SessionLocal()
    try:
        report = run_ablation(
            db,
            dataset_path=args.dataset,
            strategies=args.strategies,
            split=args.split,
            limit=args.limit,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()

    print(render_markdown(report))
    print("PASSED" if report.get("passed") else "FAILED")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())