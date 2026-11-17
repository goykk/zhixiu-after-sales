"""检查目录：按故障码组织的下一步检查规格（C-PROBE@1）。

`targets` 中的 cause_code 已对齐 design.md §2.2 C-HYPOTHESIS@1 的冻结清单：
E101 POWER_SUPPLY/POWER_WIRING；E103 NETWORK_CONFIG/NETWORK_MODULE；
E105 COMPRESSOR_FAULT/CONDENSER_BLOCKED/REFRIGERANT_LEAK；
E106 FAN_BLOCKED/FAN_MOTOR/FAN_DRIVER；E108 SENSOR_FAULT/SENSOR_WIRING。
planner 用 `targets ∩ 活跃假设 cause_code` 做硬过滤，命名必须与假设规则一致。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeSpec:
    code: str
    probe_type: str
    question: str
    targets: tuple[str, ...]
    expected_outcomes: dict[str, dict]
    cost_level: str
    risk_level: str
    success_rate: float
    coverage: float
    required_tools: tuple[str, ...] = ()


def _outcome(supports: tuple[str, ...] = (), refutes: tuple[str, ...] = ()) -> dict:
    return {"supports": list(supports), "refutes": list(refutes)}


_E101 = (
    ProbeSpec(
        code="ASK_POWER_LED",
        probe_type="question",
        question="设备面板指示灯是否点亮？",
        targets=("POWER_SUPPLY", "POWER_WIRING"),
        expected_outcomes={
            "指示灯不亮": _outcome(
                supports=("POWER_SUPPLY",), refutes=("POWER_WIRING",)
            ),
            "指示灯正常点亮": _outcome(
                supports=("POWER_WIRING",), refutes=("POWER_SUPPLY",)
            ),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.75,
    ),
    ProbeSpec(
        code="CHECK_BREAKER",
        probe_type="self_check",
        question="检查配电箱空气开关是否跳闸，复位后设备是否恢复？",
        targets=("POWER_SUPPLY", "POWER_WIRING"),
        expected_outcomes={
            "开关跳闸且复位后恢复": _outcome(
                supports=("POWER_WIRING",), refutes=("POWER_SUPPLY",)
            ),
            "开关正常但设备仍无电": _outcome(
                supports=("POWER_SUPPLY",), refutes=("POWER_WIRING",)
            ),
        },
        cost_level="medium",
        risk_level="medium",
        success_rate=0.75,
        coverage=0.85,
    ),
    ProbeSpec(
        code="PHOTO_POWER_CORD",
        probe_type="photo",
        question="请拍摄电源线、插头与插座的照片。",
        targets=("POWER_WIRING",),
        expected_outcomes={
            "插头松动或线缆破损": _outcome(supports=("POWER_WIRING",)),
            "插接牢固且线缆完好": _outcome(refutes=("POWER_WIRING",)),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.65,
    ),
    ProbeSpec(
        code="MEASURE_LINE_VOLTAGE",
        probe_type="self_check",
        question="用万用表测量进线电压。",
        targets=("POWER_SUPPLY",),
        expected_outcomes={
            "电压为 0V": _outcome(supports=("POWER_SUPPLY",)),
            "电压正常": _outcome(refutes=("POWER_SUPPLY",)),
        },
        cost_level="high",
        risk_level="high",
        success_rate=0.9,
        coverage=0.9,
        required_tools=("multimeter",),
    ),
)

_E103 = (
    ProbeSpec(
        code="ASK_NETWORK_STATUS",
        probe_type="question",
        question="设备面板是否显示离线/未连接？手机 App 能否发现该设备？",
        targets=("NETWORK_CONFIG", "NETWORK_MODULE"),
        expected_outcomes={
            "App 能发现设备但无法连上云端": _outcome(
                supports=("NETWORK_CONFIG",), refutes=("NETWORK_MODULE",)
            ),
            "App 完全无法发现设备": _outcome(
                supports=("NETWORK_MODULE",), refutes=("NETWORK_CONFIG",)
            ),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.8,
    ),
    ProbeSpec(
        code="CHECK_REBIND",
        probe_type="self_check",
        question="清除配网信息并重新配网、重新绑定账号后，设备是否恢复在线？",
        targets=("NETWORK_CONFIG", "NETWORK_MODULE"),
        expected_outcomes={
            "重新配网后恢复正常": _outcome(
                supports=("NETWORK_CONFIG",), refutes=("NETWORK_MODULE",)
            ),
            "重新配网仍然失败": _outcome(
                supports=("NETWORK_MODULE",), refutes=("NETWORK_CONFIG",)
            ),
        },
        cost_level="medium",
        risk_level="low",
        success_rate=0.85,
        coverage=0.85,
    ),
    ProbeSpec(
        code="PHOTO_NETWORK_MODULE",
        probe_type="photo",
        question="请拍摄设备网络模块与天线接线的照片。",
        targets=("NETWORK_MODULE",),
        expected_outcomes={
            "天线脱落或模块明显损坏": _outcome(supports=("NETWORK_MODULE",)),
            "模块与接线完好": _outcome(refutes=("NETWORK_MODULE",)),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.7,
    ),
    ProbeSpec(
        code="DISASSEMBLE_NETWORK_MEASURE",
        probe_type="self_check",
        question="拆解网络模块并测量供电与信号电平。",
        targets=("NETWORK_MODULE",),
        expected_outcomes={
            "供电或信号电平异常": _outcome(supports=("NETWORK_MODULE",)),
            "供电与信号电平正常": _outcome(refutes=("NETWORK_MODULE",)),
        },
        cost_level="high",
        risk_level="high",
        success_rate=0.9,
        coverage=0.9,
        required_tools=("multimeter", "screwdriver"),
    ),
)

_E105 = (
    ProbeSpec(
        code="ASK_COOLING",
        probe_type="question",
        question="出风口是否有冷风？压缩机启动时是否有明显声响？",
        targets=("COMPRESSOR_FAULT", "CONDENSER_BLOCKED", "REFRIGERANT_LEAK"),
        expected_outcomes={
            "无冷风且压缩机完全无声": _outcome(
                supports=("COMPRESSOR_FAULT",),
                refutes=("REFRIGERANT_LEAK", "CONDENSER_BLOCKED"),
            ),
            "无冷风但压缩机持续运转": _outcome(
                supports=("REFRIGERANT_LEAK",), refutes=("COMPRESSOR_FAULT",)
            ),
            "制冷间歇且外机吹热风": _outcome(
                supports=("CONDENSER_BLOCKED",), refutes=("COMPRESSOR_FAULT",)
            ),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.85,
    ),
    ProbeSpec(
        code="PHOTO_PIPE_FROST",
        probe_type="photo",
        question="请拍摄制冷管路与接头是否有结霜或油渍的照片。",
        targets=("REFRIGERANT_LEAK",),
        expected_outcomes={
            "接头结霜或有油渍": _outcome(supports=("REFRIGERANT_LEAK",)),
            "管路洁净无结霜": _outcome(refutes=("REFRIGERANT_LEAK",)),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.85,
        coverage=0.7,
    ),
    ProbeSpec(
        code="CHECK_CONDENSER_CLEAN",
        probe_type="self_check",
        question="检查冷凝器翅片是否积灰或被遮挡，清理后制冷是否改善？",
        targets=("CONDENSER_BLOCKED",),
        expected_outcomes={
            "清理后制冷明显改善": _outcome(supports=("CONDENSER_BLOCKED",)),
            "清理后无改善": _outcome(refutes=("CONDENSER_BLOCKED",)),
        },
        cost_level="medium",
        risk_level="low",
        success_rate=0.85,
        coverage=0.8,
    ),
    ProbeSpec(
        code="CHECK_COMPRESSOR_START",
        probe_type="self_check",
        question="断电重启后压缩机是否尝试启动并随即停机？",
        targets=("COMPRESSOR_FAULT",),
        expected_outcomes={
            "启动即停或过流保护": _outcome(supports=("COMPRESSOR_FAULT",)),
            "启动后持续平稳运转": _outcome(refutes=("COMPRESSOR_FAULT",)),
        },
        cost_level="medium",
        risk_level="medium",
        success_rate=0.8,
        coverage=0.85,
    ),
    ProbeSpec(
        code="MEASURE_REFRIGERANT_PRESSURE",
        probe_type="self_check",
        question="连接压力表测量系统低压侧压力。",
        targets=("REFRIGERANT_LEAK", "COMPRESSOR_FAULT"),
        expected_outcomes={
            "压力显著低于标准值": _outcome(
                supports=("REFRIGERANT_LEAK",), refutes=("COMPRESSOR_FAULT",)
            ),
            "压力正常或偏高": _outcome(
                supports=("COMPRESSOR_FAULT",), refutes=("REFRIGERANT_LEAK",)
            ),
        },
        cost_level="high",
        risk_level="high",
        success_rate=0.9,
        coverage=0.9,
        required_tools=("manifold_gauge",),
    ),
)

_E106 = (
    ProbeSpec(
        code="ASK_SOUND",
        probe_type="question",
        question="风扇区域是否有异常噪音，或完全无声？",
        targets=("FAN_BLOCKED", "FAN_MOTOR", "FAN_DRIVER"),
        expected_outcomes={
            "有摩擦或刮擦声": _outcome(
                supports=("FAN_BLOCKED",), refutes=("FAN_MOTOR", "FAN_DRIVER")
            ),
            "完全无声": _outcome(
                supports=("FAN_DRIVER",), refutes=("FAN_BLOCKED", "FAN_MOTOR")
            ),
            "转动正常但吹出热风": _outcome(
                supports=("FAN_MOTOR",), refutes=("FAN_BLOCKED", "FAN_DRIVER")
            ),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.85,
    ),
    ProbeSpec(
        code="PHOTO_BLADE",
        probe_type="photo",
        question="请拍摄风扇叶片与出风口的照片。",
        targets=("FAN_BLOCKED",),
        expected_outcomes={
            "叶片有异物或变形": _outcome(
                supports=("FAN_BLOCKED",), refutes=("FAN_MOTOR",)
            ),
            "叶片洁净且可自由转动": _outcome(refutes=("FAN_BLOCKED",)),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.85,
        coverage=0.7,
    ),
    ProbeSpec(
        code="CHECK_ROTATION",
        probe_type="self_check",
        question="断电后手动拨动风扇叶片，是否能顺畅旋转？",
        targets=("FAN_MOTOR", "FAN_DRIVER"),
        expected_outcomes={
            "拨动叶片旋转顺畅": _outcome(
                supports=("FAN_DRIVER",), refutes=("FAN_MOTOR",)
            ),
            "拨动叶片有明显卡滞或阻力": _outcome(
                supports=("FAN_MOTOR", "FAN_BLOCKED"), refutes=("FAN_DRIVER",)
            ),
        },
        cost_level="medium",
        risk_level="medium",
        success_rate=0.75,
        coverage=0.9,
    ),
    ProbeSpec(
        code="DISASSEMBLE_FAN_CAGE",
        probe_type="self_check",
        question="拆开风扇护罩后测量电机绕组阻值。",
        targets=("FAN_MOTOR",),
        expected_outcomes={
            "绕组阻值在规格范围内": _outcome(refutes=("FAN_MOTOR",)),
            "绕组阻值无穷大": _outcome(supports=("FAN_MOTOR",)),
        },
        cost_level="high",
        risk_level="high",
        success_rate=0.9,
        coverage=0.95,
        required_tools=("multimeter", "screwdriver"),
    ),
)

_E108 = (
    ProbeSpec(
        code="ASK_SENSOR_DISPLAY",
        probe_type="question",
        question="面板是否显示温度数值，或闪烁故障指示灯？",
        targets=("SENSOR_FAULT", "SENSOR_WIRING"),
        expected_outcomes={
            "数值乱跳或显示 --": _outcome(
                supports=("SENSOR_FAULT",), refutes=("SENSOR_WIRING",)
            ),
            "数值稳定但故障灯常亮": _outcome(
                supports=("SENSOR_WIRING",), refutes=("SENSOR_FAULT",)
            ),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.75,
    ),
    ProbeSpec(
        code="PHOTO_SENSOR",
        probe_type="photo",
        question="请拍摄室内温度传感器及其接线处照片。",
        targets=("SENSOR_WIRING",),
        expected_outcomes={
            "接线脱落或受潮腐蚀": _outcome(supports=("SENSOR_WIRING",)),
            "接线完好无腐蚀": _outcome(refutes=("SENSOR_WIRING",)),
        },
        cost_level="low",
        risk_level="low",
        success_rate=0.8,
        coverage=0.7,
    ),
    ProbeSpec(
        code="CHECK_SENSOR_SWAP",
        probe_type="self_check",
        question="更换同型号温度传感器后故障是否消失？",
        targets=("SENSOR_FAULT", "SENSOR_WIRING"),
        expected_outcomes={
            "更换后故障消失": _outcome(
                supports=("SENSOR_FAULT",), refutes=("SENSOR_WIRING",)
            ),
            "更换后故障依旧": _outcome(
                supports=("SENSOR_WIRING",), refutes=("SENSOR_FAULT",)
            ),
        },
        cost_level="medium",
        risk_level="medium",
        success_rate=0.85,
        coverage=0.9,
    ),
    ProbeSpec(
        code="DISASSEMBLE_SENSOR_BOARD",
        probe_type="self_check",
        question="拆解控制板测量传感器采样电压。",
        targets=("SENSOR_FAULT",),
        expected_outcomes={
            "采样电压异常": _outcome(supports=("SENSOR_FAULT",)),
            "采样电压正常": _outcome(refutes=("SENSOR_FAULT",)),
        },
        cost_level="high",
        risk_level="high",
        success_rate=0.9,
        coverage=0.95,
        required_tools=("multimeter", "screwdriver"),
    ),
)

PROBE_CATALOG: dict[str, tuple[ProbeSpec, ...]] = {
    "E101": _E101,
    "E103": _E103,
    "E105": _E105,
    "E106": _E106,
    "E108": _E108,
}