"""OpenRouter chat client (OpenAI-compatible) that asks for JSON and walks a list of free models.

Free models come and go, so the job asks OpenRouter once per run which free models support JSON
output (`candidate_models`) and falls back to a known-good list when that lookup fails. A model
that is rate-limited, unavailable or replies with broken JSON is skipped for the next one. When
every model is rate-limited the free daily quota is spent: `QuotaExhausted` stops the job calling.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
# Tried first, in this order, when free and JSON-capable (checked 2026-11-14); the rest of
# today's free JSON-capable models follow. Used as-is when the model list can't be fetched.
FALLBACK_MODELS = (
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "inclusionai/ling-3.2-flash:free",
    "baidu/ernie-5.5-flash-preview:free",
)
MAX_CANDIDATES = 6
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


def free_json_models(models: list[dict[str, Any]]) -> list[str]:
    """Ids of free models that accept a JSON response format, from OpenRouter's model list."""
    out = []
    for m in models:
        params = m.get("supported_parameters") or []
        if str(m.get("id", "")).endswith(":free") and (
            "response_format" in params or "structured_outputs" in params
        ):
            out.append(m["id"])
    return out


def order_models(preferred: str | None, available: list[str] | None) -> list[str]:
    """Preferred, then the known-good list, then the other available ones; only available ones
    when the list is known."""
    ordered = dict.fromkeys(m for m in (preferred, *FALLBACK_MODELS, *(available or [])) if m)
    if available is not None:
        ordered = {m: None for m in ordered if m in set(available)}
    return list(ordered)[:MAX_CANDIDATES]


def candidate_models(preferred: str | None) -> list[str]:
    try:
        req = urllib.request.Request(MODELS_URL, headers={"Accept": "application/json"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            available = free_json_models(json.loads(resp.read().decode()).get("data") or [])
    except (OSError, ValueError) as exc:
        log.warning("could not list OpenRouter models, using the fallback list: %s", exc)
        available = None
    models = order_models(preferred, available or None)
    log.info("model candidates: %s", models)
    return models


def chat_json(
    system: str, user: str, *, api_key: str, models: list[str], max_tokens: int = 3000
) -> tuple[dict[str, Any], str]:
    """(parsed JSON reply, model that produced it), trying ``models`` in order."""
    if not api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    if not models:
        raise LLMError("no models to try")
    errors: list[str] = []
    rate_limited = 0
    for model_id in models:
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
    if rate_limited == len(models):
        raise QuotaExhausted("; ".join(errors))
    raise LLMError("; ".join(errors))
