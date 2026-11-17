"""配件兼容性、替代件与库存判定。

判定顺序（design.md §2.2 C-PARTS@1）：配件不存在 → `unknown`；硬件区间不匹配 →
`incompatible`；其余视为可用，类型由 `part_compatibilities` 关系给出
（`requires_adapter` > `replacement` > `equivalent`）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Part, PartCompatibility
from core.devices import DeviceProfile, find_device_by_model
from core.parts.catalog import find_part, hardware_range_matches

COMPATIBILITY_TYPES = frozenset(
    {"equivalent", "replacement", "requires_adapter", "incompatible", "unknown"}
)
_IN_STOCK = frozenset({"in_stock", "instock", "in stock", "有货"})
_TYPE_PRIORITY = ("requires_adapter", "replacement")


@dataclass(frozen=True)
class CompatibilityResult:
    part_no: str
    compatible: bool
    compatibility_type: str
    evidence_source: str
    stock_status: str
    alternatives: list[str]


def _unknown(part_no: str) -> CompatibilityResult:
    return CompatibilityResult(
        part_no=part_no,
        compatible=False,
        compatibility_type="unknown",
        evidence_source="none",
        stock_status="unknown",
        alternatives=[],
    )


def check_part_compatibility(
    db: Session, *, device_model: str, part_no: str, hardware_version: str = ""
) -> CompatibilityResult:
    """查询配件在指定型号上的兼容性、库存与可替代件。"""
    requested = (part_no or "").strip()
    device = find_device_by_model(db, device_model)
    facts = _part_facts(db, device, device_model, requested)
    if facts is None:
        return _unknown(requested)

    actual, stock_status, hardware_range, evidence_source = facts
    version = (hardware_version or "").strip() or (device.hardware_version if device else "") or ""
    relations = _relations(db, actual)
    alternatives = _alternatives(db, device, device_model, relations, version)

    # 显式不兼容关系与硬件区间越界同样一票否决，优先于 equivalent/replacement/requires_adapter。
    explicit_incompatible = any(
        relation.compatibility_type == "incompatible" for relation in relations
    )
    if explicit_incompatible or not hardware_range_matches(hardware_range, version):
        return CompatibilityResult(
            part_no=actual,
            compatible=False,
            compatibility_type="incompatible",
            evidence_source=evidence_source,
            stock_status=stock_status,
            alternatives=alternatives,
        )
    return CompatibilityResult(
        part_no=actual,
        compatible=True,
        compatibility_type=_relation_type(relations),
        evidence_source=evidence_source,
        stock_status=stock_status,
        alternatives=alternatives,
    )


def _part_facts(
    db: Session, device: DeviceProfile | None, device_model: str, part_no: str
) -> tuple[str, str, str, str] | None:
    """返回 `(part_no, stock_status, hardware_range, evidence_source)`。

    `parts` 表是运营侧库存与适用区间的权威来源；未入库（或设备档案缺失）时
    回退到内置目录，避免演示数据未就绪时整条链路不可用。
    """
    if not part_no:
        return None
    if device is not None:
        row = db.execute(
            select(Part).where(Part.device_id == device.id, Part.part_no == part_no)
        ).scalars().first()
        if row is not None:
            return (
                row.part_no,
                (row.stock_status or "unknown").strip().lower(),
                row.hardware_range or "",
                "parts",
            )
    spec = find_part(device_model, part_no)
    if spec is None:
        return None
    return (spec.part_no, spec.stock_status, spec.hardware_range, "catalog")


def _relations(db: Session, part_no: str) -> list[PartCompatibility]:
    return list(
        db.execute(
            select(PartCompatibility).where(PartCompatibility.source_part_no == part_no)
        ).scalars().all()
    )


def _is_in_stock(stock_status: str) -> bool:
    return (stock_status or "").strip().lower() in _IN_STOCK


def _alternatives(
    db: Session,
    device: DeviceProfile | None,
    device_model: str,
    relations: list[PartCompatibility],
    hardware_version: str,
) -> list[str]:
    """替代件 = 关系类型可用、库存 `in_stock` 且硬件区间匹配的 target_part_no。"""
    alternatives: list[str] = []
    for relation in relations:
        if relation.compatibility_type == "incompatible":
            continue
        facts = _part_facts(db, device, device_model, relation.target_part_no)
        if facts is None:
            continue
        target, stock_status, hardware_range, _ = facts
        if target in alternatives:
            continue
        if _is_in_stock(stock_status) and hardware_range_matches(hardware_range, hardware_version):
            alternatives.append(target)
    return alternatives


def _relation_type(relations: list[PartCompatibility]) -> str:
    types = {relation.compatibility_type for relation in relations}
    for candidate in _TYPE_PRIORITY:
        if candidate in types:
            return candidate
    return "equivalent"