"""Provider 工厂：按配置选择 Ollama / 真实 OCR 或确定性 Mock。"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable

from core.ai import ocr_paddle, ocr_rapid, ocr_tesseract
from core.ai.base import EmbeddingProvider, LLMProvider, OCRProvider
from core.ai.mock import MockEmbedder, MockLLM, MockOCR
from core.ai.ollama import OllamaEmbedder, OllamaLLM
from core.observability.tracer import get_tracer
from services.api.app.config import settings


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    if settings.ai_provider.lower() == "ollama":
        return OllamaLLM()
    return MockLLM()


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingProvider:
    if settings.ai_provider.lower() == "ollama" and settings.ollama_embedding_model:
        return OllamaEmbedder(
            settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            dim=settings.embedding_dim,
            timeout=settings.ollama_timeout,
        )
    return MockEmbedder(settings.embedding_dim)


@lru_cache(maxsize=1)
def get_ocr() -> OCRProvider:
    requested = (settings.ocr_provider or "").strip().lower()
    builder = _OCR_BUILDERS.get(requested)
    if builder is None:
        return MockOCR()
    provider, reason = builder()
    if provider is not None:
        return provider
    _emit_fallback(requested, reason)
    return MockOCR()



def _build_paddle() -> tuple[OCRProvider | None, str]:
    if not ocr_paddle.available():
        return None, "paddleocr 未安装或不可导入"
    try:
        return ocr_paddle.PaddleOCRProvider(), ""
    except Exception as exc:  # noqa: BLE001 - 构造失败同样回退
        return None, f"PaddleOCRProvider 构造失败: {exc}"


def _build_tesseract() -> tuple[OCRProvider | None, str]:
    if not ocr_tesseract.available():
        return None, "pytesseract 或 tesseract 二进制不可用"
    try:
        return ocr_tesseract.TesseractProvider(), ""
    except Exception as exc:  # noqa: BLE001 - 构造失败同样回退
        return None, f"TesseractProvider 构造失败: {exc}"


def _build_rapid() -> tuple[OCRProvider | None, str]:
    if not ocr_rapid.available():
        return None, "rapidocr_onnxruntime 未安装或不可导入"
    try:
        return ocr_rapid.RapidOCRProvider(), ""
    except Exception as exc:  # noqa: BLE001 - 构造失败同样回退
        return None, f"RapidOCRProvider 构造失败: {exc}"


_OCR_BUILDERS: dict[str, Callable[[], tuple[OCRProvider | None, str]]] = {
    "paddle": _build_paddle,
    "tesseract": _build_tesseract,
    "rapid": _build_rapid,
}


def _emit_fallback(requested: str, reason: str) -> None:
    # 追踪失败不能影响业务主流程
    try:
        get_tracer().emit("ocr_provider_fallback", requested=requested, reason=reason)
    except Exception:  # noqa: BLE001
        pass