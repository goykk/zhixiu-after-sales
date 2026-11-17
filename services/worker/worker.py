"""同步任务 worker。

本版不引入 Celery：手册索引、受理与检查回写都在请求内同步完成。该进程作为
可选后台入口（心跳 + 预留异步任务消费点），可用 `python -m services.worker.worker --once`
验证部署连通性。
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Sequence

from core.observability.tracer import Tracer, get_tracer


@dataclass(frozen=True)
class WorkerConfig:
    interval_seconds: float = 30.0
    run_id: str | None = None
    max_ticks: int | None = None


def run_once(tracer: Tracer | None = None) -> dict:
    """执行一次心跳任务，返回已写入的追踪记录。"""
    active = tracer or get_tracer()
    return active.emit("worker.heartbeat", service="worker")


def run_forever(config: WorkerConfig, tracer: Tracer | None = None) -> int:
    active = tracer or get_tracer(config.run_id)
    ticks = 0
    try:
        while config.max_ticks is None or ticks < config.max_ticks:
            run_once(active)
            ticks += 1
            if config.max_ticks is not None and ticks >= config.max_ticks:
                break
            time.sleep(config.interval_seconds)
    except KeyboardInterrupt:
        return 0
    return ticks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="zhixiu-v12 同步任务 worker")
    parser.add_argument("--once", action="store_true", help="只执行一次心跳后退出")
    parser.add_argument("--interval", type=float, default=30.0, help="心跳间隔秒数")
    parser.add_argument("--run-id", default=None, help="复用已有 run_id")
    parser.add_argument("--max-ticks", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    config = WorkerConfig(
        interval_seconds=args.interval,
        run_id=args.run_id,
        max_ticks=1 if args.once else args.max_ticks,
    )
    run_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())