"""配件目录、兼容性与库存查询。"""

from core.parts.catalog import (
    PART_CATALOG,
    PartSpec,
    find_part,
    hardware_range_matches,
    parts_for_model,
)
from core.parts.compatibility import CompatibilityResult, check_part_compatibility

__all__ = [
    "PART_CATALOG",
    "CompatibilityResult",
    "PartSpec",
    "check_part_compatibility",
    "find_part",
    "hardware_range_matches",
    "parts_for_model",
]