import json
from typing import Any

import requests

_URL = "https://openrouter.ai/api/v1/chat/completions"
_SYSTEM = "You are a code repository analyst. Always respond with valid JSON and nothing else."


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        return "\n".join(inner).strip()
    return text


def _post(messages: list[dict[str, str]], key: str, model: str) -> str:
    resp = requests.post(
        _URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_llm_chat(messages: list[dict[str, str]], key: str, model: str) -> str:
    """Multi-turn call. Returns raw content string (not parsed)."""
    return _post(messages, key, model)


def call_llm(prompt: str, key: str, model: str) -> dict:
    content = _post(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        key,
        model,
    )

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    try:
        return json.loads(_strip_fences(content))
    except json.JSONDecodeError:
        return {"error": "llm_parse_failed", "raw": content[:500]}