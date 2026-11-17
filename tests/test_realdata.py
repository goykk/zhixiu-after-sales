"""真实维修记录接入测试（C-TEST-REALDATA@1）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from core.db.models import WorkOrder
from core.diagnosis.hypotheses import DIAGNOSIS_RULES
from core.probes.catalog import PROBE_CATALOG
from core.simulator.loader import DEVICE_MODELS, load_scenarios

_ROOT = Path(__file__).resolve().parents[1]
_ERROR_CODES = [code for code in ("E101", "E103", "E105", "E106", "E108") if code in PROBE_CATALOG]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_record(index: int) -> dict:
    error_code = _ERROR_CODES[index % len(_ERROR_CODES)]
    cause = DIAGNOSIS_RULES[error_code][0].cause_code
    model = sorted(DEVICE_MODELS)[index % len(DEVICE_MODELS)]
    return {
        "error_code": error_code,
        "device_model": model,
        "case_symptom": f"真实记录 {index}：{error_code} 现象",
        "actual_cause_code": cause,
        "action": "现场处理",
        "parts_replaced": [],
        "resolved": True,
        "note": "test",
    }


def _write_records(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def test_import_dry_run_writes_nothing(db, seed_base, seed_parts):
    mod = _load_script("import_outcomes")
    records = [_valid_record(i) for i in range(3)]
    summary = mod.import_records(db, records, dry_run=True)
    assert summary["imported"] == 3
    assert db.query(WorkOrder).count() == 0


def test_import_invalid_record_is_reported(db, seed_base, seed_parts):
    mod = _load_script("import_outcomes")
    bad = _valid_record(0)
    bad["actual_cause_code"] = "NOT_A_CAUSE"
    summary = mod.import_records(db, [bad], dry_run=False)
    assert summary["invalid"] == 1
    assert summary["imported"] == 0
    assert db.query(WorkOrder).count() == 0


def test_import_is_idempotent(db, seed_base, seed_parts):
    mod = _load_script("import_outcomes")
    records = [_valid_record(i) for i in range(4)]
    first = mod.import_records(db, records, dry_run=False)
    assert first["imported"] == 4
    second = mod.import_records(db, records, dry_run=False)
    assert second["imported"] == 0
    assert second["skipped"] == 4
    assert db.query(WorkOrder).count() == 4


def test_builder_rejects_insufficient_records(tmp_path):
    mod = _load_script("build_scenarios_from_real")
    path = _write_records(tmp_path / "few.jsonl", [_valid_record(i) for i in range(59)])
    assert mod.main(["--file", str(path), "--out", str(tmp_path / "out.json")]) == 1


def test_builder_generates_loadable_dataset(tmp_path):
    mod = _load_script("build_scenarios_from_real")
    path = _write_records(tmp_path / "enough.jsonl", [_valid_record(i) for i in range(60)])
    out = tmp_path / "scenarios.json"
    assert mod.main(["--file", str(path), "--out", str(out)]) == 0
    loaded = load_scenarios(out)
    assert len(loaded) == 60
    assert sum(1 for item in loaded if item.holdout) == 12
    assert all(len(item.variants) == 3 for item in loaded)


def test_builder_probe_answers_are_consistent_and_cover_eligible_probes(tmp_path):
    mod = _load_script("build_scenarios_from_real")
    path = _write_records(tmp_path / "enough.jsonl", [_valid_record(i) for i in range(60)])
    out = tmp_path / "scenarios.json"
    assert mod.main(["--file", str(path), "--out", str(out)]) == 0
    loaded = load_scenarios(out)

    for scenario in loaded:
        eligible = {spec.code for spec in mod._eligible_probes(scenario.error_code)}
        for variant in scenario.variants:
            assert set(variant.probe_answers) == eligible, (
                f"{scenario.id} 缺少检查答案会留下 pending probe"
            )
            for code, observed in variant.probe_answers.items():
                spec = next(
                    item for item in PROBE_CATALOG[scenario.error_code] if item.code == code
                )
                effect = spec.expected_outcomes[observed]
                assert scenario.true_cause_code not in effect.get("refutes", []), (
                    f"{scenario.id}/{code} 的观察值反驳了真实根因"
                )