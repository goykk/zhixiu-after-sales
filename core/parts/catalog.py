"""内置配件目录与硬件适用区间判定。

主件号清单由 design.md §2.2 C-PARTS@1 冻结，维修方案模板与种子数据引用同一套编号。
替代件以 `<主件号>-R2` 命名，并在目录中保留独立库存，替代关系本身存放在
`part_compatibilities` 表（由种子脚本写入）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STOCK_IN_STOCK = "in_stock"
STOCK_BACKORDER = "backorder"
STOCK_OUT_OF_STOCK = "out_of_stock"
STOCK_UNKNOWN = "unknown"


@dataclass(frozen=True)
class PartSpec:
    part_no: str
    name: str
    device_model: str
    stock_status: str
    hardware_range: str


PART_CATALOG: dict[str, tuple[PartSpec, ...]] = {
    "AuroraHome AC-Pro 1200": (
        PartSpec("FAN-BLADE-KIT", "风扇扇叶组件", "AuroraHome AC-Pro 1200", STOCK_IN_STOCK, "HW-2.0~HW-2.1"),
        PartSpec("FAN-MOTOR-ASSY", "风扇电机总成", "AuroraHome AC-Pro 1200", STOCK_IN_STOCK, "HW-2.0~HW-2.1"),
        PartSpec("FAN-DRIVER-BOARD", "风扇驱动板", "AuroraHome AC-Pro 1200", STOCK_BACKORDER, "HW-2.0~HW-2.1"),
        PartSpec("POWER-SUPPLY-UNIT", "电源供应单元", "AuroraHome AC-Pro 1200", STOCK_OUT_OF_STOCK, "HW-2.0~HW-2.1"),
        PartSpec("POWER-SUPPLY-UNIT-R2", "电源供应单元（二代替代件）", "AuroraHome AC-Pro 1200", STOCK_IN_STOCK, "HW-2.0~HW-2.1"),
    ),
    "AuroraHome AC-Mini 600": (
        PartSpec("FAN-BLADE-KIT", "风扇扇叶组件", "AuroraHome AC-Mini 600", STOCK_IN_STOCK, "HW-1.0~HW-1.2"),
        PartSpec("FAN-MOTOR-ASSY", "风扇电机总成", "AuroraHome AC-Mini 600", STOCK_BACKORDER, "HW-1.0~HW-1.2"),
        PartSpec("POWER-WIRING-HARNESS", "电源线束", "AuroraHome AC-Mini 600", STOCK_IN_STOCK, "HW-1.0~HW-1.2"),
        PartSpec("SENSOR-KIT", "传感器组件", "AuroraHome AC-Mini 600", STOCK_OUT_OF_STOCK, "HW-1.0~HW-1.2"),
        PartSpec("SENSOR-KIT-R2", "传感器组件（二代替代件）", "AuroraHome AC-Mini 600", STOCK_IN_STOCK, "HW-1.0~HW-1.2"),
    ),
    "NovaDesk PX-220": (
        PartSpec("POWER-SUPPLY-UNIT", "电源供应单元", "NovaDesk PX-220", STOCK_IN_STOCK, "HW-3.0~HW-3.2"),
        PartSpec("CONTROL-BOARD", "主控板", "NovaDesk PX-220", STOCK_BACKORDER, "HW-3.0~HW-3.2"),
        PartSpec("SENSOR-KIT", "传感器组件", "NovaDesk PX-220", STOCK_IN_STOCK, "HW-3.0~HW-3.2"),
        PartSpec("WIFI-MODULE", "无线通信模块", "NovaDesk PX-220", STOCK_OUT_OF_STOCK, "HW-3.0~HW-3.2"),
        PartSpec("WIFI-MODULE-R2", "无线通信模块（二代替代件）", "NovaDesk PX-220", STOCK_IN_STOCK, "HW-3.0~HW-3.2"),
    ),
    "NovaDesk PX-450": (
        PartSpec("POWER-SUPPLY-UNIT", "电源供应单元", "NovaDesk PX-450", STOCK_IN_STOCK, "HW-4.0~HW-4.1"),
        PartSpec("CONTROL-BOARD", "主控板", "NovaDesk PX-450", STOCK_IN_STOCK, "HW-4.0~HW-4.1"),
        PartSpec("WIFI-MODULE", "无线通信模块", "NovaDesk PX-450", STOCK_BACKORDER, "HW-4.0~HW-4.1"),
        PartSpec("SENSOR-HARNESS", "传感器线束", "NovaDesk PX-450", STOCK_OUT_OF_STOCK, "HW-4.0~HW-4.1"),
        PartSpec("SENSOR-HARNESS-R2", "传感器线束（二代替代件）", "NovaDesk PX-450", STOCK_IN_STOCK, "HW-4.0~HW-4.1"),
    ),
    "VentoCool FZ-30": (
        PartSpec("COMPRESSOR-UNIT", "压缩机总成", "VentoCool FZ-30", STOCK_OUT_OF_STOCK, "HW-1.0~HW-1.1"),
        PartSpec("CONDENSER-FILTER", "冷凝器滤网", "VentoCool FZ-30", STOCK_IN_STOCK, "HW-1.0~HW-1.1"),
        PartSpec("POWER-WIRING-HARNESS", "电源线束", "VentoCool FZ-30", STOCK_IN_STOCK, "HW-1.0~HW-1.1"),
        PartSpec("SENSOR-HARNESS", "传感器线束", "VentoCool FZ-30", STOCK_BACKORDER, "HW-1.0~HW-1.1"),
        PartSpec("COMPRESSOR-UNIT-R2", "压缩机总成（二代替代件）", "VentoCool FZ-30", STOCK_IN_STOCK, "HW-1.0~HW-1.1"),
    ),
}


def _model_key(value: str) -> str:
    return " ".join((value or "").split()).lower()


def _part_key(value: str) -> str:
    return re.sub(r"[\s_]+", "-", (value or "").strip().lower())


def parts_for_model(device_model: str) -> list[PartSpec]:
    """按型号返回配件目录；支持全名与去品牌短名（`AC-Pro 1200`）。"""
    key = _model_key(device_model)
    if not key:
        return []
    for full_name, specs in PART_CATALOG.items():
        if _model_key(full_name) == key:
            return list(specs)
    for full_name, specs in PART_CATALOG.items():
        full_key = _model_key(full_name)
        if full_key.endswith(" " + key) or key.endswith(" " + full_key):
            return list(specs)
    return []


def find_part(device_model: str, part_no: str) -> PartSpec | None:
    """按型号与件号查目录条目，件号大小写/空格/下划线不敏感。"""
    target = _part_key(part_no)
    if not target:
        return None
    for spec in parts_for_model(device_model):
        if _part_key(spec.part_no) == target:
            return spec
    return None


_RANGE_RE = re.compile(r"^(?P<lo>.+?)(?:~|～|\.\.|至)(?P<hi>.+)$")
_DASH_RANGE_RE = re.compile(r"^(?P<lo>.+?)\s+-\s+(?P<hi>.+)$")
_ANY_TOKENS = frozenset({"*", "any", "all", "全部", "全系列"})


def _version_key(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text or ""))


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    size = max(len(left), len(right))
    left = left + (0,) * (size - len(left))
    right = right + (0,) * (size - len(right))
    return (left > right) - (left < right)


def _token_matches(token: str, hardware_version: str) -> bool:
    token = token.strip().lower()
    if not token or token in _ANY_TOKENS:
        return True
    version_key = _version_key(hardware_version)

    for operator, comparator in (
        (">=", lambda result: result >= 0),
        ("≥", lambda result: result >= 0),
        ("<=", lambda result: result <= 0),
        ("≤", lambda result: result <= 0),
        (">", lambda result: result > 0),
        ("<", lambda result: result < 0),
    ):
        if token.startswith(operator):
            bound = _version_key(token[len(operator) :])
            if not bound:
                return True
            return comparator(_compare(version_key, bound))

    match = _RANGE_RE.match(token) or _DASH_RANGE_RE.match(token)
    if match:
        low, high = _version_key(match.group("lo")), _version_key(match.group("hi"))
        if not low or not high:
            return True
        return _compare(version_key, low) >= 0 and _compare(version_key, high) <= 0

    if "x" in token or "*" in token:
        prefix = re.split(r"[x*]", token, maxsplit=1)[0]
        prefix = re.sub(r"[\s_-]+$", "", prefix)
        return hardware_version.strip().lower().replace(" ", "").startswith(prefix.replace(" ", ""))

    return _compare(version_key, _version_key(token)) == 0


def hardware_range_matches(hardware_range: str, hardware_version: str) -> bool:
    """判定硬件版本是否落在适用区间内。

    区间支持 `A~B`、`A - B`、`A..B`、`A至B`、`>=A`/`<=A`、`A.x` 通配与逗号并列；
    任一侧为空时无法判定，按“适用”处理（缺失信息不阻断主流程）。
    """
    tokens = [token for token in re.split(r"[,，;；/]", hardware_range or "") if token.strip()]
    if not tokens or not (hardware_version or "").strip():
        return True
    return any(_token_matches(token, hardware_version) for token in tokens)