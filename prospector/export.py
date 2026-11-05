"""Exportación del CRM a CSV y Excel."""
from __future__ import annotations

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import Database
from .offer import Offer

COLUMNS = [
    ("ID", lambda p, o, d: f"P-{p['id']:05d}"),
    ("Empresa", lambda p, o, d: p["nombre"]),
    ("Razón social", lambda p, o, d: p.get("razon_social") or ""),
    ("Sector", lambda p, o, d: o.sector_name(p.get("sector"))),
    ("Ciudad", lambda p, o, d: p.get("ciudad") or ""),
    ("Dirección", lambda p, o, d: p.get("direccion") or ""),
    ("Sedes", lambda p, o, d: p.get("num_sedes") or 1),
    ("Sitio web", lambda p, o, d: p.get("sitio_web") or ""),
    ("Redes sociales", lambda p, o, d: " ".join(x for x in [p.get("instagram"), p.get("facebook"), p.get("linkedin"), p.get("tiktok")] if x)),
    ("Contacto", lambda p, o, d: p.get("contacto_nombre") or ""),
    ("Cargo", lambda p, o, d: p.get("contacto_cargo") or ""),
    ("Correo", lambda p, o, d: p.get("correo") or ""),
    ("Teléfono", lambda p, o, d: p.get("telefono") or ""),
    ("WhatsApp", lambda p, o, d: p.get("whatsapp") or ""),
    ("Servicio recomendado", lambda p, o, d: o.service_name(p.get("servicio_recomendado"))),
    ("Problema potencial", lambda p, o, d: p.get("problema_potencial") or ""),
    ("Justificación", lambda p, o, d: p.get("justificacion") or ""),
    ("Puntaje", lambda p, o, d: p.get("puntaje")),
    ("Clasificación", lambda p, o, d: p.get("clasificacion") or ""),
    ("Estado comercial", lambda p, o, d: p.get("estado_comercial") or ""),
    ("Fuentes", lambda p, o, d: d.get(p["id"], "")),
    ("Fecha de investigación", lambda p, o, d: p.get("fecha_investigacion") or ""),
    ("Última actualización", lambda p, o, d: p.get("fecha_actualizacion") or ""),
    ("Google Maps", lambda p, o, d: p.get("google_maps_url") or ""),
    ("Observaciones", lambda p, o, d: p.get("observaciones") or ""),
]


def _sources(db: Database, prospects: list[dict]) -> dict[int, str]:
    out = {}
    for p in prospects:
        urls = []
        for e in db.evidence(p["id"]):
            src = e["url"] or e["fuente"]
            if src and src not in urls:
                urls.append(src)
        out[p["id"]] = " | ".join(urls[:8])
    return out


def rows(db: Database, offer: Offer, prospects: list[dict]) -> list[list]:
    src = _sources(db, prospects)
    return [[fn(p, offer, src) for _, fn in COLUMNS] for p in prospects]


def to_csv(db: Database, offer: Offer, prospects: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c for c, _ in COLUMNS])
    w.writerows(rows(db, offer, prospects))
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM para que Excel lea las tildes


def to_xlsx(db: Database, offer: Offer, prospects: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Prospectos"
    ws.append([c for c, _ in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E5A")
    for r in rows(db, offer, prospects):
        ws.append(r)
    widths = {"Empresa": 32, "Dirección": 40, "Problema potencial": 50, "Justificación": 60, "Fuentes": 60,
              "Servicio recomendado": 34, "Redes sociales": 40}
    for i, (name, _) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(name, 16)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
