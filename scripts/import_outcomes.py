"""导入真实维修结果（JSONL）为 Case + WorkOrder + RepairOutcome（幂等）。

记录字段（每行一个 JSON 对象）：
  error_code, device_model, case_symptom, actual_cause_code,
  action, parts_replaced (list[str]), resolved (bool), note

用法：
  python scripts/import_outcomes.py --file data/outcomes/real/v1/sample_template.jsonl --dry-run
  python scripts/import_outcomes.py --file <real.jsonl>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db.base import SessionLocal  # noqa: E402
from core.db.models import Case, RepairOutcome, User, WorkOrder, new_id, utcnow  # noqa: E402
from core.devices import find_device_by_model  # noqa: E402
from core.diagnosis.hypotheses import DIAGNOSIS_RULES, GENERAL_RULES  # noqa: E402

REQUIRED_FIELDS = ("error_code", "device_model", "case_symptom", "actual_cause_code", "action")


def known_cause_codes() -> set[str]:
    codes = {rule.cause_code for rules in DIAGNOSIS_RULES.values() for rule in rules}
    codes.update(rule.cause_code for rule in GENERAL_RULES)
    return codes


def load_records(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"记录文件不存在：{p}")
    records = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"第 {lineno} 行不是合法 JSON：{exc}") from exc
        record["_lineno"] = lineno
        records.append(record)
    return records


def validate_record(db, record: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not str(record.get(field) or "").strip():
            errors.append(f"缺少字段 {field}")
    cause = str(record.get("actual_cause_code") or "")
    if cause and cause not in known_cause_codes():
        errors.append(f"未知根因 actual_cause_code={cause}")
    model = str(record.get("device_model") or "")
    if model and find_device_by_model(db, model) is None:
        errors.append(f"设备型号未建档：{model}")
    parts = record.get("parts_replaced")
    if parts is not None and not isinstance(parts, list):
        errors.append("parts_replaced 必须是数组")
    return errors


def _real_key(record: dict) -> str:
    payload = {k: v for k, v in record.items() if not k.startswith("_")}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def _pick_user(db) -> User | None:
    for email in ("user@demo.local", "agent@demo.local", "admin@demo.local"):
        found = db.query(User).filter(User.email == email).first()
        if found is not None:
            return found
    return db.query(User).first()


def import_records(db, records: list[dict], *, dry_run: bool = False) -> dict:
    cause_codes = known_cause_codes()
    user = _pick_user(db)
    summary = {"total": len(records), "imported": 0, "skipped": 0, "invalid": 0, "errors": []}
    if user is None:
        summary["errors"].append("数据库中没有可用用户，无法挂载案例")
        return summary

    for record in records:
        lineno = record.get("_lineno", "?")
        problems = validate_record(db, record)
        if problems:
            summary["invalid"] += 1
            summary["errors"].append({"line": lineno, "problems": problems})
            continue

        key = f"real-{_real_key(record)}"
        if db.query(WorkOrder).filter(WorkOrder.idempotency_key == key).first() is not None:
            summary["skipped"] += 1
            continue
        if dry_run:
            summary["imported"] += 1
            continue

        profile = find_device_by_model(db, str(record["device_model"]))
        case = Case(
            id=new_id(),
            user_id=user.id,
            device_id=profile.id if profile else None,
            status="WORK_ORDER_CREATED",
            symptom=str(record.get("case_symptom") or ""),
            error_code=str(record.get("error_code") or ""),
            extracted={"source": "real", "real_key": key},
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(case)
        db.flush()
        order = WorkOrder(
            id=new_id(),
            case_id=case.id,
            idempotency_key=key,
            status="resolved",
            external_id=f"REAL-{key[-6:]}",
            resolution=str(record.get("action") or ""),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(order)
        db.flush()
        db.add(
            RepairOutcome(
                id=new_id(),
                work_order_id=order.id,
                technician_id=user.id,
                actual_cause_code=str(record.get("actual_cause_code") or ""),
                action=str(record.get("action") or ""),
                parts_replaced=list(record.get("parts_replaced") or []),
                resolved=bool(record.get("resolved", True)),
                note=str(record.get("note") or ""),
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        db.commit()
        summary["imported"] += 1

    if dry_run:
        db.rollback()
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导入真实维修结果")
    parser.add_argument("--file", default="data/outcomes/real/v1/sample_template.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        records = load_records(args.file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 2
    if args.limit:
        records = records[: args.limit]

    db = SessionLocal()
    try:
        summary = import_records(db, records, dry_run=args.dry_run)
    finally:
        db.close()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(
            f"total={summary['total']} imported={summary['imported']} "
            f"skipped={summary['skipped']} invalid={summary['invalid']}"
            + (" (dry-run)" if args.dry_run else "")
        )
        for err in summary["errors"]:
            print(f"  - {err}", file=sys.stderr)
    return 1 if summary["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())