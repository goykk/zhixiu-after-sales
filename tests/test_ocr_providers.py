"""T46: OCR provider、PDF 文本层与 factory 回退测试（契约 C-TEST-OCR@1）。

覆盖：factory 按 `settings.ocr_provider` 选择与不可用回退追踪、真实 provider 的
不可用错误语义与可选真实识别（未安装时 skip）、PDF 文本层/扫描件判定、
`extract_fields` 的 PDF 文本层优先与 OCR 回退、MockOCR 行为不变。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.ai.base import OCRBlock, OCRResult, ProviderError
from core.ai.mock import MockOCR
from services.api.app.config import settings

_SAMPLE_PATH = Path("data/ocr_samples/sample.png")

_PROVIDER_MODULES = {
    "paddle": "core.ai.ocr_paddle",
    "tesseract": "core.ai.ocr_tesseract",
    "rapid": "core.ai.ocr_rapid",
}


@pytest.fixture(autouse=True)
def _reset_ocr_cache():
    """`get_ocr` 带 lru_cache；逐例切换 provider 前后都需清空，避免串味。"""
    from core.ai.factory import get_ocr

    clear = getattr(get_ocr, "cache_clear", lambda: None)
    clear()
    yield
    clear()


def _trace_events(trace_dir: Path, event: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(trace_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("event") == event:
                events.append(record)
    return events


def _probe_available(module_name: str) -> bool:
    """模块缺失或探测异常一律视为不可用，便于真实识别用例统一 skip。"""
    try:
        module = __import__(module_name, fromlist=["available"])
    except ImportError:
        return False
    try:
        return bool(module.available())
    except Exception:  # noqa: BLE001 - 探测失败等价于不可用
        return False


_PADDLE_AVAILABLE = _probe_available(_PROVIDER_MODULES["paddle"])
_TESSERACT_AVAILABLE = _probe_available(_PROVIDER_MODULES["tesseract"])
_RAPID_AVAILABLE = _probe_available(_PROVIDER_MODULES["rapid"])


def _force_unavailable(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    """同时覆盖「模块调用」与「函数导入」两种 factory 引用方式。"""

    def _unavailable() -> bool:
        return False

    from core.ai import factory

    original = module.available
    for name, value in list(vars(factory).items()):
        if value is original:
            monkeypatch.setattr(factory, name, _unavailable)
    monkeypatch.setattr(module, "available", _unavailable)


def _load_cjk_font(size: int):
    from PIL import ImageFont

    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return None


def _ensure_sample_png() -> Path:
    """优先使用 C-OCR-TOOL@1 生成的样例；缺失时按同一文案自行渲染。"""
    if _SAMPLE_PATH.is_file():
        return _SAMPLE_PATH

    from PIL import Image, ImageDraw, ImageFont

    _SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    font = _load_cjk_font(32)
    if font is not None:
        lines = ("型号 AuroraHome AC-Pro 1200", "故障码 E106")
    else:
        try:
            font = ImageFont.load_default(size=32)
        except TypeError:  # 旧版 Pillow 不支持 size 参数
            font = ImageFont.load_default()
        lines = ("Model AuroraHome AC-Pro 1200", "Code E106")

    image = Image.new("RGB", (860, 260), "white")
    draw = ImageDraw.Draw(image)
    y = 40
    for line in lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 110
    image.save(_SAMPLE_PATH)
    return _SAMPLE_PATH


def _pymupdf():
    try:
        import pymupdf
    except ImportError:  # PyMuPDF 旧版本只暴露 fitz
        import fitz as pymupdf
    return pymupdf


def _pdf_with_text() -> bytes:
    fitz = _pymupdf()
    doc = fitz.open()
    first = doc.new_page()
    first.insert_text((72, 72), "AuroraHome AC-Pro 1200", fontsize=16)
    first.insert_text((72, 100), "Fault code E106: fan blocked", fontsize=16)
    second = doc.new_page()
    second.insert_text((72, 72), "Second page maintenance note", fontsize=16)
    data = doc.tobytes()
    doc.close()
    return data


def _blank_pdf() -> bytes:
    fitz = _pymupdf()
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def _store_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    filename: str = "case.pdf",
) -> dict[str, Any]:
    from core.storage import get_object_store

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    stored = get_object_store().put(data, filename, "application/pdf")
    return {
        "object_key": stored.object_key,
        "filename": filename,
        "content_type": "application/pdf",
    }


class _RecordingOCR:
    """记录调用次数；用于断言文本层 PDF 不触发 OCR。"""

    def __init__(
        self,
        result: OCRResult | None = None,
        error: ProviderError | None = None,
    ) -> None:
        self.calls = 0
        self._result = result
        self._error = error

    def recognize(self, data: bytes, filename: str) -> OCRResult:
        del data, filename
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


# ---------------------------------------------------------------------------
# factory：选择与回退追踪
# ---------------------------------------------------------------------------


def test_factory_returns_mock_for_mock_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ocr_provider", "mock")
    monkeypatch.setattr(settings, "trace_dir", str(tmp_path))

    from core.ai.factory import get_ocr

    assert isinstance(get_ocr(), MockOCR)
    assert not _trace_events(tmp_path, "ocr_provider_fallback")


@pytest.mark.parametrize("provider", ["paddle", "tesseract", "rapid"])
def test_factory_falls_back_to_mock_when_provider_unavailable(
    provider, monkeypatch, tmp_path
):
    module = pytest.importorskip(
        _PROVIDER_MODULES[provider], reason=f"{provider} provider 尚未提供"
    )
    monkeypatch.setattr(settings, "ocr_provider", provider)
    monkeypatch.setattr(settings, "trace_dir", str(tmp_path))
    _force_unavailable(monkeypatch, module)

    from core.ai.factory import get_ocr

    assert isinstance(get_ocr(), MockOCR)
    events = _trace_events(tmp_path, "ocr_provider_fallback")
    assert events, f"{provider} 不可用时回退 Mock 必须产生 ocr_provider_fallback 追踪"
    assert events[-1]["fields"]["requested"] == provider
    assert events[-1]["fields"].get("reason")


# ---------------------------------------------------------------------------
# 真实 provider：不可用错误语义 + 可选真实识别
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_PADDLE_AVAILABLE, reason="paddleocr 已安装，走真实识别用例")
def test_paddle_provider_raises_ocr_unavailable():
    from core.ai.ocr_paddle import PaddleOCRProvider

    with pytest.raises(ProviderError) as excinfo:
        PaddleOCRProvider().recognize(b"not-an-image", "sample.png")
    assert excinfo.value.code == "OCR_UNAVAILABLE"


@pytest.mark.skipif(not _PADDLE_AVAILABLE, reason="paddleocr 不可用，跳过真实识别")
def test_paddle_provider_recognizes_sample_image():
    """paddleocr 已安装但引擎初始化失败（如版本参数不兼容）时按不可用 skip。"""
    from core.ai.ocr_paddle import PaddleOCRProvider

    sample = _ensure_sample_png()
    try:
        result = PaddleOCRProvider().recognize(sample.read_bytes(), sample.name)
    except ProviderError as exc:
        if exc.code == "OCR_UNAVAILABLE":
            pytest.skip(f"PaddleOCR 引擎不可用：{exc.message}")
        raise

    assert "AC-Pro 1200" in result.text or "E106" in result.text.upper()


@pytest.mark.skipif(_TESSERACT_AVAILABLE, reason="tesseract 可用，无需验证缺失语义")
def test_tesseract_provider_raises_ocr_unavailable():
    from core.ai.ocr_tesseract import TesseractProvider

    with pytest.raises(ProviderError) as excinfo:
        TesseractProvider().recognize(b"not-an-image", "sample.png")
    assert excinfo.value.code == "OCR_UNAVAILABLE"


@pytest.mark.skipif(_RAPID_AVAILABLE, reason="rapidocr 已安装，走真实识别用例")
def test_rapid_provider_raises_ocr_unavailable():
    ocr_rapid = pytest.importorskip(
        _PROVIDER_MODULES["rapid"], reason="rapid provider 尚未提供"
    )

    with pytest.raises(ProviderError) as excinfo:
        ocr_rapid.RapidOCRProvider().recognize(b"not-an-image", "sample.png")
    assert excinfo.value.code == "OCR_UNAVAILABLE"


@pytest.mark.skipif(not _RAPID_AVAILABLE, reason="rapidocr 不可用，跳过真实识别")
def test_rapid_provider_recognizes_sample_image():
    from core.ai.ocr_rapid import RapidOCRProvider

    sample = _ensure_sample_png()
    result = RapidOCRProvider().recognize(sample.read_bytes(), sample.name)

    assert "AC-Pro 1200" in result.text or "E106" in result.text.upper()


# ---------------------------------------------------------------------------
# PDF 文本层与页码标记
# ---------------------------------------------------------------------------


def test_extract_pdf_text_detects_text_layer():
    from core.multimodal.pdf import extract_pdf_text

    pdf = extract_pdf_text(_pdf_with_text())

    assert pdf.has_text_layer is True
    assert "AC-Pro 1200" in pdf.text
    assert "E106" in pdf.text
    assert len(pdf.pages) == 2
    assert pdf.pages[0].strip() and pdf.pages[1].strip()


def test_extract_pdf_text_blank_pdf_has_no_text_layer():
    from core.multimodal.pdf import extract_pdf_text

    pdf = extract_pdf_text(_blank_pdf())

    assert pdf.has_text_layer is False
    assert len(pdf.pages) == 2
    assert all(not page.strip() for page in pdf.pages)


def test_pdf_page_markers_prefix_each_page():
    from core.multimodal.pdf import pdf_page_markers

    marked = pdf_page_markers(["first", "second"])

    assert "<!-- page: 1 -->" in marked
    assert "<!-- page: 2 -->" in marked
    assert marked.index("<!-- page: 1 -->") < marked.index("first")
    assert marked.index("first") < marked.index("<!-- page: 2 -->") < marked.index("second")


# ---------------------------------------------------------------------------
# extract_fields：PDF 文本层优先 / 扫描件回退 OCR
# ---------------------------------------------------------------------------


def test_extract_fields_uses_pdf_text_layer_without_ocr(
    db, seed_base, monkeypatch, tmp_path
):
    from core.ai.mock import MockLLM
    from core.multimodal.extract import extract_fields

    upload = _store_upload(tmp_path, monkeypatch, _pdf_with_text())
    ocr = _RecordingOCR(error=ProviderError("OCR_FAILED", "文本层 PDF 不应调用 OCR"))

    fields = extract_fields(db, [upload], ocr=ocr, llm=MockLLM())

    assert ocr.calls == 0
    assert fields.device_model == "AC-Pro 1200"
    assert fields.error_code == "E106"
    assert fields.needs_human is False
    assert "AC-Pro 1200" in fields.raw_text


def test_extract_fields_falls_back_to_ocr_when_pdf_has_no_text_layer(
    db, seed_base, monkeypatch, tmp_path
):
    from core.ai.mock import MockLLM
    from core.multimodal.extract import extract_fields

    upload = _store_upload(tmp_path, monkeypatch, _blank_pdf())
    recognized = OCRResult(
        text="型号 AuroraHome AC-Pro 1200 故障码 E106",
        blocks=(OCRBlock(text="型号 AuroraHome AC-Pro 1200 故障码 E106", confidence=0.9),),
        confidence=0.9,
    )
    ocr = _RecordingOCR(result=recognized)

    fields = extract_fields(db, [upload], ocr=ocr, llm=MockLLM())

    assert ocr.calls == 1
    assert fields.device_model == "AC-Pro 1200"
    assert fields.error_code == "E106"


# ---------------------------------------------------------------------------
# MockOCR 行为不变
# ---------------------------------------------------------------------------


def test_mock_ocr_remains_deterministic():
    ocr = MockOCR()

    first = ocr.recognize(b"", "AuroraHome AC-Pro 1200.png")
    second = ocr.recognize(b"\x00\x01\x02", "AuroraHome AC-Pro 1200.png")

    assert first == second
    assert "AC-Pro 1200" in first.text
    assert first.confidence == 0.95


def test_mock_ocr_blurry_and_unknown_filenames():
    ocr = MockOCR()

    blurry = ocr.recognize(b"", "blurry AC-Pro 1200 photo.png")
    unknown = ocr.recognize(b"", "photo.png")

    assert blurry.confidence == 0.4
    assert "AC-Pro 1200" in blurry.text
    assert unknown.text == ""
    assert unknown.confidence == 0.2