"""Controles de contacto y protección de datos (Ley 1581 de 2012).

- Lista de exclusión: quien pide no ser contactado queda bloqueado por todos sus
  identificadores (teléfono, WhatsApp, correo, dominio, Google place_id).
- Frecuencia: mínimo N días entre contactos y máximo M intentos sin respuesta.
- Aprobación humana: un mensaje solo pasa a "aprobado" si se puede contactar,
  y solo el usuario lo marca como "enviado" (el sistema no envía nada).
- Retención: purga periódica de prospectos descartados o inactivos.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .db import Database, now
from .normalize import company_domain, normalize_phone

NO_CONTACT_STATES = {"Descartado", "Cliente ganado", "Cliente perdido"}


def identifiers(p: dict) -> list[tuple[str, str | None]]:
    return [
        ("place_id", p.get("google_place_id")),
        ("telefono", normalize_phone(p.get("telefono"))),
        ("telefono", normalize_phone(p.get("whatsapp"))),
        ("correo", (p.get("correo") or "").lower() or None),
        ("dominio", p.get("dominio") or company_domain(p.get("sitio_web"))),
        ("nombre", p.get("nombre_norm")),
    ]


def can_contact(db: Database, p: dict, rules: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    sup = db.is_suppressed(identifiers(p))
    if sup:
        reasons.append(f"Está en la lista de exclusión ({sup['tipo']}: {sup['motivo'] or 'sin motivo'}).")
    if p.get("excluido"):
        reasons.append(f"Prospecto excluido: {p.get('motivo_exclusion') or 'sin motivo'}.")
    if p.get("estado_comercial") in NO_CONTACT_STATES:
        reasons.append(f"Estado comercial '{p['estado_comercial']}' no admite prospección.")
    dias = int(rules.get("dias_entre_contactos", 7))
    if p.get("ultimo_contacto"):
        last = datetime.fromisoformat(p["ultimo_contacto"])
        if datetime.now() - last < timedelta(days=dias):
            reasons.append(f"Último contacto el {p['ultimo_contacto'][:10]}; deben pasar {dias} días entre contactos.")
    max_int = int(rules.get("max_intentos_sin_respuesta", 3))
    if (p.get("intentos_contacto") or 0) >= max_int and p.get("estado_comercial") in {"Contactado", "Pendiente de contacto"}:
        reasons.append(f"Ya tiene {p['intentos_contacto']} intentos sin respuesta (máximo {max_int}).")
    return (not reasons), reasons


def opt_out(db: Database, p: dict, motivo: str = "Pidió no ser contactado") -> None:
    for tipo, valor in identifiers(p):
        if valor:
            db.add_suppression(tipo, valor, motivo)
    db.update_prospect(p["id"], {"estado_comercial": "Descartado", "excluido": 1, "motivo_exclusion": motivo})
    db.delete_drafts(p["id"])
    db.log_event(p["id"], "Exclusión", motivo)


def approve_message(db: Database, mid: int, rules: dict) -> tuple[bool, list[str]]:
    m = db.get_message(mid)
    if not m:
        return False, ["Mensaje no encontrado."]
    p = db.get_prospect(m["prospecto_id"])
    ok, reasons = can_contact(db, p, rules)
    if not ok:
        return False, reasons
    db.update_message(mid, estado="aprobado", aprobado_en=now())
    db.log_event(p["id"], "Mensaje aprobado", f"{m['canal']} #{mid}")
    return True, []


def mark_sent(db: Database, mid: int, rules: dict) -> tuple[bool, list[str]]:
    m = db.get_message(mid)
    if not m:
        return False, ["Mensaje no encontrado."]
    if m["estado"] != "aprobado":
        return False, ["Solo se puede marcar como enviado un mensaje aprobado."]
    p = db.get_prospect(m["prospecto_id"])
    ok, reasons = can_contact(db, p, rules)
    if not ok:
        return False, reasons
    db.update_message(mid, estado="enviado", enviado_en=now())
    db.add_contact(p["id"], m["canal"], "enviado manualmente", f"Mensaje #{mid}")
    if p.get("estado_comercial") in {"Nuevo prospecto", "Pendiente de investigación", "Prospecto calificado", "Pendiente de contacto"}:
        db.update_prospect(p["id"], {"estado_comercial": "Contactado"})
    db.log_event(p["id"], "Contacto registrado", f"{m['canal']} (mensaje #{mid}, enviado por el usuario)")
    return True, []


def purge(db: Database, rules: dict) -> int:
    n = db.purge(int(rules.get("dias_retencion_descartados", 180)), int(rules.get("dias_retencion_sin_contacto", 365)))
    db.log_event(None, "Purga de retención", f"{n} prospectos eliminados")
    return n
