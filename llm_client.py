import json
import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM_MESSAGE = "You are a code repository analyst. Always respond with valid JSON and nothing else."


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first line (```json or ```) and last line (```)
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text


def call_llm(prompt: str, key: str, model: str) -> dict:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
    }

    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    # First parse attempt
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences and retry
    try:
        return json.loads(_strip_fences(content))
    except json.JSONDecodeError:
        return {"error": "llm_parse_failed", "raw": content[:500]}
