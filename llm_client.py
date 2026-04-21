import json
import os
import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM_MESSAGE = "You are a code repository analyst. Always respond with valid JSON and nothing else."

# Optional request logging — set _log_dir to a directory path to enable
_log_dir = None
_log_counter = 0


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

    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    # Log request + response if logging is enabled
    global _log_counter
    if _log_dir:
        _log_counter += 1
        os.makedirs(_log_dir, exist_ok=True)
        log_path = os.path.join(_log_dir, f"{_log_counter:02d}_{model.replace('/', '_')}.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"=== REQUEST #{_log_counter} ===\n")
            f.write(f"Model: {model}\n\n")
            f.write("--- System ---\n")
            f.write(SYSTEM_MESSAGE + "\n\n")
            f.write("--- User prompt ---\n")
            f.write(prompt + "\n\n")
            f.write("=== RESPONSE ===\n")
            f.write(content if content else "(empty)")

    if not content.strip():
        raw_resp = str(data)[:300]
        return {"error": "llm_empty_response", "raw": raw_resp}

    # First parse attempt
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strip markdown fences and retry
    try:
        return json.loads(_strip_fences(content))
    except (json.JSONDecodeError, TypeError):
        return {"error": "llm_parse_failed", "raw": content[:500]}
