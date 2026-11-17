"""Ollama 原生 HTTP 客户端。"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from core.ai.base import ProviderError
from services.api.app.config import settings

_JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _normalize(vector: list[float], dim: int) -> list[float]:
    if dim <= 0:
        raise ProviderError("EMBEDDING_BAD_DIM", f"embedding dim must be positive, got {dim}")
    values = [float(value) for value in vector[:dim]]
    if len(values) < dim:
        values.extend([0.0] * (dim - len(values)))
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0.0:
        return values
    return [value / norm for value in values]


class _OllamaClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("MODEL_TIMEOUT", f"ollama request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("MODEL_UNAVAILABLE", f"ollama request failed: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("MODEL_BAD_RESPONSE", "ollama returned non-json response") from exc
        if not isinstance(data, dict):
            raise ProviderError("MODEL_BAD_RESPONSE", "ollama returned unexpected payload")
        return data


class OllamaLLM:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.model = model or settings.ollama_model
        self._client = _OllamaClient(
            base_url or settings.ollama_base_url,
            timeout if timeout is not None else settings.ollama_timeout,
        )

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 512,
    ) -> str:
        return self._chat(prompt, system=system, max_tokens=max_tokens, json_mode=False)

    def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_hint: str | None = None,
    ) -> dict[str, Any]:
        if schema_hint:
            hint = f"仅输出 JSON，字段提示：{schema_hint}"
            system = f"{system}\n{hint}" if system else hint
        content = self._chat(prompt, system=system, max_tokens=1024, json_mode=True)
        return _parse_json_object(content)

    def _chat(
        self,
        prompt: str,
        *,
        system: str | None,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        data = self._client.post("/api/chat", payload)
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError("MODEL_BAD_RESPONSE", "ollama response missing message.content")
        return content


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        model: str | None = None,
        dim: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.model = model or settings.ollama_embedding_model
        self.dim = dim if dim is not None else settings.embedding_dim
        self._client = _OllamaClient(
            base_url or settings.ollama_base_url,
            timeout if timeout is not None else settings.ollama_timeout,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        data = self._client.post("/api/embeddings", {"model": self.model, "prompt": text})
        embedding = data.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise ProviderError("MODEL_BAD_RESPONSE", "ollama response missing embedding")
        return _normalize(embedding, self.dim)


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = _FENCE_PATTERN.sub("", content).strip()
    for candidate in (stripped, _first_json_block(stripped)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ProviderError("MODEL_INVALID_JSON", "ollama response is not a valid json object")


def _first_json_block(text: str) -> str:
    match = _JSON_BLOCK_PATTERN.search(text)
    return match.group(0) if match else ""