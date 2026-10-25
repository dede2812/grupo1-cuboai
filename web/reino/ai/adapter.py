"""Adaptador de proveedor de IA (OpenAI-compatible, §10).

- Clave fuera del repositorio (settings.REINO_AI desde entorno).
- Entradas y salidas tipadas; timeout configurable; sin reenviar todo el
  historial en cada turno (se acota).
- `available()` distingue honestamente el modo del asesor: con clave real el
  modo es "ai"; sin ella, "rules" (nunca se simula una respuesta del modelo).
"""

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


class ProviderUnavailable(ProviderError):
    """Sin clave o proveedor inalcanzable: el orquestador degrada con honestidad."""


def available():
    return bool(settings.REINO_AI.get("API_KEY"))


def chat(messages, tools=None):
    """Una llamada chat.completions. Devuelve el dict del primer mensaje."""
    cfg = settings.REINO_AI
    if not cfg.get("API_KEY"):
        raise ProviderUnavailable("Sin REINO_AI_API_KEY configurada.")
    base_url = cfg.get("BASE_URL", "https://api.openai.com/v1")
    endpoint = urlparse(base_url)
    if endpoint.scheme != "https" and not (endpoint.scheme == "http" and endpoint.hostname in ("localhost", "127.0.0.1", "::1")):
        raise ProviderError("invalid_provider_url")
    if len(json.dumps(messages, ensure_ascii=False)) > cfg.get("MAX_CONTEXT_CHARS", 32000):
        raise ProviderError("context_limit")
    payload = {
        "model": cfg.get("MODEL", "gpt-4o-mini"),
        "messages": messages,
        "max_completion_tokens": cfg.get("MAX_COMPLETION_TOKENS", 600),
        "store": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['API_KEY']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(cfg.get("TIMEOUT_SECONDS", 12), 30)) as resp:
            raw = resp.read(100001)
            if len(raw) > 100000:
                raise ProviderError("response_too_large")
            data = json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        logger.warning("ai_provider_http_error status=%s", exc.code)
        raise ProviderError(f"http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("ai_provider_unavailable")
        raise ProviderUnavailable("provider_unavailable") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProviderError("invalid_provider_json") from None
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("invalid_provider_response") from None
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProviderError("invalid_provider_message")
    content, calls = message.get("content"), message.get("tool_calls")
    if content is not None and not isinstance(content, str):
        raise ProviderError("invalid_provider_content")
    if calls is not None and not isinstance(calls, list):
        raise ProviderError("invalid_provider_tools")
    if calls and (len(calls) > 12 or any(
        not isinstance(call, dict) or not isinstance(call.get("id"), str)
        or not isinstance(call.get("function"), dict)
        or not isinstance(call["function"].get("name"), str)
        or not isinstance(call["function"].get("arguments", ""), str)
        for call in calls
    )):
        raise ProviderError("invalid_provider_tool_call")
    if not content and not calls:
        raise ProviderError("empty_provider_response")
    usage = data.get("usage") or {}
    if isinstance(usage, dict):
        logger.info("ai_provider_usage input_tokens=%s output_tokens=%s",
                    usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return {k: message[k] for k in ("role", "content", "tool_calls") if k in message}


def probe():
    """Prueba REAL mínima de conexión con el proveedor (AC25).

    Devuelve (ok, detalle). No registra secretos ni cuerpos completos.
    """
    cfg = settings.REINO_AI
    if not cfg.get("API_KEY"):
        return False, "Sin clave configurada."
    try:
        response = chat([{"role": "user", "content": "Respondé únicamente OK."}])
        if not response.get("content"):
            return False, "El modelo no devolvió una respuesta de texto."
        return True, f"Solicitud real de texto completada con {cfg['MODEL']}."
    except ProviderError:
        return False, "No se pudo completar una solicitud real al modelo configurado."
