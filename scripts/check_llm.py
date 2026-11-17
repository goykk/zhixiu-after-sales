"""校验本地 Ollama 是否就绪：模型是否已拉取、能否完成一次生成。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx  # noqa: E402

from core.ai.base import ProviderError  # noqa: E402
from core.ai.ollama import OllamaLLM  # noqa: E402
from services.api.app.config import settings  # noqa: E402


def _model_names(tags: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    models = tags.get("models")
    if not isinstance(models, list):
        return names
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if isinstance(name, str):
            names.add(name)
    return names


def _model_available(target: str, names: set[str]) -> bool:
    if target in names:
        return True
    base = target.split(":", 1)[0]
    return any(name.split(":", 1)[0] == base for name in names)


def main() -> int:
    base_url = settings.ollama_base_url.rstrip("/")
    model = settings.ollama_model
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=10.0)
        response.raise_for_status()
        tags = response.json()
    except httpx.HTTPError as exc:
        print(f"无法连接 Ollama ({base_url})：{exc}", file=sys.stderr)
        print("请确认已启动 Ollama 服务后重试。", file=sys.stderr)
        return 1

    if not isinstance(tags, dict) or not _model_available(model, _model_names(tags)):
        print(f"模型 {model} 不存在。请执行：ollama pull {model}")
        return 1

    llm = OllamaLLM(base_url=base_url, model=model)
    try:
        output = llm.generate("请用一句话说明你已就绪。", max_tokens=64)
    except ProviderError as exc:
        print(f"模型试跑失败 [{exc.code}]：{exc.message}", file=sys.stderr)
        return 1
    print(f"模型 {model} 可用。试跑输出前 200 字符：")
    print(output[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())