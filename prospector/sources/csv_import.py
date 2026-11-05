"""Importación manual de empresas desde CSV (listas propias, ferias, referidos,
directorios con licencia). Cada fila debe indicar de dónde salió el dato."""
from __future__ import annotations

import csv
import io

COLUMNS = ["nombre", "sector", "ciudad", "direccion", "sitio_web", "telefono", "whatsapp", "correo",
           "instagram", "facebook", "contacto_nombre", "contacto_cargo", "fuente", "url_fuente", "observaciones"]

ALIASES = {
    "empresa": "nombre", "negocio": "nombre", "nombre comercial": "nombre",
    "web": "sitio_web", "sitio web": "sitio_web", "pagina web": "sitio_web", "url": "sitio_web",
    "teléfono": "telefono", "celular": "telefono", "email": "correo", "e-mail": "correo",
    "dirección": "direccion", "cargo": "contacto_cargo", "contacto": "contacto_nombre",
    "origen": "fuente", "url fuente": "url_fuente",
}


def parse_csv(content: bytes | str) -> list[dict]:
    if isinstance(content, bytes):
        for enc in ("utf-8-sig", "latin-1"):
            try:
                content = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    sample = content[:2000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for raw in csv.DictReader(io.StringIO(content), dialect=dialect):
        row = {}
        for k, v in raw.items():
            if k is None:
                continue
            key = k.strip().lower()
            key = ALIASES.get(key, key)
            if key in COLUMNS:
                row[key] = (v or "").strip()
        if row.get("nombre"):
            rows.append(row)
    return rows


TEMPLATE = ",".join(COLUMNS) + "\n" + \
    "Café Ejemplo,cafeteria,Medellín,Cra 1 # 2-3,https://cafeejemplo.co,6040000000,,hola@cafeejemplo.co,https://instagram.com/cafeejemplo,,,,Feria gastronómica 2026,,Fila de ejemplo: bórrala\n"
