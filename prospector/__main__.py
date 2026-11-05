"""Línea de comandos.

  python -m prospector servidor [--puerto 8000]
  python -m prospector buscar "Encuentra 30 cafeterías en Envigado que puedan necesitar costeo"
  python -m prospector exportar --formato xlsx --salida prospectos.xlsx
  python -m prospector purgar
"""
from __future__ import annotations

import argparse
import json
import sys

from . import compliance, export
from .db import Database
from .offer import get_offer
from .settings import load_settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prospector", description="Agente de prospección – Finanzas a la carta")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("servidor", help="Inicia la interfaz web")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--puerto", type=int, default=8000)
    b = sub.add_parser("buscar", help="Ejecuta una corrida del agente y muestra el informe")
    b.add_argument("instruccion")
    e = sub.add_parser("exportar", help="Exporta el CRM")
    e.add_argument("--formato", choices=["csv", "xlsx"], default="xlsx")
    e.add_argument("--salida", required=True)
    sub.add_parser("purgar", help="Aplica la política de retención de datos")
    args = ap.parse_args(argv)

    settings = load_settings()
    db = Database(settings.db_path)
    if args.cmd in (None, "servidor"):
        import uvicorn

        from .web.app import create_app

        uvicorn.run(create_app(settings, db), host=getattr(args, "host", "127.0.0.1"), port=getattr(args, "puerto", 8000))
        return 0
    if args.cmd == "buscar":
        from .agent.runner import ProspectingAgent

        agent = ProspectingAgent(db, settings)
        rid = db.create_run(args.instruccion)
        report = agent.run(rid)
        print(db.get_run(rid)["log"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report.get("error") else 0
    if args.cmd == "exportar":
        offer = get_offer(settings.offer_path)
        rows = db.list_prospects()
        data = export.to_csv(db, offer, rows) if args.formato == "csv" else export.to_xlsx(db, offer, rows)
        with open(args.salida, "wb") as fh:
            fh.write(data)
        print(f"{len(rows)} prospectos exportados a {args.salida}")
        return 0
    if args.cmd == "purgar":
        n = compliance.purge(db, get_offer(settings.offer_path).contact_rules)
        print(f"{n} prospectos eliminados por la política de retención")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
