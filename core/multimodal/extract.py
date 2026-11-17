"""OCR + LLM 结构化字段提取，型号必须命中设备档案。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from core.ai.base import ProviderError
from core.ai.factory import get_llm, get_ocr
from core.devices import find_device_by_model
from core.multimodal.pdf import extract_pdf_text, pdf_page_markers
from core.multimodal.quality import normalize_content_type
from core.storage import get_object_store
from services.api.app.config import settings

TEXT_CONTENT_TYPES = {"text/markdown", "text/plain"}
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
PDF_CONTENT_TYPE = "application/pdf"
PDF_SUFFIX = ".pdf"
MODEL_PATTERN = re.compile(r"\b[A-Za-z]{2,6}-?\s?\d{3,6}[A-Za-z]?\b")
ERROR_CODE_PATTERN = re.compile(r"[Ee]\d{2,4}")

_SYSTEM_PROMPT = "你是售后故障信息抽取器，只输出 JSON，不要解释。"
_SCHEMA_HINT = {
    "device_model": "string",
    "serial_number": "string",
    "error_code": "string",
    "symptom": "string",
    "environment": "object",
    "attempted_steps": "array[string]",
}


@dataclass
class ExtractedFields:
    device_model: str | None = None
    serial_number: str | None = None
    error_code: str | None = None
    symptom: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    attempted_steps: list[str] = field(default_factory=list)
    field_confidence: float = 0.0
    needs_human: bool = False
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_model": self.device_model,
            "serial_number": self.serial_number,
            "error_code": self.error_code,
            "symptom": self.symptom,
            "environment": dict(self.environment),
            "attempted_steps": list(self.attempted_steps),
            "field_confidence": self.field_confidence,
            "needs_human": self.needs_human,
            "raw_text": self.raw_text,
        }


def extract_fields(
    db,
    uploads: Sequence[Any],
    *,
    ocr=None,
    llm=None,
    user_text: str = "",
) -> ExtractedFields:
    ocr = ocr if ocr is not None else get_ocr()
    llm = llm if llm is not None else get_llm()
    store = get_object_store()

    texts: list[str] = []
    confidences: list[float] = []
    needs_human = False

    for upload in uploads or ():
        object_key = _attr(upload, "object_key")
        filename = _attr(upload, "filename") or ""
        content_type = _attr(upload, "content_type") or ""
        if not object_key:
            needs_human = True
            continue
        try:
            data = store.get(object_key)
        except OSError:
            needs_human = True
            continue

        if _is_text(content_type, filename):
            texts.append(_decode(data))
            continue
        if settings.ocr_pdf_text_layer and _is_pdf(content_type, filename):
            try:
                pdf = extract_pdf_text(data)
            except ProviderError:
                needs_human = True
                continue
            if pdf.has_text_layer:
                texts.append(pdf_page_markers(pdf.pages))
                continue
            # 扫描件无文本层：回退 OCR 路径
        try:
            result = ocr.recognize(data, filename)
        except ProviderError:
            needs_human = True
            continue
        if result.text and result.text.strip():
            texts.append(result.text)
        confidences.append(float(result.confidence))

    raw_text = "\n".join(text.strip() for text in texts if text and text.strip()).strip()
    if not raw_text:
        raw_text = (user_text or "").strip()
    source_text = "\n".join(part for part in (raw_text, (user_text or "").strip()) if part)

    fields = ExtractedFields(raw_text=raw_text)
    if not source_text:
        fields.needs_human = True
        return fields

    try:
        payload = llm.generate_json(
            _build_prompt(source_text),
            system=_SYSTEM_PROMPT,
            schema_hint=_SCHEMA_HINT,
        )
    except ProviderError:
        fields.needs_human = True
        return fields
    if not isinstance(payload, dict):
        fields.needs_human = True
        return fields

    device_model, device = _resolve_model(db, payload.get("device_model"), source_text)
    fields.device_model = device_model
    fields.serial_number = _text(payload.get("serial_number"))
    fields.error_code = _error_code(payload.get("error_code")) or _error_code(source_text)
    fields.symptom = _text(payload.get("symptom"))
    fields.environment = _environment(payload.get("environment"))
    fields.attempted_steps = _steps(payload.get("attempted_steps"))

    if not device_model or device is None:
        needs_human = True

    text_confidence = sum(confidences) / len(confidences) if confidences else 1.0
    filled = sum(1 for value in (fields.device_model, fields.error_code, fields.symptom) if value)
    fields.field_confidence = round(text_confidence * (0.5 + 0.5 * filled / 3), 4)
    if fields.field_confidence < settings.min_confidence:
        needs_human = True
    fields.needs_human = fields.needs_human or needs_human
    return fields


def _attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _is_text(content_type: str, filename: str) -> bool:
    if normalize_content_type(content_type) in TEXT_CONTENT_TYPES:
        return True
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix in TEXT_SUFFIXES


def _is_pdf(content_type: str, filename: str) -> bool:
    if normalize_content_type(content_type) == PDF_CONTENT_TYPE:
        return True
    return filename.lower().endswith(PDF_SUFFIX)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _build_prompt(text: str) -> str:
    return (
        "从下面的售后故障材料中提取结构化字段，只返回 JSON。\n"
        "字段：device_model（设备完整型号）、serial_number（序列号）、"
        "error_code（故障码，如 E106）、symptom（故障现象）、"
        "environment（安装/使用环境，JSON 对象）、attempted_steps（已尝试步骤，JSON 数组）。\n"
        f"材料：\n{text}"
    )


def _resolve_model(db, raw_model: Any, text: str) -> tuple[str | None, Any]:
    candidate = _text(raw_model)
    if candidate:
        device = find_device_by_model(db, candidate)
        if device is not None:
            return device.model, device
    for match in MODEL_PATTERN.findall(text or "")[:5]:
        device = find_device_by_model(db, match)
        if device is not None:
            return device.model, device
    return candidate, None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if item is not None)
    text = str(value).strip()
    return text or None


def _error_code(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    match = ERROR_CODE_PATTERN.search(text)
    return match.group(0).upper() if match else None


def _environment(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items() if item not in (None, "")}
    text = _text(value)
    return {"notes": text} if text else {}


def _steps(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()][:20]
    text = _text(value)
    if not text:
        return []
    parts = re.split(r"[;；,，、\n]", text)
    return [part.strip() for part in parts if part.strip()][:20]