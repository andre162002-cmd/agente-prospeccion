"""Acceso a Claude con salida JSON validada por esquema.

Si no hay credenciales de Anthropic, `LLM.available` es False y cada módulo
usa su versión basada en reglas (nunca se inventan datos en ningún caso).
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, enabled: bool, model: str, effort: str = "medium"):
        self.model = model
        self.effort = effort
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._client = None
        self._use_fallbacks = True
        if enabled and anthropic is not None:
            try:
                self._client = anthropic.Anthropic(max_retries=3)
            except Exception as exc:  # credenciales ausentes o inválidas
                log.warning("Claude no disponible: %s", exc)
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def json(self, system: str, prompt: str, schema: dict[str, Any], *, effort: str | None = None,
             max_tokens: int = 16000) -> dict[str, Any]:
        if not self._client:
            raise LLMError("Claude no está configurado")
        params: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort or self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if self._use_fallbacks:
                try:
                    resp = self._client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
                except anthropic.BadRequestError as exc:
                    # Modelo o plataforma sin soporte de fallbacks: se reintenta sin ellos.
                    if "fallback" not in str(exc).lower():
                        raise
                    self._use_fallbacks = False
                    resp = self._client.messages.create(**params)
            else:
                resp = self._client.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Credenciales de Anthropic inválidas") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Límite de uso de la API de Claude alcanzado") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Error de la API de Claude ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("No se pudo conectar con la API de Claude") from exc

        self.calls += 1
        usage = getattr(resp, "usage", None)
        if usage:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        if resp.stop_reason == "refusal":
            raise LLMError("Claude declinó la solicitud")
        if resp.stop_reason == "max_tokens":
            raise LLMError("Respuesta de Claude truncada")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if not text:
            raise LLMError("Respuesta de Claude sin texto")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Respuesta de Claude no es JSON válido") from exc

    def usage_summary(self) -> dict[str, Any]:
        return {"llamadas": self.calls, "tokens_entrada": self.input_tokens, "tokens_salida": self.output_tokens,
                "modelo": self.model if self.available else None}


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Atajo para esquemas JSON estrictos."""
    return {"type": "object", "properties": properties, "required": required or list(properties),
            "additionalProperties": False}
