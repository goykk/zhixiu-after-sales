"""C-REPAIR@1: 根因到维修方案的模板库。

配件号集中定义在本模块：方案的 `parts` 必须与 C-PARTS@1 的配件目录（`PART_CATALOG`）
及种子数据保持同一套编号，否则兼容性校验会落到 `unknown` 而无法推荐换件方案。
"""

from __future__ import annotations

from dataclasses import dataclass

FAN_BLADE_KIT = "FAN-BLADE-KIT"
FAN_MOTOR_ASSY = "FAN-MOTOR-ASSY"
FAN_DRIVER_BOARD = "FAN-DRIVER-BOARD"
POWER_SUPPLY_UNIT = "POWER-SUPPLY-UNIT"
POWER_WIRING_HARNESS = "POWER-WIRING-HARNESS"
WIFI_MODULE = "WIFI-MODULE"
COMPRESSOR_UNIT = "COMPRESSOR-UNIT"
CONDENSER_FILTER = "CONDENSER-FILTER"
SENSOR_KIT = "SENSOR-KIT"
SENSOR_HARNESS = "SENSOR-HARNESS"
CONTROL_BOARD = "CONTROL-BOARD"

ACTIONS = ("self_service", "repair_center", "on_site", "replace_part")


@dataclass(frozen=True)
class OptionTemplate:
    action: str
    label: str
    parts: tuple[str, ...]
    rationale: str
    risk_level: str
    estimated_cost: float


