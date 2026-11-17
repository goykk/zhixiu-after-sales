"""Tesseract Provider：需要 pytesseract 与系统 tesseract 二进制。"""

from __future__ import annotations

import importlib
from typing import Any

from core.ai.base import OCRBlock, OCRResult, ProviderError


def available() -> bool:
    """pytesseract 可导入且系统二进制可调用才视为可用。"""
    try:
        importlib.import_module("pytesseract")
        import pytesseract
    except Exception:  # noqa: BLE001 - 缺包
        return False
    try:
        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 - 缺系统二进制或不可执行
        return False
    return True


class TesseractProvider:
    def __init__(self, min_confidence: float | None = None) -> None:
        if min_confidence is None:
            from services.api.app.config import settings

            min_confidence = settings.ocr_min_confidence
        self.min_confidence = float(min_confidence)

    def recognize(self, data: bytes, filename: str) -> OCRResult:
        del filename
        pytesseract = _pytesseract()
        image = _open_image(data)
        try:
            lang = _lang()
            kwargs = {"lang": lang} if lang else {}
            payload = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT, **kwargs
            )
        except Exception as exc:  # noqa: BLE001 - 二进制缺失/识别失败
            raise ProviderError("OCR_FAILED", f"tesseract 识别失败: {exc}") from exc
        return _build_result(payload, self.min_confidence)


def _pytesseract() -> Any:
    try:
        return importlib.import_module("pytesseract")
    except Exception as exc:  # noqa: BLE001 - 缺包
        raise ProviderError("OCR_UNAVAILABLE", f"pytesseract 不可用: {exc}") from exc


def _open_image(data: bytes) -> Any:
    try:
        import io

        from PIL import Image
    except Exception as exc:  # noqa: BLE001 - 解码依赖缺失
        raise ProviderError("OCR_UNAVAILABLE", f"图片解码依赖缺失: {exc}") from exc
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - 图片损坏
        raise ProviderError("OCR_FAILED", f"图片无法解码: {exc}") from exc


def _lang() -> str | None:
    # tesseract 语言包缺失会直接失败，因此仅在配置为 chi* 时显式传入
    from services.api.app.config import settings

    lang = (settings.ocr_lang or "").strip()
    return lang if lang.lower().startswith("chi") else None


def _build_result(payload: dict[str, list[Any]], min_confidence: float) -> OCRResult:
    blocks: list[OCRBlock] = []
    texts = payload.get("text") or []
    confs = payload.get("conf") or []
    for index, raw_text in enumerate(texts):
        text = str(raw_text).strip()
        if not text:
            continue
        try:
            confidence = float(confs[index]) / 100.0
        except (IndexError, TypeError, ValueError):
            continue
        if confidence < 0 or confidence < min_confidence:
            continue
        blocks.append(
            OCRBlock(
                text=text,
                confidence=round(confidence, 4),
                bbox=_bbox(payload, index),
            )
        )
    text = "\n".join(block.text for block in blocks)
    confidence = sum(block.confidence for block in blocks) / len(blocks) if blocks else 0.0
    return OCRResult(text=text, blocks=tuple(blocks), confidence=round(confidence, 4))


def _bbox(payload: dict[str, list[Any]], index: int) -> tuple[float, float, float, float] | None:
    try:
        left = float(payload["left"][index])
        top = float(payload["top"][index])
        width = float(payload["width"][index])
        height = float(payload["height"][index])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return (left, top, left + width, top + height)