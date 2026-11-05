"""Interfaz web de control del agente (FastAPI + plantillas Jinja2)."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import compliance, export
from ..agent.outreach import CHANNEL_LABELS
from ..agent.runner import ProspectingAgent
from ..db import ESTADOS_COMERCIALES, Database, now
from ..normalize import company_domain, normalize_phone
from ..offer import get_offer
from ..settings import Settings, load_settings
from ..sources.csv_import import TEMPLATE, parse_csv

HERE = Path(__file__).parent


def create_app(settings: Settings | None = None, db: Database | None = None,
               agent_factory: Callable[[], ProspectingAgent] | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = db or Database(settings.db_path)
    app = FastAPI(title="Agente de prospección – Finanzas a la carta")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    def offer():
        return get_offer(settings.offer_path)

    def make_agent() -> ProspectingAgent:
        return agent_factory() if agent_factory else ProspectingAgent(db, settings)

    templates.env.globals.update(
        ESTADOS=ESTADOS_COMERCIALES, CANALES=CHANNEL_LABELS, settings=settings,
    )

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        ctx.setdefault("msg", request.query_params.get("msg"))
        ctx.setdefault("err", request.query_params.get("err"))
        ctx["offer"] = offer()
        ctx["path"] = request.url.path
        return templates.TemplateResponse(request, name, ctx)

    def back(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
        q = {k: v for k, v in (("msg", msg), ("err", err)) if v}
        sep = "&" if "?" in url else "?"
        return RedirectResponse(url + (sep + urlencode(q) if q else ""), status_code=303)

    def get_or_404(pid: int) -> dict:
        p = db.get_prospect(pid)
        if not p:
            raise HTTPException(404, "Prospecto no encontrado")
        return p

    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        total = db.count_prospects(incluir_excluidos=True)
        activos = db.count_prospects()
        kpis = {
            "total": total,
            "nuevos": db.count_prospects(estado="Nuevo prospecto"),
            "calificados": len([p for p in db.list_prospects() if (p.get("puntaje") or 0) >= 60]),
            "prioritarios": db.count_prospects(clasificacion="Prospecto prioritario"),
            "contactados": sum(db.count_prospects(estado=e) for e in ESTADOS_COMERCIALES[4:10]),
            "clientes": db.count_prospects(estado="Cliente ganado"),
            "descartados": total - activos,
            "borradores": len(db.messages(estado="borrador")),
        }
        o = offer()
        por_sector = [(o.sector_name(s), n) for s, n in db.group_count("sector")]
        por_ciudad = db.group_count("ciudad")
        por_estado = dict(db.group_count("estado_comercial"))
        embudo = [(e, por_estado.get(e, 0)) for e in ESTADOS_COMERCIALES]
        por_clasif = db.group_count("clasificacion")
        semanas = db.leads_by_week()
        top = db.list_prospects(limit=8)
        return render(request, "dashboard.html", kpis=kpis, por_sector=por_sector, por_ciudad=por_ciudad[:10],
                      embudo=embudo, por_clasif=por_clasif, semanas=semanas, top=top, runs=db.list_runs(5))

    # ------------------------------------------------------------------
    @app.get("/buscar", response_class=HTMLResponse)
    def buscar(request: Request):
        return render(request, "buscar.html", runs=db.list_runs(30))

    @app.post("/buscar")
    def buscar_post(instruccion: str = Form(...)):
        instruccion = instruccion.strip()
        if len(instruccion) < 8:
            return back("/buscar", err="Escribe una instrucción más completa.")
        rid = make_agent().start(instruccion)
        return back(f"/corridas/{rid}")

    @app.get("/corridas/{rid}", response_class=HTMLResponse)
    def corrida(request: Request, rid: int):
        r = db.get_run(rid)
        if not r:
            raise HTTPException(404)
        return render(request, "corrida.html", r=r, prospectos=db.prospects_of_run(rid))

    # ------------------------------------------------------------------
    def _filters(request: Request) -> dict:
        qp = request.query_params
        return {k: qp.get(k) or None for k in ("sector", "ciudad", "estado", "clasificacion", "servicio", "q")} | {
            "incluir_excluidos": qp.get("excluidos") == "1"}

    @app.get("/prospectos", response_class=HTMLResponse)
    def prospectos(request: Request, orden: str = "puntaje", pagina: int = 1):
        f = _filters(request)
        per = 50
        total = db.count_prospects(**f)
        rows = db.list_prospects(**f, orden=orden, limit=per, offset=(max(1, pagina) - 1) * per)
        qs = urlencode({k: v for k, v in request.query_params.items() if k not in {"pagina"}})
        return render(request, "prospectos.html", rows=rows, total=total, f=f, orden=orden, pagina=pagina,
                      paginas=max(1, (total + per - 1) // per), qs=qs,
                      sectores=db.distinct("sector"), ciudades=db.distinct("ciudad"),
                      clasificaciones=db.distinct("clasificacion"), servicios=db.distinct("servicio_recomendado"))

    @app.get("/prospectos/nuevo", response_class=HTMLResponse)
    def nuevo(request: Request):
        return render(request, "nuevo.html")

    @app.post("/prospectos/nuevo")
    def nuevo_post(nombre: str = Form(...), sector: str = Form(""), ciudad: str = Form(""), direccion: str = Form(""),
                   sitio_web: str = Form(""), telefono: str = Form(""), whatsapp: str = Form(""), correo: str = Form(""),
                   instagram: str = Form(""), contacto_nombre: str = Form(""), contacto_cargo: str = Form(""),
                   fuente: str = Form(...), url_fuente: str = Form(""), investigar: str = Form("")):
        agent = make_agent()
        pid, status = agent.ingest_manual(dict(
            nombre=nombre, sector=sector, ciudad=ciudad, direccion=direccion, sitio_web=sitio_web, telefono=telefono,
            whatsapp=whatsapp, correo=correo, instagram=instagram, contacto_nombre=contacto_nombre,
            contacto_cargo=contacto_cargo, fuente=fuente, url_fuente=url_fuente))
        if pid is None:
            return back("/prospectos/nuevo", err="La empresa está en la lista de exclusión; no se registró.")
        if investigar:
            agent.research(pid)
        else:
            agent.qualify(pid, generate_messages=False)
        return back(f"/prospectos/{pid}", msg="Empresa registrada." if status == "nuevo" else "Ya existía: se completaron los datos faltantes.")

    @app.get("/prospectos/{pid}", response_class=HTMLResponse)
    def prospecto(request: Request, pid: int):
        p = get_or_404(pid)
        ok, reasons = compliance.can_contact(db, p, offer().contact_rules)
        return render(request, "prospecto.html", p=p, evidencia=db.evidence(pid), sedes=db.branches(pid),
                      historial=db.history(pid), mensajes=db.messages(pid), contactos=db.contacts(pid),
                      puede_contactar=ok, motivos=reasons)

    @app.post("/prospectos/{pid}/estado")
    def cambiar_estado(pid: int, estado: str = Form(...), nota: str = Form("")):
        p = get_or_404(pid)
        if estado not in ESTADOS_COMERCIALES:
            raise HTTPException(400, "Estado inválido")
        db.update_prospect(pid, {"estado_comercial": estado})
        db.log_event(pid, "Cambio de estado", f"{p['estado_comercial']} → {estado}" + (f". {nota}" if nota else ""))
        return back(f"/prospectos/{pid}", msg="Estado actualizado.")

    async def _read_form(request: Request) -> dict:
        form = await request.form()
        return {k: str(v).strip() for k, v in form.items()}

    @app.post("/prospectos/{pid}/actualizar")
    async def actualizar(pid: int, request: Request):
        p = get_or_404(pid)
        form = await _read_form(request)
        fuente = form.pop("fuente", "") or "Edición manual"
        url = form.pop("url_fuente", "") or None
        editable = ["razon_social", "sitio_web", "telefono", "whatsapp", "correo", "instagram", "facebook", "linkedin",
                    "contacto_nombre", "contacto_cargo", "direccion", "ciudad", "observaciones"]
        updates = {}
        for k in editable:
            if k in form and (form[k] or None) != (p.get(k) or None):
                updates[k] = form[k] or None
        if not updates:
            return back(f"/prospectos/{pid}", msg="Sin cambios.")
        if "telefono" in updates:
            updates["telefono_norm"] = normalize_phone(updates["telefono"])
        if "sitio_web" in updates:
            updates["dominio"] = company_domain(updates["sitio_web"])
        if "contacto_nombre" in updates:
            updates["contacto_fuente_url"] = url
        db.update_prospect(pid, updates)
        for k, v in updates.items():
            if k in {"telefono_norm", "dominio", "contacto_fuente_url", "observaciones"} or not v:
                continue
            db.add_evidence(pid, k, v, fuente, url, "alta" if url else "media", "confirmado" if url else "estimado")
        db.log_event(pid, "Datos actualizados", ", ".join(k for k in updates if k not in {"telefono_norm", "dominio"}))
        return back(f"/prospectos/{pid}", msg="Datos actualizados.")

    @app.post("/prospectos/{pid}/investigar")
    def investigar(pid: int, servicio: str = Form("")):
        get_or_404(pid)
        agent = make_agent()

        def job():
            agent.research(pid, servicio or None)

        t = threading.Thread(target=job, daemon=True)
        t.start()
        t.join(timeout=45)
        msg = "Investigación actualizada." if not t.is_alive() else "La investigación sigue en curso; recarga en unos segundos."
        return back(f"/prospectos/{pid}", msg=msg)

    @app.post("/prospectos/{pid}/mensajes")
    def regenerar_mensajes(pid: int):
        p = get_or_404(pid)
        if not p.get("ficha"):
            make_agent().qualify(pid, generate_messages=False)
        n = make_agent().generate_messages(pid)
        if not n:
            return back(f"/prospectos/{pid}", err="No se generaron mensajes (el prospecto está en la lista de exclusión).")
        return back(f"/prospectos/{pid}#mensajes", msg=f"{n} borradores preparados. Revísalos y apruébalos antes de usarlos.")

    @app.post("/prospectos/{pid}/contacto")
    def registrar_contacto(pid: int, canal: str = Form(...), resultado: str = Form(...), nota: str = Form("")):
        p = get_or_404(pid)
        if resultado != "respondió":
            ok, reasons = compliance.can_contact(db, p, offer().contact_rules)
            if not ok:
                return back(f"/prospectos/{pid}", err="No se puede registrar un nuevo contacto: " + " ".join(reasons))
        db.add_contact(pid, canal, resultado, nota)
        nuevo_estado = {"respondió": "Respondió", "reunión agendada": "Reunión programada"}.get(resultado, "Contactado")
        if ESTADOS_COMERCIALES.index(nuevo_estado) > ESTADOS_COMERCIALES.index(p["estado_comercial"]) or \
                p["estado_comercial"] in {"Nuevo prospecto", "Pendiente de investigación", "Prospecto calificado", "Pendiente de contacto"}:
            db.update_prospect(pid, {"estado_comercial": nuevo_estado})
        db.log_event(pid, "Contacto registrado", f"{canal}: {resultado}. {nota}".strip())
        return back(f"/prospectos/{pid}", msg="Contacto registrado.")

    @app.post("/prospectos/{pid}/excluir")
    def excluir(pid: int, motivo: str = Form("Pidió no ser contactado")):
        compliance.opt_out(db, get_or_404(pid), motivo)
        return back(f"/prospectos/{pid}", msg="Agregado a la lista de exclusión. No se volverá a contactar ni a importar.")

    @app.post("/prospectos/{pid}/eliminar")
    def eliminar(pid: int):
        p = get_or_404(pid)
        db.delete_prospect(pid)
        db.log_event(None, "Prospecto eliminado", f"{p['nombre']} (#{pid}) eliminado por el usuario")
        return back("/prospectos", msg=f"Se eliminó {p['nombre']} y toda su información.")

    # ------------------------------------------------------------------
    @app.get("/mensajes", response_class=HTMLResponse)
    def mensajes(request: Request, estado: str = "borrador", canal: str = ""):
        rows = db.messages(estado=estado or None)
        if canal:
            rows = [m for m in rows if m["canal"] == canal]
        return render(request, "mensajes.html", rows=rows, estado=estado, canal=canal)

    def _msg_redirect(mid: int, origen: str) -> str:
        m = db.get_message(mid)
        return f"/prospectos/{m['prospecto_id']}#mensajes" if origen == "ficha" and m else "/mensajes"

    @app.post("/mensajes/{mid}/editar")
    def editar_mensaje(mid: int, cuerpo: str = Form(...), asunto: str = Form(""), origen: str = Form("")):
        m = db.get_message(mid)
        if not m:
            raise HTTPException(404)
        if m["estado"] == "enviado":
            return back(_msg_redirect(mid, origen), err="Un mensaje enviado no se puede editar.")
        db.update_message(mid, cuerpo=cuerpo, asunto=asunto or None, estado="borrador")
        return back(_msg_redirect(mid, origen), msg="Mensaje guardado como borrador.")

    @app.post("/mensajes/{mid}/aprobar")
    def aprobar(mid: int, origen: str = Form("")):
        ok, reasons = compliance.approve_message(db, mid, offer().contact_rules)
        if not ok:
            return back(_msg_redirect(mid, origen), err="No se puede aprobar: " + " ".join(reasons))
        return back(_msg_redirect(mid, origen), msg="Mensaje aprobado. Envíalo tú mismo y luego márcalo como enviado.")

    @app.post("/mensajes/{mid}/enviado")
    def enviado(mid: int, origen: str = Form("")):
        ok, reasons = compliance.mark_sent(db, mid, offer().contact_rules)
        if not ok:
            return back(_msg_redirect(mid, origen), err=" ".join(reasons))
        return back(_msg_redirect(mid, origen), msg="Contacto registrado en el historial.")

    @app.post("/mensajes/{mid}/descartar")
    def descartar_msg(mid: int, origen: str = Form("")):
        url = _msg_redirect(mid, origen)
        db.update_message(mid, estado="descartado")
        return back(url, msg="Mensaje descartado.")

    # ------------------------------------------------------------------
    @app.get("/duplicados", response_class=HTMLResponse)
    def duplicados(request: Request):
        return render(request, "duplicados.html", pares=db.possible_duplicates())

    @app.post("/duplicados/fusionar")
    def fusionar(conservar: int = Form(...), eliminar: int = Form(...)):
        try:
            db.merge_prospects(conservar, eliminar)
        except ValueError as exc:
            return back("/duplicados", err=str(exc))
        make_agent().qualify(conservar, generate_messages=False)
        return back("/duplicados", msg="Registros fusionados y recalificados.")

    # ------------------------------------------------------------------
    @app.get("/importar", response_class=HTMLResponse)
    def importar(request: Request):
        return render(request, "importar.html")

    @app.get("/importar/plantilla.csv")
    def plantilla():
        return Response(TEMPLATE.encode("utf-8"), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=plantilla_prospectos.csv"})

    @app.post("/importar")
    async def importar_post(archivo: UploadFile = File(...), investigar: str = Form("")):
        content = await archivo.read()
        rows = parse_csv(content)
        if not rows:
            return back("/importar", err="El archivo no tiene filas válidas (se requiere al menos la columna 'nombre').")
        sin_fuente = [r["nombre"] for r in rows if not r.get("fuente")]
        if sin_fuente:
            return back("/importar", err=f"{len(sin_fuente)} filas no indican la columna 'fuente' (de dónde salió el dato). "
                                         "Complétala para cumplir la trazabilidad.")
        agent = make_agent()
        nuevos = existentes = excluidos = 0
        ids = []
        for r in rows:
            pid, status = agent.ingest_manual(r)
            if pid is None:
                excluidos += 1
                continue
            ids.append(pid)
            nuevos += status == "nuevo"
            existentes += status == "existente"
        if investigar:
            threading.Thread(target=lambda: [agent.research(i) for i in ids], daemon=True).start()
        else:
            for i in ids:
                agent.qualify(i, generate_messages=False)
        return back("/prospectos?orden=fecha", msg=f"Importación: {nuevos} nuevos, {existentes} ya existían, "
                                                   f"{excluidos} en lista de exclusión."
                    + (" La investigación web corre en segundo plano." if investigar else ""))

    # ------------------------------------------------------------------
    @app.get("/cumplimiento", response_class=HTMLResponse)
    def cumplimiento(request: Request):
        return render(request, "cumplimiento.html", exclusiones=db.suppressions())

    @app.post("/cumplimiento/exclusion")
    def agregar_exclusion(tipo: str = Form(...), valor: str = Form(...), motivo: str = Form("")):
        valor = valor.strip()
        if tipo == "telefono":
            valor = normalize_phone(valor) or valor
        elif tipo == "dominio":
            valor = company_domain(valor) or valor.lower()
        elif tipo == "correo":
            valor = valor.lower()
        elif tipo == "nombre":
            from ..normalize import normalize_name
            valor = normalize_name(valor)
        db.add_suppression(tipo, valor, motivo)
        return back("/cumplimiento", msg="Agregado a la lista de exclusión.")

    @app.post("/cumplimiento/exclusion/{sid}/eliminar")
    def quitar_exclusion(sid: int):
        db.remove_suppression(sid)
        return back("/cumplimiento", msg="Registro retirado de la lista de exclusión.")

    @app.post("/cumplimiento/purgar")
    def purgar():
        n = compliance.purge(db, offer().contact_rules)
        return back("/cumplimiento", msg=f"Purga de retención ejecutada: {n} prospectos eliminados.")

    # ------------------------------------------------------------------
    @app.get("/exportar.{fmt}")
    def exportar(request: Request, fmt: str):
        f = _filters(request)
        rows = db.list_prospects(**f, orden=request.query_params.get("orden", "puntaje"))
        stamp = now()[:10]
        if fmt == "csv":
            return Response(export.to_csv(db, offer(), rows), media_type="text/csv",
                            headers={"Content-Disposition": f"attachment; filename=prospectos_{stamp}.csv"})
        if fmt == "xlsx":
            return Response(export.to_xlsx(db, offer(), rows),
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f"attachment; filename=prospectos_{stamp}.xlsx"})
        raise HTTPException(404)

    @app.get("/configuracion", response_class=HTMLResponse)
    def configuracion(request: Request):
        llm_ok = make_agent().llm.available
        return render(request, "configuracion.html", llm_ok=llm_ok)

    return app
