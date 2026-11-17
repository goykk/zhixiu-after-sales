"""检索结果重排：0.7 × 向量相关度 + 0.3 × 关键词命中率。"""

from __future__ import annotations

import copy
import dataclasses
import re
from typing import Any, Iterable

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*|[\u4e00-\u9fff]+")
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def keyword_score(query: str, text: str) -> float:
    tokens = _tokens(query)
    if not tokens:
        return 0.0
    haystack = (text or "").lower()
    hits = sum(1 for token in tokens if token in haystack)
    return hits / len(tokens)


def rerank(query: str, items: Iterable[Any], top_k: int = 5) -> list[Any]:
    scored: list[tuple[float, Any]] = []
    for item in items:
        relevance = float(getattr(item, "relevance_score", 0.0) or 0.0)
        quote = str(getattr(item, "quote", getattr(item, "content", "")) or "")
        final = VECTOR_WEIGHT * relevance + KEYWORD_WEIGHT * keyword_score(query, quote)
        scored.append((final, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_with_score(item, score) for score, item in scored[: max(top_k, 0)]]


def _with_score(item: Any, score: float) -> Any:
    if dataclasses.is_dataclass(item):
        return dataclasses.replace(item, relevance_score=score)
    if isinstance(item, dict):
        updated = dict(item)
        updated["relevance_score"] = score
        return updated
    updated = copy.copy(item)
    setattr(updated, "relevance_score", score)
    return updated