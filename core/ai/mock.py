"""确定性 Mock Provider：用于测试与无模型环境的回退。"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from core.ai.base import OCRBlock, OCRResult

# 已知型号全名；裸型号（去品牌短名）同样映射回全名。
KNOWN_MODELS: tuple[str, ...] = (
    "AuroraHome AC-Pro 1200",
    "AuroraHome AC-Pro 900",
    "AuroraHome AC-Mini 600",
    "AuroraHome AC-Lite 500",
    "AuroraHome WH-3000",
    "Northwind DH-200",
    "NovaDesk PX-220",
    "NovaDesk PX-450",
    "VentoCool FZ-30",
)

MODEL_PATTERN = re.compile(r"[A-Z]{2,6}-?\d{3,6}[A-Z]?", re.IGNORECASE)
ERROR_CODE_PATTERN = re.compile(r"[Ee]\d{2,4}")
SERIAL_PATTERN = re.compile(
    r"(?:SN|S/N|序列号)\s*[:：]?\s*([A-Za-z0-9-]{6,})", re.IGNORECASE
)
SYMPTOM_PATTERN = re.compile(
    r"(?:故障现象|现象|symptom)\s*[:：]\s*([^\n。；;]+)", re.IGNORECASE
)

FAULT_RULES: dict[str, tuple[dict[str, object], ...]] = {
    "E101": (
        {"cause_code": "POWER_INPUT", "label": "电源输入异常或插头接触不良", "confidence": 0.50},
        {"cause_code": "POWER_BOARD", "label": "电源板故障", "confidence": 0.30},
    ),
    "E103": (
        {"cause_code": "VOLTAGE_ABNORMAL", "label": "输入电压异常触发保护", "confidence": 0.50},
        {"cause_code": "POWER_BOARD", "label": "电源板故障", "confidence": 0.30},
    ),
    "E105": (
        {"cause_code": "OVERHEAT", "label": "散热不良导致过热保护", "confidence": 0.50},
        {"cause_code": "TEMP_SENSOR", "label": "温度传感器开路或漂移", "confidence": 0.30},
    ),
    "E106": (
        {"cause_code": "FAN_BLOCKED", "label": "风扇轴承磨损或异物卡阻", "confidence": 0.60},
        {"cause_code": "FAN_DRIVER", "label": "风扇驱动供电异常", "confidence": 0.40},
    ),
    "E108": (
        {"cause_code": "COMM_BUS", "label": "通信总线接触不良", "confidence": 0.50},
        {"cause_code": "CONTROL_BOARD", "label": "控制板故障", "confidence": 0.30},
    ),
}

GENERIC_CANDIDATES: tuple[dict[str, object], ...] = (
    {"cause_code": "GENERAL_POWER", "label": "电源或连接异常", "confidence": 0.35},
)

_ATTEMPT_ACTIONS = ("重启", "断电", "复位", "清洁", "清理", "更换", "重插", "调温")


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _strip_brand(full_name: str) -> str:
    _, _, model = full_name.partition(" ")
    return model or full_name


def find_known_model(text: str) -> str | None:
    """全名或去品牌短名命中已知型号时返回全名。"""
    normalized = _normalize(text)
    for full_name in KNOWN_MODELS:
        if _normalize(full_name) in normalized or _normalize(_strip_brand(full_name)) in normalized:
            return full_name
    return None


def _fallback_model(text: str) -> str:
    match = MODEL_PATTERN.search(text)
    return match.group(0).strip() if match else ""


def _extract_serial(text: str) -> str:
    match = SERIAL_PATTERN.search(text)
    return match.group(1).strip() if match else ""


def _extract_error_code(text: str) -> str:
    match = ERROR_CODE_PATTERN.search(text)
    return match.group(0).upper() if match else ""


def _extract_symptom(text: str) -> str:
    match = SYMPTOM_PATTERN.search(text)
    if match:
        return match.group(1).strip()[:200]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:200]


def _extract_environment(text: str) -> dict[str, Any]:
    environment: dict[str, Any] = {}
    location = re.search(r"(室内|室外|阳台|厨房|客厅|机房)", text)
    if location:
        environment["location"] = location.group(1)
    temperature = re.search(r"(-?\d{1,3})\s*(?:℃|°C|度)", text)
    if temperature:
        environment["temperature"] = int(temperature.group(1))
    humidity = re.search(r"湿度\s*[:：]?\s*(\d{1,3})\s*%", text)
    if humidity:
        environment["humidity"] = int(humidity.group(1))
    return environment


def _extract_attempted_steps(text: str) -> list[str]:
    return [action for action in _ATTEMPT_ACTIONS if action in text]


class MockLLM:
    """从 prompt 中按确定性规则抽取字段，不依赖任何外部服务。"""

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
    ) -> str:
        fields = self.generate_json(prompt, system=system)
        model = fields["device_model"] or "未知型号"
        code = fields["error_code"] or "未知故障码"
        return f"[mock] 设备 {model} 故障码 {code}：建议先检查电源与连接。"

    def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_hint: str | None = None,
    ) -> dict[str, Any]:
        text = f"{system}\n{prompt}" if system else prompt
        serial = _extract_serial(text)
        scrubbed = SERIAL_PATTERN.sub(" ", text)
        model = find_known_model(scrubbed) or _fallback_model(scrubbed)
        code = _extract_error_code(scrubbed)
        candidates = [dict(item) for item in FAULT_RULES.get(code, GENERIC_CANDIDATES)]

        if not model:
            question = "请问设备铭牌上的型号是什么？"
        elif not code:
            question = "请问设备显示的故障码是什么？"
        else:
            question = ""

        return {
            "device_model": model,
            "serial_number": serial,
            "error_code": code,
            "symptom": _extract_symptom(text),
            "environment": _extract_environment(text),
            "attempted_steps": _extract_attempted_steps(text),
            "candidates": candidates,
            "clarifying_question": question,
        }


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


class MockEmbedder:
    def __init__(self, dim: int = 64) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            values.extend(byte / 127.5 - 1.0 for byte in digest)
            counter += 1
        return _l2_normalize(values[: self.dim])


class MockOCR:
    def recognize(self, data: bytes, filename: str) -> OCRResult:
        del data
        model = find_known_model(filename) or _fallback_model(filename)
        if not model:
            return OCRResult(text="", blocks=(), confidence=0.2)
        text = f"型号 {model}"
        confidence = 0.4 if "blurry" in filename.lower() else 0.95
        block = OCRBlock(text=text, confidence=confidence)
        return OCRResult(text=text, blocks=(block,), confidence=confidence)