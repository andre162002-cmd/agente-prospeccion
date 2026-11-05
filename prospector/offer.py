"""Carga y consulta de la oferta comercial (config/oferta.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .normalize import strip_accents


@dataclass
class Offer:
    raw: dict[str, Any]
    path: Path | None = None
    _services: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._services = {s["id"]: s for s in self.raw.get("servicios", [])}

    # --- servicios ---------------------------------------------------
    @property
    def services(self) -> dict[str, dict]:
        return self._services

    def service(self, service_id: str | None) -> dict | None:
        return self._services.get(service_id or "")

    def service_name(self, service_id: str | None) -> str:
        s = self.service(service_id)
        return s["nombre"] if s else (service_id or "")

    # --- sectores ----------------------------------------------------
    @property
    def sectors(self) -> dict[str, dict]:
        return self.raw.get("sectores", {})

    def sector_name(self, sector_id: str | None) -> str:
        return self.sectors.get(sector_id or "", {}).get("nombre", sector_id or "Sin clasificar")

    def sector_priority(self, sector_id: str | None) -> int:
        return int(self.sectors.get(sector_id or "", {}).get("prioridad", 3))

    def sector_from_google_types(self, types: list[str], primary: str | None = None) -> str | None:
        ordered = ([primary] if primary else []) + list(types or [])
        for t in ordered:
            for sid, s in self.sectors.items():
                if t in s.get("tipos_google", []):
                    return sid
        return None

    def sector_from_text(self, text: str) -> list[str]:
        """Sectores mencionados en un texto libre (instrucción o nombre)."""
        t = f" {strip_accents(text.lower())} "
        found: list[str] = []
        for sid, s in self.sectors.items():
            for w in s.get("palabras", []):
                if f" {strip_accents(w.lower())}" in t and sid not in found:
                    found.append(sid)
                    break
        return found

    # --- ICP / geografía ---------------------------------------------
    @property
    def icp(self) -> dict:
        return self.raw.get("icp", {})

    @property
    def geography(self) -> dict:
        return self.raw.get("geografia", {})

    @property
    def cities(self) -> dict[str, float]:
        return self.geography.get("ciudades", {})

    def canonical_city(self, text: str | None) -> str | None:
        if not text:
            return None
        t = strip_accents(text.lower())
        for city in self.cities:
            if strip_accents(city.lower()) in t:
                return city
        return None

    def is_excluded_chain(self, name: str) -> bool:
        n = f" {strip_accents(name.lower())} "
        for chain in self.icp.get("cadenas_excluidas", []):
            c = strip_accents(chain.lower())
            if n.strip() == c or f" {c} " in n:
                return True
        return False

    # --- calificación / contacto -------------------------------------
    def weights(self, service_id: str | None = None) -> dict[str, int]:
        cfg = self.raw.get("calificacion", {})
        w = dict(cfg.get("pesos_por_defecto", {}))
        w.update(cfg.get("pesos_por_servicio", {}).get(service_id or "", {}))
        return w

    def classify(self, score: float) -> str:
        for band in self.raw.get("calificacion", {}).get("clasificacion", []):
            if score >= band["min"]:
                return band["nombre"]
        return "Baja prioridad"

    @property
    def contact_rules(self) -> dict:
        return self.raw.get("contacto", {})

    @property
    def brand(self) -> dict:
        return self.raw.get("marca", {})

    def summary_for_llm(self) -> str:
        """Resumen compacto de la oferta para el contexto del modelo."""
        b = self.brand
        lines = [
            f"MARCA: {b.get('nombre')} – {b.get('responsable')}. {b.get('posicionamiento')}.",
            f"PROMESA: {b.get('promesa')}",
            "CREDENCIALES: " + "; ".join(b.get("credenciales", [])),
            "SERVICIOS:",
        ]
        for s in self.services.values():
            lines.append(
                f"- [{s['id']}] {s['nombre']} ({s.get('tipo')}, {s.get('precio')}): {s.get('descripcion', '').strip()}"
                + (f" Resuelve: {'; '.join(s.get('resuelve', []))}." if s.get("resuelve") else "")
                + f" Sectores: {', '.join(s.get('sectores', []))}."
            )
        lines.append("FUERA DE ALCANCE (nunca ofrecer): " + "; ".join(self.raw.get("fuera_de_alcance", [])))
        lines.append("CLIENTE IDEAL: " + " ".join(self.icp.get("descripcion", "").split()))
        lines.append("DECISORES: " + ", ".join(self.icp.get("decisores", [])))
        return "\n".join(lines)


def load_offer(path: Path) -> Offer:
    with open(path, encoding="utf-8") as fh:
        return Offer(yaml.safe_load(fh), path)


@lru_cache(maxsize=4)
def cached_offer(path: str, mtime: float) -> Offer:  # mtime invalida la caché al editar
    return load_offer(Path(path))


def get_offer(path: Path) -> Offer:
    return cached_offer(str(path), path.stat().st_mtime)
