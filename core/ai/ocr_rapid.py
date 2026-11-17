"""RapidOCR Provider：PaddleOCR PP-OCR 的 ONNX 实现，Python 3.13 下可直接安装。"""

from __future__ import annotations

import importlib
import importlib.util
from functools import lru_cache
from typing import Any

from core.ai.base import OCRBlock, OCRResult, ProviderError


def available() -> bool:
    """`rapidocr_onnxruntime` 与 `numpy` 都可导入才视为可用。"""
    for module in ("rapidocr_onnxruntime", "numpy"):
        if importlib.util.find_spec(module) is None:
            return False
    try:
        importlib.import_module("rapidocr_onnxruntime")
        importlib.import_module("numpy")
    except Exception:  # noqa: BLE001 - 依赖链缺失视为不可用
        return False
    return True


class RapidOCRProvider:
    def __init__(self, min_confidence: float | None = None) -> None:
        if min_confidence is None:
            from services.api.app.config import settings

            min_confidence = settings.ocr_min_confidence
        self.min_confidence = float(min_confidence)

    def recognize(self, data: bytes, filename: str) -> OCRResult:
        del filename
        engine = _engine()
        image = _decode_image(data)
        try:
            raw = engine(image)
        except Exception as exc:  # noqa: BLE001 - 引擎内部错误统一归为识别失败
            raise ProviderError("OCR_FAILED", f"rapidocr 识别失败: {exc}") from exc
        # RapidOCR 返回 (result, elapsed)；result 为 None 表示未检出文本
        result = raw[0] if isinstance(raw, tuple) else raw
        return _build_result(result, self.min_confidence)


@lru_cache(maxsize=1)
def _engine() -> Any:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:  # noqa: BLE001 - 导入链缺失
        raise ProviderError("OCR_UNAVAILABLE", f"rapidocr_onnxruntime 不可用: {exc}") from exc
    try:
        return RapidOCR()
    except Exception as exc:  # noqa: BLE001 - 模型加载失败
        raise ProviderError("OCR_UNAVAILABLE", f"RapidOCR 初始化失败: {exc}") from exc


def _decode_image(data: bytes) -> Any:
    try:
        import io

        import numpy as np
        from PIL import Image
    except Exception as exc:  # noqa: BLE001 - 解码依赖缺失
        raise ProviderError("OCR_UNAVAILABLE", f"图片解码依赖缺失: {exc}") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            return np.array(image.convert("RGB"))
    except Exception as exc:  # noqa: BLE001 - 图片损坏
        raise ProviderError("OCR_FAILED", f"图片无法解码: {exc}") from exc


def _build_result(result: Any, min_confidence: float) -> OCRResult:
    blocks: list[OCRBlock] = []
    for item in result or ():
        block = _to_block(item, min_confidence)
        if block is not None:
            blocks.append(block)
    text = "\n".join(block.text for block in blocks)
    confidence = sum(block.confidence for block in blocks) / len(blocks) if blocks else 0.0
    return OCRResult(text=text, blocks=tuple(blocks), confidence=round(confidence, 4))


def _to_block(item: Any, min_confidence: float) -> OCRBlock | None:
    """RapidOCR 单条结果为 `[box, text, score]`。"""
    if not isinstance(item, (list, tuple)) or len(item) < 3:
        return None
    box, raw_text, raw_score = item[0], item[1], item[2]
    text = str(raw_text).strip()
    try:
        confidence = float(raw_score)
    except (TypeError, ValueError):
        return None
    if not text or confidence < min_confidence:
        return None
    return OCRBlock(text=text, confidence=round(confidence, 4), bbox=_bbox(box))


def _bbox(box: Any) -> tuple[float, float, float, float] | None:
    try:
        points = [(float(point[0]), float(point[1])) for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))