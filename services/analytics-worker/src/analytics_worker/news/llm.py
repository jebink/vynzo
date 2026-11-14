"""OpenRouter chat client (OpenAI-compatible) that asks for JSON and walks a list of free models.

A model that is rate-limited or unavailable is skipped for the next one. When every model is
rate-limited the free daily quota is spent: `QuotaExhausted` tells the job to stop calling.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FALLBACK_MODELS = (
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "liquid/lfm-2.5-2.6b:free",
)
SKIP_STATUSES = {404, 408, 429, 500, 502, 503}
TIMEOUT_S = 120


class LLMError(RuntimeError):
    """No model returned usable JSON."""


class QuotaExhausted(LLMError):
    """Every model answered 429: the free quota is spent for today."""


def extract_json(text: str) -> dict[str, Any]:
    """The JSON object in a reply, tolerating ``` fences or prose around it."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError(f"no JSON object in reply: {text[:200]!r}") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise LLMError("reply JSON is not an object")
    return parsed


def _message_text(body: dict[str, Any]) -> str:
    message = ((body.get("choices") or [{}])[0]).get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return content if isinstance(content, str) else ""


def models_to_try(preferred: str | None) -> list[str]:
    return list(dict.fromkeys(m for m in (preferred, *FALLBACK_MODELS) if m))


def chat_json(
    system: str, user: str, *, api_key: str, model: str | None = None, max_tokens: int = 3000
) -> tuple[dict[str, Any], str]:
    """(parsed JSON reply, model that produced it)."""
    if not api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    errors: list[str] = []
    rate_limited = 0
    candidates = models_to_try(model)
    for model_id in candidates:
        payload = {
            "model": model_id,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(  # noqa: S310 - fixed https URL
            OPENROUTER_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Title": "VYNZO news sentiment",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310
                body = json.loads(resp.read().decode())
            return extract_json(_message_text(body)), model_id
        except urllib.error.HTTPError as exc:
            errors.append(f"{model_id}: HTTP {exc.code}")
            rate_limited += exc.code == 429
            if exc.code not in SKIP_STATUSES:
                raise LLMError("; ".join(errors)) from exc
        except (LLMError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
            errors.append(f"{model_id}: {exc}")
        log.warning("model %s failed: %s", model_id, errors[-1])
    if rate_limited == len(candidates):
        raise QuotaExhausted("; ".join(errors))
    raise LLMError("; ".join(errors))
