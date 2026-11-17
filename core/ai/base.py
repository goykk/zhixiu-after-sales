"""Provider 协议与公共数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """Provider 调用失败；消费者必须显式处理，不得伪造成功。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OCRBlock:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class OCRResult:
    text: str
    blocks: tuple[OCRBlock, ...]
    confidence: float


@runtime_checkable
class LLMProvider(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
    ) -> str: ...

    def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_hint: str | None = None,
    ) -> dict[str, Any]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class OCRProvider(Protocol):
    def recognize(self, data: bytes, filename: str) -> OCRResult: ...