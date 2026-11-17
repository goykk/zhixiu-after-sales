"""PaddleOCR Provider：可选依赖，缺失时抛 `OCR_UNAVAILABLE` 而非伪造文本。"""

from __future__ import annotations

import importlib
import importlib.util
import io
from functools import lru_cache
from typing import Any, Iterator

from core.ai.base import OCRBlock, OCRResult, ProviderError


def available() -> bool:
    """`paddleocr` 可导入才视为可用；仅 find_spec 命中不足以证明依赖完整。"""
    if importlib.util.find_spec("paddleocr") is None:
        return False
    try:
        importlib.import_module("paddleocr")
    except Exception:  # noqa: BLE001 - 依赖链缺失（numpy/paddle）同样视为不可用
        return False
    return True


class PaddleOCRProvider:
    def __init__(self, lang: str | None = None, min_confidence: float | None = None) -> None:
        # 延迟读取配置：构造阶段不触发 paddleocr 导入
        if lang is None or min_confidence is None:
            from services.api.app.config import settings

            lang = settings.ocr_lang if lang is None else lang
            min_confidence = settings.ocr_min_confidence if min_confidence is None else min_confidence
        self.lang = lang
        self.min_confidence = float(min_confidence)

    def recognize(self, data: bytes, filename: str) -> OCRResult:
        del filename
        engine = _engine(self.lang)
        image = _decode_image(data)
        try:
            raw = _invoke(engine, image)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - 引擎内部错误统一归为识别失败
            raise ProviderError("OCR_FAILED", f"paddleocr 识别失败: {exc}") from exc
        return _build_result(raw, self.min_confidence)


@lru_cache(maxsize=1)
def _engine(lang: str) -> Any:
    """复用单个 engine；初始化失败不缓存（异常不会被 lru_cache 记住），下次仍可重试。"""
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # noqa: BLE001 - 导入链缺失即不可用
        raise ProviderError("OCR_UNAVAILABLE", f"paddleocr 不可用: {exc}") from exc

    # 2.x 接受 show_log；3.x 会以 Unknown argument 拒绝。3.x 还需关闭 mkldnn，
    # 否则 CPU 推理在部分 paddle 版本上抛 ConvertPirAttribute NotImplementedError。
    attempts: tuple[dict[str, Any], ...] = (
        {"lang": lang, "use_angle_cls": True, "show_log": False},
        {"lang": lang, "use_angle_cls": True, "enable_mkldnn": False},
        {"lang": lang},
    )
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 逐个降级尝试
            last_error = exc
    raise ProviderError("OCR_UNAVAILABLE", f"PaddleOCR 初始化失败: {last_error}") from last_error


def _invoke(engine: Any, image: Any) -> Any:
    """3.x 的主入口是 `predict`；2.x 只有 `ocr`。"""
    predict = getattr(engine, "predict", None)
    if callable(predict):
        return predict(image)
    return engine.ocr(image, cls=True)


def _decode_image(data: bytes) -> Any:
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:  # noqa: BLE001 - 解码依赖缺失
        raise ProviderError("OCR_UNAVAILABLE", f"图片解码依赖缺失: {exc}") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            return np.array(image.convert("RGB"))
    except Exception as exc:  # noqa: BLE001 - 图片损坏
        raise ProviderError("OCR_FAILED", f"图片无法解码: {exc}") from exc


def _build_result(raw: Any, min_confidence: float) -> OCRResult:
    blocks: list[OCRBlock] = []
    for page in raw or ():
        for box, text, score in _iter_entries(page):
            if not text or score < min_confidence:
                continue
            blocks.append(OCRBlock(text=text, confidence=round(score, 4), bbox=_bbox(box)))
    text = "\n".join(block.text for block in blocks)
    confidence = sum(block.confidence for block in blocks) / len(blocks) if blocks else 0.0
    return OCRResult(text=text, blocks=tuple(blocks), confidence=round(confidence, 4))


def _iter_entries(page: Any) -> Iterator[tuple[Any, str, float]]:
    payload = _res_payload(page)
    if payload is not None:
        texts = payload.get("rec_texts") or ()
        scores = payload.get("rec_scores") or ()
        boxes = payload.get("rec_polys") or payload.get("dt_polys") or ()
        for index, raw_text in enumerate(texts):
            try:
                score = float(scores[index])
            except (IndexError, TypeError, ValueError):
                continue
            box = boxes[index] if index < len(boxes) else None
            yield box, str(raw_text).strip(), score
        return
    for item in _page_items(page):
        box, raw_text, score = item
        text = str(raw_text).strip()
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            continue
        yield box, text, confidence


def _res_payload(page: Any) -> dict[str, Any] | None:
    """3.x 返回 `OCRResult`，识别结果在 `.json["res"]`；也兼容裸 dict。"""
    data = getattr(page, "json", None)
    if data is None and isinstance(page, dict):
        data = page
    if not isinstance(data, dict):
        return None
    payload = data.get("res", data)
    return payload if isinstance(payload, dict) and "rec_texts" in payload else None


def _page_items(page: Any) -> list[tuple[Any, str, Any]]:
    """2.x 结构：单页 `[[bbox, (text, conf)], ...]`，兼容多层嵌套。"""
    if not page:
        return []
    if _is_block(page[0]):
        return [(item[0], item[1][0], item[1][1]) for item in page if _is_block(item)]
    items: list[tuple[Any, str, Any]] = []
    for nested in page:
        if isinstance(nested, (list, tuple)):
            items.extend(_page_items(nested))
    return items


def _is_block(item: Any) -> bool:
    return (
        isinstance(item, (list, tuple))
        and len(item) >= 2
        and isinstance(item[1], (list, tuple))
        and len(item[1]) >= 2
        and isinstance(item[1][0], str)
    )


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