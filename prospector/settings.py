"""Configuración leída de variables de entorno (.env). Nunca credenciales en código."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv es opcional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path
    offer_path: Path
    google_places_api_key: str | None
    anthropic_enabled: bool
    claude_model: str
    claude_effort: str
    http_user_agent: str
    website_timeout_s: float
    max_pages_per_site: int

    @property
    def places_enabled(self) -> bool:
        return bool(self.google_places_api_key)


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def load_settings() -> Settings:
    has_anthropic_credentials = any(
        os.getenv(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")
    )
    return Settings(
        db_path=Path(os.getenv("PROSPECTOR_DB", ROOT / "data" / "prospectos.db")),
        offer_path=Path(os.getenv("PROSPECTOR_OFERTA", ROOT / "config" / "oferta.yaml")),
        google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY") or None,
        anthropic_enabled=_bool(os.getenv("PROSPECTOR_USAR_IA"), has_anthropic_credentials),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5"),
        claude_effort=os.getenv("CLAUDE_EFFORT", "medium"),
        http_user_agent=os.getenv(
            "PROSPECTOR_USER_AGENT",
            "FinanzasALaCarta-Prospector/1.0 (investigacion comercial B2B; respeta robots.txt)",
        ),
        website_timeout_s=float(os.getenv("PROSPECTOR_WEB_TIMEOUT", "10")),
        max_pages_per_site=int(os.getenv("PROSPECTOR_MAX_PAGINAS_SITIO", "4")),
    )