REPAIR_TEMPLATES: dict[str, tuple[OptionTemplate, ...]] = {
    "FAN_BLOCKED": (
        OptionTemplate(
            action="self_service",
            label="自行断电清理风道与扇叶异物",
            parts=(),
            rationale="异物或积尘是最常见的卡阻来源，清理后可先观察运行电流与噪音是否恢复。",
            risk_level="low",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门拆机清理并做动平衡检查",
            parts=(),
            rationale="上门可同时清理风道内侧、检查扇叶变形与固定卡扣，一次处理到位。",
            risk_level="low",
            estimated_cost=180.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换风扇叶片组件",
            parts=(FAN_BLADE_KIT,),
            rationale="扇叶变形或根部开裂无法通过清理恢复时，更换叶片组件可彻底消除摩擦异响。",
            risk_level="medium",
            estimated_cost=260.0,
        ),
    ),
    "FAN_MOTOR": (
        OptionTemplate(
            action="self_service",
            label="断电后手动盘车并观察轴承阻力",
            parts=(),
            rationale="先确认轴承是否发涩、轴向间隙是否过大，可避免误换整机部件。",
            risk_level="medium",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门更换风扇电机总成",
            parts=(FAN_MOTOR_ASSY,),
            rationale="轴承磨损已确认时更换电机总成比单换轴承更可靠，且可现场复测转速。",
            risk_level="medium",
            estimated_cost=480.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修更换电机与轴承",
            parts=(FAN_MOTOR_ASSY,),
            rationale="需要拆解定子并做动平衡与噪音测试，寄修工位条件优于现场。",
            risk_level="medium",
            estimated_cost=420.0,
        ),
    ),
    "FAN_DRIVER": (
        OptionTemplate(
            action="on_site",
            label="上门检测驱动板供电与接插件",
            parts=(),
            rationale="先测量驱动板输入电压与 PWM 信号，区分供电异常与驱动板本体损坏。",
            risk_level="low",
            estimated_cost=150.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换风扇驱动板",
            parts=(FAN_DRIVER_BOARD,),
            rationale="供电正常但驱动无输出时，更换驱动板可恢复风扇转速控制。",
            risk_level="medium",
            estimated_cost=380.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修更换驱动板并做带载测试",
            parts=(FAN_DRIVER_BOARD,),
            rationale="带载老化测试需要工装台架，寄修可验证更换后长时间运行稳定性。",
            risk_level="medium",
            estimated_cost=330.0,
        ),
    ),
    "POWER_SUPPLY": (
        OptionTemplate(
            action="on_site",
            label="上门测量电源输出并紧固接线",
            parts=(),
            rationale="先区分电源输出异常与接线压降，避免直接更换电源模块。",
            risk_level="low",
            estimated_cost=160.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换电源模块",
            parts=(POWER_SUPPLY_UNIT,),
            rationale="输出电压超出规格或带载跌落时，更换电源模块是最直接的修复方式。",
            risk_level="medium",
            estimated_cost=350.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="整机寄修检测供电链路",
            parts=(),
            rationale="存在多路负载异常时可整机寄修，逐路排查供电链路与保护电路。",
            risk_level="medium",
            estimated_cost=300.0,
        ),
    ),
    "POWER_WIRING": (
        OptionTemplate(
            action="self_service",
            label="断电后重新插紧电源插头与端子",
            parts=(),
            rationale="插头虚接是最常见的接触不良原因，重新插紧后可复测供电是否稳定。",
            risk_level="low",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门更换电源线束",
            parts=(POWER_WIRING_HARNESS,),
            rationale="端子氧化或线束压伤无法通过紧固恢复时，整体更换线束更安全。",
            risk_level="medium",
            estimated_cost=140.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修检查内部接线与端子",
            parts=(),
            rationale="内部接线段需要拆机检查压接质量与绝缘，寄修可做完整电性能测试。",
            risk_level="low",
            estimated_cost=260.0,
        ),
    ),
    "NETWORK_CONFIG": (
        OptionTemplate(
            action="self_service",
            label="重置网络并重新配网",
            parts=(),
            rationale="配网信息丢失或路由策略变更可通过重置配网恢复，无需更换硬件。",
            risk_level="low",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门协助配网与路由优化",
            parts=(),
            rationale="现场可确认信号强度与路由器设置，排除穿墙衰减与频段冲突。",
            risk_level="low",
            estimated_cost=120.0,
        ),
    ),
    "NETWORK_MODULE": (
        OptionTemplate(
            action="on_site",
            label="上门检查天线与模块接触",
            parts=(),
            rationale="先排除天线脱落与排线松动，再判断通信模块是否本体损坏。",
            risk_level="low",
            estimated_cost=130.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换网络通信模块",
            parts=(WIFI_MODULE,),
            rationale="模块无法注册或信号持续低于阈值时，更换模块可恢复联网能力。",
            risk_level="medium",
            estimated_cost=260.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修更换通信模块并做入网测试",
            parts=(WIFI_MODULE,),
            rationale="入网认证与射频指标需要工装环境，寄修可完成完整入网验证。",
            risk_level="medium",
            estimated_cost=240.0,
        ),
    ),
    "COMPRESSOR_FAULT": (
        OptionTemplate(
            action="on_site",
            label="上门检测压缩机绕组与启动电容",
            parts=(),
            rationale="先测量绕组阻值与启动电容容量，可避免误判导致整机更换。",
            risk_level="medium",
            estimated_cost=220.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修更换压缩机",
            parts=(COMPRESSOR_UNIT,),
            rationale="压缩机更换涉及制冷剂回收与焊接，需要工位与真空设备，寄修更稳妥。",
            risk_level="high",
            estimated_cost=1500.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换压缩机总成",
            parts=(COMPRESSOR_UNIT,),
            rationale="绕组短路或卡缸确认后整机更换压缩机总成，恢复制冷能力。",
            risk_level="high",
            estimated_cost=1600.0,
        ),
    ),
    "CONDENSER_BLOCKED": (
        OptionTemplate(
            action="self_service",
            label="清理滤网与冷凝器表面积尘",
            parts=(),
            rationale="散热不良多由滤网与翅片积尘造成，清理后高压压力可明显回落。",
            risk_level="low",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门深度清洗冷凝器",
            parts=(),
            rationale="翅片深部堵塞需要专用清洗剂与冲洗设备，现场可同步检查风道。",
            risk_level="low",
            estimated_cost=160.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换冷凝器滤网",
            parts=(CONDENSER_FILTER,),
            rationale="滤网破损或变形导致无法有效拦截粉尘时，更换滤网恢复过滤能力。",
            risk_level="low",
            estimated_cost=90.0,
        ),
    ),
    "REFRIGERANT_LEAK": (
        OptionTemplate(
            action="on_site",
            label="上门检漏并补加制冷剂",
            parts=(),
            rationale="先定位泄漏点并做保压确认，再按铭牌充注量补加制冷剂。",
            risk_level="medium",
            estimated_cost=400.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修检漏焊接与保压测试",
            parts=(),
            rationale="换热器内部泄漏需要氮气保压与焊接修复，寄修工位条件更充分。",
            risk_level="medium",
            estimated_cost=520.0,
        ),
    ),
    "SENSOR_FAULT": (
        OptionTemplate(
            action="replace_part",
            label="更换温度/压力传感器",
            parts=(SENSOR_KIT,),
            rationale="传感器读数持续偏离且线路正常时，更换传感器是最直接的修复方式。",
            risk_level="low",
            estimated_cost=180.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门更换并校准传感器",
            parts=(SENSOR_KIT,),
            rationale="现场更换后可立即与标准表比对，确保读数回到允许偏差内。",
            risk_level="low",
            estimated_cost=220.0,
        ),
    ),
    "SENSOR_WIRING": (
        OptionTemplate(
            action="on_site",
            label="上门检查并更换传感器线束",
            parts=(SENSOR_HARNESS,),
            rationale="短路或断路确认在线束侧时，更换线束可恢复信号传输。",
            risk_level="low",
            estimated_cost=190.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修线路检修与屏蔽处理",
            parts=(),
            rationale="干扰导致的信号漂移需要重新布线并加屏蔽层，寄修更易验证。",
            risk_level="low",
            estimated_cost=280.0,
        ),
    ),
    "GENERAL_POWER": (
        OptionTemplate(
            action="self_service",
            label="检查插座与空开并恢复供电",
            parts=(),
            rationale="先确认外部供电与保护开关状态，排除非设备侧原因。",
            risk_level="low",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门检测供电链路与电源模块",
            parts=(),
            rationale="外部供电正常但设备无输出时，现场测量可定位到电源模块或负载。",
            risk_level="medium",
            estimated_cost=180.0,
        ),
        OptionTemplate(
            action="replace_part",
            label="更换电源模块",
            parts=(POWER_SUPPLY_UNIT,),
            rationale="电源模块无输出或带载崩溃时，更换模块恢复整机供电。",
            risk_level="medium",
            estimated_cost=350.0,
        ),
    ),
    "GENERAL_CONTROL": (
        OptionTemplate(
            action="self_service",
            label="断电重启并恢复出厂设置",
            parts=(),
            rationale="控制程序异常可先通过断电重启与恢复默认参数排除软件侧问题。",
            risk_level="low",
            estimated_cost=0.0,
        ),
        OptionTemplate(
            action="on_site",
            label="上门检查控制板与面板连接",
            parts=(CONTROL_BOARD,),
            rationale="面板无响应时现场检查排线与控制板状态，必要时更换控制板。",
            risk_level="medium",
            estimated_cost=300.0,
        ),
        OptionTemplate(
            action="repair_center",
            label="寄修检测控制板与固件",
            parts=(CONTROL_BOARD,),
            rationale="固件校验与元件级检测需要工装，寄修可确认控制板是否需更换。",
            risk_level="medium",
            estimated_cost=320.0,
        ),
    ),
}