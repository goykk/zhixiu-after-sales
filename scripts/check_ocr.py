"""检查 OCR provider：打印实际使用的 provider、耗时、置信度与识别文本。"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ai.base import OCRBlock, OCRProvider, OCRResult, ProviderError  # noqa: E402
from scripts.make_ocr_sample import make_sample  # noqa: E402

DEFAULT_IMAGE = ROOT / "data" / "ocr_samples" / "sample.png"
PROVIDERS: tuple[str, ...] = ("mock", "rapid", "paddle", "tesseract")
# 未指定 provider 时按真实能力优先、Mock 兜底依次挑选
AUTO_ORDER: tuple[str, ...] = ("paddle", "rapid", "tesseract", "mock")
PREVIEW_CHARS = 200

PROVIDER_MODULES: dict[str, tuple[str, str]] = {
    "rapid": ("core.ai.ocr_rapid", "RapidOCRProvider"),
    "paddle": ("core.ai.ocr_paddle", "PaddleOCRProvider"),
    "tesseract": ("core.ai.ocr_tesseract", "TesseractProvider"),
}


def load_provider(name: str) -> tuple[OCRProvider | None, str]:
    """返回 (provider 实例, 不可用原因)。Mock 恒定可用。"""
    if name == "mock":
        from core.ai.mock import MockOCR

        return MockOCR(), ""

    module_path, class_name = PROVIDER_MODULES[name]
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        return None, f"缺少模块 {module_path}：{exc}"

    provider_cls = getattr(module, class_name, None)
    if provider_cls is None:
        return None, f"{module_path} 未提供 {class_name}"
    try:
        if not module.available():
            return None, f"{name} 依赖或二进制未就绪"
    except Exception as exc:  # noqa: BLE001 - 可用性探测自身的异常一律视为不可用
        return None, f"可用性检查失败：{exc}"
    try:
        return provider_cls(), ""
    except ProviderError as exc:
        return None, f"{exc.code}: {exc.message}"
    except Exception as exc:  # noqa: BLE001 - 构造期异常统一视为不可用
        return None, f"初始化失败：{type(exc).__name__}: {exc}"


def recognize(name: str, data: bytes, filename: str) -> tuple[OCRResult | None, str]:
    """返回 (识别结果, 失败原因)。"""
    provider, reason = load_provider(name)
    if provider is None:
        return None, reason
    try:
        return provider.recognize(data, filename), ""
    except ProviderError as exc:
        return None, f"{exc.code}: {exc.message}"
    except Exception as exc:  # noqa: BLE001 - 检查脚本需报告任意失败而非中断
        return None, f"{type(exc).__name__}: {exc}"


def _same_line(previous: OCRBlock, current: OCRBlock) -> bool:
    previous_center = (previous.bbox[1] + previous.bbox[3]) / 2
    current_center = (current.bbox[1] + current.bbox[3]) / 2
    previous_height = max(previous.bbox[3] - previous.bbox[1], 1.0)
    current_height = max(current.bbox[3] - current.bbox[1], 1.0)
    return abs(current_center - previous_center) <= 0.5 * max(previous_height, current_height)


def readable_text(result: OCRResult) -> str:
    """同一水平线上的块用空格拼接，不同行用换行；缺 bbox 时退回 block 顺序拼接。"""
    if any(block.bbox is None for block in result.blocks):
        return result.text

    lines: list[list[OCRBlock]] = []
    for block in sorted(result.blocks, key=lambda item: (item.bbox[1], item.bbox[0])):
        if lines and _same_line(lines[-1][-1], block):
            lines[-1].append(block)
        else:
            lines.append([block])

    merged = []
    for line in lines:
        ordered = sorted(line, key=lambda item: item.bbox[0])
        merged.append(" ".join(block.text for block in ordered))
    return "\n".join(merged)


def _pick_and_recognize(
    requested: str | None, data: bytes, filename: str
) -> tuple[str, OCRResult | None, str, int]:
    """返回 (实际 provider, 结果, 失败原因, 耗时毫秒)。"""
    candidates = (requested,) if requested is not None else AUTO_ORDER
    name = candidates[-1]
    reason = "无可用 provider"
    for candidate in candidates:
        started = time.perf_counter()
        result, failure = recognize(candidate, data, filename)
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        if result is not None:
            return candidate, result, "", elapsed_ms
        name, reason = candidate, failure
        # 自动挑选时逐个试到能真正识别为止，显式指定时只试一次
        if requested is None:
            print(f"跳过 provider={candidate}：{failure}", file=sys.stderr)
    return name, None, reason, elapsed_ms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 OCR provider 可用性与识别效果")
    parser.add_argument("--provider", choices=PROVIDERS, help="指定 provider；缺省自动挑选可识别者")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE), help="待识别图片路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    image = Path(args.image)
    if not image.is_file():
        make_sample(image)
    data = image.read_bytes()

    name, result, reason, elapsed_ms = _pick_and_recognize(args.provider, data, image.name)
    available = result is not None
    confidence = result.confidence if result is not None else 0.0
    text = readable_text(result) if result is not None else ""
    payload = {
        "provider": name,
        "available": available,
        "elapsed_ms": elapsed_ms,
        "confidence": confidence,
        "text": text,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"provider={name} available={available} elapsed_ms={elapsed_ms} confidence={confidence:.3f}")
        print(f"识别文本前 {PREVIEW_CHARS} 字符：")
        print(text[:PREVIEW_CHARS])

    if not available:
        print(f"OCR_UNAVAILABLE provider={name}：{reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())