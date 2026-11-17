"""PDF 文本层提取：有文本层优先用文本，扫描件才交给 OCR。"""

from __future__ import annotations

from dataclasses import dataclass

from core.ai.base import ProviderError

MIN_TEXT_LAYER_CHARS = 20
PAGE_MARKER_TEMPLATE = "<!-- page: {page} -->"


@dataclass
class PDFText:
    text: str
    pages: list[str]
    has_text_layer: bool


def extract_pdf_text(data: bytes) -> PDFText:
    """逐页 `get_text()`；加密或损坏抛 `ProviderError("PDF_INVALID")`。"""
    fitz = _fitz()
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - 损坏或非 PDF 字节
        raise ProviderError("PDF_INVALID", f"PDF 无法解析: {exc}") from exc
    try:
        if getattr(document, "needs_pass", False):
            raise ProviderError("PDF_INVALID", "PDF 已加密，无法提取文本层")
        pages = [page.get_text() or "" for page in document]
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - 解析中途失败
        raise ProviderError("PDF_INVALID", f"PDF 文本层提取失败: {exc}") from exc
    finally:
        document.close()

    text = "\n".join(pages).strip()
    return PDFText(text=text, pages=pages, has_text_layer=len(text) >= MIN_TEXT_LAYER_CHARS)


def pdf_page_markers(pages: list[str]) -> str:
    """每页前插入 `<!-- page: N -->`（N 从 1 开始），供切片按页归属。"""
    parts: list[str] = []
    for index, content in enumerate(pages or ()):
        marker = PAGE_MARKER_TEMPLATE.format(page=index + 1)
        parts.append(f"{marker}\n{(content or '').strip()}")
    return "\n\n".join(parts)


def _fitz():
    """pymupdf 与旧别名 fitz 是同一库；优先新模块名以避免弃用告警。"""
    try:
        import pymupdf as module
    except Exception:
        try:
            import fitz as module  # type: ignore[no-redef]
        except Exception as exc:  # noqa: BLE001 - pymupdf 为可选依赖
            raise ProviderError("PDF_INVALID", f"pymupdf 不可用: {exc}") from exc
    return module