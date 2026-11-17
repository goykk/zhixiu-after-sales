"""由真实维修记录生成诊断场景集（C-SIM@1 兼容）。

- 输入：真实维修结果 JSONL（字段同 `scripts/import_outcomes.py`）。
- 要求：有效记录 ≥ 60（对齐场景集 60–80 的契约），否则退出码 1。
- 输出：`data/scenarios/real-v1/scenarios.json`（dataset_version=real-v1），写出后用
  `core.simulator.loader.load_scenarios` 自校验。

用法：
  python scripts/build_scenarios_from_real.py --file <real.jsonl> --out data/scenarios/real-v1/scenarios.json
  python scripts/build_scenarios_from_real.py --file data/outcomes/real/v1/sample_template.jsonl --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.diagnosis.hypotheses import DIAGNOSIS_RULES, GENERAL_RULES  # noqa: E402
from core.probes.catalog import PROBE_CATALOG  # noqa: E402
from core.simulator.loader import DEVICE_MODELS, VARIANT_IDS  # noqa: E402

MIN_RECORDS = 60
MAX_RECORDS = 80
HOLDOUT_SHARE = 0.2
VARIANT_IDS_LOCAL = tuple(VARIANT_IDS)


def known_cause_codes() -> set[str]:
    codes = {rule.cause_code for rules in DIAGNOSIS_RULES.values() for rule in rules}
    codes.update(rule.cause_code for rule in GENERAL_RULES)
    return codes


def load_records(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"记录文件不存在：{p}")
    records: list[dict] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        record = json.loads(line)
        record["_lineno"] = lineno
        records.append(record)
    return records


def _eligible_probes(error_code: str) -> list:
    probes = PROBE_CATALOG.get(error_code, ())
    return [p for p in probes if p.risk_level != "high" and not p.required_tools]


def _first_observation(spec) -> str | None:
    for key in spec.expected_outcomes:
        return str(key)
    return None


def _holdout_ids(ids: list[str], share: float = HOLDOUT_SHARE) -> set[str]:
    ranked = sorted(ids, key=lambda value: hashlib.sha1(value.encode("utf-8")).hexdigest())
    count = max(1, round(len(ranked) * share)) if ranked else 0
    return set(ranked[:count])


def build_scenarios(records: list[dict]) -> tuple[list[dict], list[dict]]:
    causes = known_cause_codes()
    skips: list[dict] = []
    prepared: list[dict] = []

    for record in records:
        lineno = record.get("_lineno", "?")
        error_code = str(record.get("error_code") or "")
        device_model = str(record.get("device_model") or "")
        cause = str(record.get("actual_cause_code") or "")
        symptom = str(record.get("case_symptom") or "").strip()
        if error_code not in PROBE_CATALOG:
            skips.append({"line": lineno, "reason": f"error_code 无检查目录：{error_code}"})
            continue
        if device_model not in DEVICE_MODELS:
            skips.append({"line": lineno, "reason": f"device_model 不在演示型号：{device_model}"})
            continue
        if cause not in causes:
            skips.append({"line": lineno, "reason": f"actual_cause_code 非冻结根因：{cause}"})
            continue
        if not symptom:
            skips.append({"line": lineno, "reason": "缺少 case_symptom"})
            continue

        others = [c for c in (r.cause_code for r in DIAGNOSIS_RULES.get(error_code, ())) if c != cause]
        probes = _eligible_probes(error_code)
        answers: dict[str, str] = {}
        expected: list[str] = []
        for spec in probes[:3]:
            observed = _first_observation(spec)
            if observed:
                answers[spec.code] = observed
                expected.append(spec.code)

        variants = []
        for variant_id in VARIANT_IDS_LOCAL:
            variants.append(
                {
                    "id": variant_id,
                    "symptom": symptom,
                    "evidence": [
                        {"source_type": "customer", "polarity": "support", "quote": symptom}
                    ],
                    "probe_answers": dict(answers),
                    "expected_probe_codes": list(expected),
                    "expected_escalation": False,
                    "expected_evidence_manual_ids": [],
                }
            )
        prepared.append(
            {
                "id": f"real-{hashlib.sha1(f'{lineno}:{error_code}:{cause}'.encode()).hexdigest()[:12]}",
                "device_model": device_model,
                "error_code": error_code,
                "true_cause_code": cause,
                "confusable_causes": others[:2],
                "risk_flags": [],
                "holdout": False,
                "variants": variants,
            }
        )

    holdout_ids = _holdout_ids([item["id"] for item in prepared])
    for item in prepared:
        item["holdout"] = item["id"] in holdout_ids
    return prepared, skips


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="由真实维修记录生成场景集")
    parser.add_argument("--file", required=True, help="真实维修结果 JSONL")
    parser.add_argument("--out", default="data/scenarios/real-v1/scenarios.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        records = load_records(args.file)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 2

    scenarios, skips = build_scenarios(records)
    summary = {
        "input": len(records),
        "usable": len(scenarios),
        "skipped": len(skips),
        "min_required": MIN_RECORDS,
    }
    if len(scenarios) < MIN_RECORDS:
        summary["error"] = (
            f"有效记录不足：{len(scenarios)} < {MIN_RECORDS}（场景集需 {MIN_RECORDS}–{MAX_RECORDS}）"
        )
        print(json.dumps(summary, ensure_ascii=False) if args.json else summary["error"], file=sys.stderr)
        return 1

    scenarios = scenarios[:MAX_RECORDS]
    payload = {"dataset_version": "real-v1", "scenarios": scenarios}

    from core.simulator.loader import load_scenarios

    out_path = Path(args.out)
    if args.dry_run:
        summary["would_write"] = str(out_path)
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        loaded = load_scenarios(out_path)
    except ValueError as exc:
        print(f"生成结果未通过加载器校验：{exc}", file=sys.stderr)
        return 1
    summary["written"] = str(out_path)
    summary["scenarios"] = len(loaded)
    summary["holdout"] = sum(1 for item in loaded if item.holdout)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())