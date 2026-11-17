"""手册正文切片：按页码标记、标题层级切块并滑窗重叠。"""

from __future__ import annotations

import re
from dataclasses import dataclass

PAGE_MARKER_RE = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_BREAKERS = ("\n\n", "\n", "。", "！", "？", ". ", " ")


@dataclass(frozen=True)
class ChunkDraft:
    page: int
    section: str
    content: str


def chunk_markdown(text: str, *, max_chars: int = 800, overlap: int = 80) -> list[ChunkDraft]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not text or not text.strip():
        return []
    overlap = max(0, min(overlap, max_chars - 1))

    drafts: list[ChunkDraft] = []

    for block, block_page, block_section in _split_blocks(text):
        drafts.extend(_window(block, block_page, block_section, max_chars, overlap))
    return drafts


def _take_buffer(buffer: list[str]) -> str:
    block = "\n".join(buffer).strip()
    buffer.clear()
    return block


def _split_blocks(text: str) -> list[tuple[str, int, str]]:
    blocks: list[tuple[str, int, str]] = []
    buffer: list[str] = []
    page, section = 1, ""
    for line in text.splitlines():
        marker = PAGE_MARKER_RE.search(line)
        if marker is not None:
            block = _take_buffer(buffer)
            if block:
                blocks.append((block, page, section))
            page = int(marker.group(1))
            continue
        heading = HEADING_RE.match(line.strip())
        if heading is not None:
            block = _take_buffer(buffer)
            if block:
                blocks.append((block, page, section))
            section = heading.group(1).strip()
            continue
        buffer.append(line)
    block = _take_buffer(buffer)
    if block:
        blocks.append((block, page, section))
    return blocks


def _window(block: str, page: int, section: str, max_chars: int, overlap: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    start, length = 0, len(block)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            end = _break_point(block, start, end)
        piece = block[start:end].strip()
        if piece:
            drafts.append(ChunkDraft(page=page, section=section, content=piece))
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return drafts


def _break_point(text: str, start: int, end: int) -> int:
    floor = start + max(1, (end - start) // 2)
    for breaker in _BREAKERS:
        index = text.rfind(breaker, floor, end)
        if index != -1:
            return index + len(breaker)
    return end