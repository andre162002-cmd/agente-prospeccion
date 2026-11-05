"""Orquestador del agente de prospección.

Flujo de una corrida (instrucción en lenguaje natural):
 1. Interpretar la instrucción → plan (planner).
 2. Consultar la oferta (config/oferta.yaml) para sectores, servicio y criterios.
 3. Buscar empresas en Google Places (fuente oficial).
 4. Deduplicar (place_id, dominio, teléfono, nombre normalizado) y agrupar sedes.
 5. Investigar el sitio web de cada empresa (respetando robots.txt).
 6. Calificar (0–100, explicado) y relacionar con un servicio (ficha comercial).
 7. Preparar borradores de mensajes para los prospectos calificados.
 8. Guardar todo con fuente, fecha, confianza y verificación, y generar el informe.

El agente nunca inventa resultados: si una fuente no está configurada o falla,
la corrida lo reporta como error o advertencia.
"""
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field

from ..compliance import can_contact, identifiers
from ..db import Database, now
from ..normalize import company_domain, normalize_name, normalize_phone
from ..offer import Offer, get_offer
from ..settings import Settings
from ..sources.google_places import GooglePlacesClient, Place, PlacesError
from ..sources.website import WebsiteResearcher
from .intel import build_brief
from .llm import LLM
from .outreach import CHANNELS, build_messages
from .planner import SearchPlan, plan_instruction
from .qualify import score_prospect

FUENTE_GOOGLE = "Google Places API"
FUENTE_WEB = "Sitio web de la empresa"
EARLY_STATES = {"Nuevo prospecto", "Pendiente de investigación", "Prospecto calificado", None, ""}


@dataclass
class RunStats:
    solicitadas: int = 0
    resultados_fuente: int = 0
    empresas_nuevas: int = 0
    sedes_agregadas: int = 0
    ya_existian: int = 0
    cerradas: int = 0
    en_lista_exclusion: int = 0
    fuera_de_filtro: int = 0
    verificadas: int = 0
    prioritarias: int = 0
    calificadas: int = 0
    por_investigar: int = 0
    baja_prioridad: int = 0
    descartadas_icp: int = 0
    con_canal_contacto: int = 0
    sitios_revisados: int = 0
    sitios_bloqueados_o_fallidos: int = 0
    mensajes_preparados: int = 0
    consultas_ejecutadas: int = 0
    advertencias: list[str] = field(default_factory=list)


def size_estimate(sedes: int, resenas: int) -> str:
    if sedes >= 9:
        return "Grande (9+ sedes)"
    if sedes >= 4:
        return "Mediana (4–8 sedes)"
    if sedes >= 2:
        return "Pequeña (2–3 sedes)"
    if resenas >= 500:
        return "Pequeña (1 sede, alto volumen)"
    return "Micro o pequeña (1 sede)"


class ProspectingAgent:
    def __init__(self, db: Database, settings: Settings, *, offer: Offer | None = None,
                 places: GooglePlacesClient | None = None, website: WebsiteResearcher | None = None,
                 llm: LLM | None = None):
        self.db = db
        self.settings = settings
        self.offer = offer or get_offer(settings.offer_path)
        self.places = places
        if self.places is None and settings.places_enabled:
            self.places = GooglePlacesClient(settings.google_places_api_key or "")
        self.website = website or WebsiteResearcher(settings.http_user_agent, settings.website_timeout_s,
                                                    settings.max_pages_per_site)
        self.llm = llm or LLM(settings.anthropic_enabled, settings.claude_model, settings.claude_effort)

    # ------------------------------------------------------------------
    # Ingesta
    # ------------------------------------------------------------------
    def _evidence_from_place(self, pid: int, pl: Place) -> None:
        url = pl.maps_url
        add = lambda campo, valor, conf="alta", ver="confirmado": self.db.add_evidence(pid, campo, valor, FUENTE_GOOGLE, url, conf, ver)  # noqa: E731
        add("nombre", pl.nombre)
        add("sede", f"{pl.nombre} – {pl.direccion or 'dirección no disponible'}")
        if pl.direccion:
            add("direccion", pl.direccion)
        if pl.ciudad:
            add("ciudad", pl.ciudad)
        if pl.tipo_principal_texto or pl.tipo_principal:
            add("actividad", pl.tipo_principal_texto or pl.tipo_principal)
        if pl.telefono:
            add("telefono", pl.telefono)
        if pl.sitio_web:
            add("sitio_web", pl.sitio_web)
        if pl.estado_negocio:
            add("estado_negocio", pl.estado_negocio)
        if pl.rating is not None:
            add("rating", f"{pl.rating} ({pl.num_resenas or 0} reseñas)")
        if pl.nivel_precio:
            add("nivel_precio", pl.nivel_precio)
        if pl.resumen:
            add("descripcion", pl.resumen)
        if pl.domicilios is not None:
            add("domicilios", "sí" if pl.domicilios else "no")

    def ingest_place(self, pl: Place, sector_hint: str | None, run_id: int | None) -> tuple[int | None, str]:
        if pl.estado_negocio and pl.estado_negocio.startswith("CLOSED"):
            return None, "cerrado"
        name_norm = normalize_name(pl.nombre)
        phone = normalize_phone(pl.telefono)
        domain = company_domain(pl.sitio_web)
        if self.db.is_suppressed([("place_id", pl.place_id), ("telefono", phone), ("dominio", domain), ("nombre", name_norm)]):
            return None, "excluido_lista"
        existing = self.db.find_prospect(place_id=pl.place_id, dominio=domain, telefono_norm=phone,
                                         nombre_norm=name_norm if len(name_norm) >= 5 else None)
        branch = {"place_id": pl.place_id, "nombre": pl.nombre, "direccion": pl.direccion, "ciudad": pl.ciudad,
                  "telefono": pl.telefono, "maps_url": pl.maps_url, "lat": pl.lat, "lng": pl.lng}
        if existing:
            pid = existing["id"]
            is_same_place = existing.get("google_place_id") == pl.place_id or any(
                b["place_id"] == pl.place_id for b in self.db.branches(pid))
            self._evidence_from_place(pid, pl)
            if is_same_place:
                # Refresca datos variables (reseñas, estado) sin pisar datos editados a mano.
                self.db.update_prospect(pid, {"rating": pl.rating, "num_resenas": pl.num_resenas,
                                              "estado_negocio": pl.estado_negocio})
                self.db.log_event(pid, "Encontrado de nuevo", f"Consulta: {pl.consulta}", run_id)
                return pid, "existente"
            self.db.add_branch(pid, branch)
            p = self.db.get_prospect(pid)
            self.db.update_prospect(pid, {"num_resenas": (p.get("num_resenas") or 0) + (pl.num_resenas or 0)})
            self.db.log_event(pid, "Sede agregada", f"{pl.nombre} – {pl.direccion}", run_id)
            return pid, "sede_agregada"

        sector = self.offer.sector_from_google_types(pl.tipos, pl.tipo_principal) or sector_hint
        senales = {}
        if pl.domicilios:
            senales["domicilios_google"] = True
        values = {
            "nombre": pl.nombre, "nombre_norm": name_norm, "sector": sector,
            "actividad": pl.tipo_principal_texto or pl.tipo_principal,
            "ciudad": self.offer.canonical_city(pl.ciudad) or pl.ciudad or self.offer.canonical_city(pl.direccion),
            "direccion": pl.direccion, "sitio_web": pl.sitio_web, "dominio": domain,
            "telefono": pl.telefono, "telefono_norm": phone, "rating": pl.rating, "num_resenas": pl.num_resenas,
            "nivel_precio": pl.nivel_precio, "estado_negocio": pl.estado_negocio, "google_place_id": pl.place_id,
            "google_maps_url": pl.maps_url, "descripcion": pl.resumen, "senales": senales,
            "estado_comercial": "Nuevo prospecto", "corrida_id": run_id,
        }
        if pl.sitio_web and "instagram.com" in pl.sitio_web.lower():
            values["instagram"] = pl.sitio_web
        if pl.sitio_web and "facebook.com" in pl.sitio_web.lower():
            values["facebook"] = pl.sitio_web
        pid = self.db.insert_prospect(values)
        self.db.add_branch(pid, branch)
        self._evidence_from_place(pid, pl)
        self.db.log_event(pid, "Prospecto creado", f"Fuente: {FUENTE_GOOGLE}. Consulta: {pl.consulta}", run_id)
        return pid, "nuevo"

    def ingest_manual(self, row: dict, run_id: int | None = None) -> tuple[int | None, str]:
        """Alta manual o por CSV. La fuente declarada queda registrada en cada dato."""
        nombre = row["nombre"].strip()
        name_norm = normalize_name(nombre)
        phone = normalize_phone(row.get("telefono"))
        domain = company_domain(row.get("sitio_web"))
        if self.db.is_suppressed([("telefono", phone), ("dominio", domain), ("nombre", name_norm),
                                  ("correo", (row.get("correo") or "").lower() or None)]):
            return None, "excluido_lista"
        existing = self.db.find_prospect(dominio=domain, telefono_norm=phone, nombre_norm=name_norm)
        fuente = row.get("fuente") or "Carga manual"
        url = row.get("url_fuente") or None
        ver = "confirmado" if url else "estimado"
        conf = "alta" if url else "media"
        fields = {k: (row.get(k) or None) for k in ["sitio_web", "telefono", "whatsapp", "correo", "instagram", "facebook",
                                                     "direccion", "contacto_nombre", "contacto_cargo"]}
        sector = row.get("sector") if row.get("sector") in self.offer.sectors else (
            (self.offer.sector_from_text(row.get("sector") or "") or self.offer.sector_from_text(nombre) or [None])[0])
        if existing:
            pid = existing["id"]
            updates = {k: v for k, v in fields.items() if v and not existing.get(k)}
            if updates:
                self.db.update_prospect(pid, updates)
            status = "existente"
        else:
            values = {"nombre": nombre, "nombre_norm": name_norm, "sector": sector,
                      "ciudad": self.offer.canonical_city(row.get("ciudad")) or row.get("ciudad") or None,
                      "dominio": domain, "telefono_norm": phone, "observaciones": row.get("observaciones") or "",
                      "estado_comercial": "Nuevo prospecto", "corrida_id": run_id, **fields}
            if fields.get("contacto_nombre"):
                values["contacto_fuente_url"] = url
            pid = self.db.insert_prospect(values)
            status = "nuevo"
        for campo, valor in [("nombre", nombre), ("ciudad", row.get("ciudad")), *fields.items()]:
            if valor:
                if campo in {"contacto_nombre", "contacto_cargo"}:
                    self.db.add_evidence(pid, "contacto", f"{fields.get('contacto_nombre') or ''} | {fields.get('contacto_cargo') or ''}", fuente, url, conf, ver)
                    continue
                self.db.add_evidence(pid, campo, valor, fuente, url, conf, ver)
        self.db.log_event(pid, "Alta manual" if status == "nuevo" else "Actualización manual", f"Fuente: {fuente}", run_id)
        return pid, status

    # ------------------------------------------------------------------
    # Investigación individual
    # ------------------------------------------------------------------
    def research_website(self, pid: int, run_id: int | None = None) -> dict:
        p = self.db.get_prospect(pid)
        info = {"revisado": False, "ok": False}
        url = p.get("sitio_web")
        if not url or not company_domain(url):
            if url:
                self.db.add_evidence(pid, "sitio_web_estado", "El enlace publicado es una red social o agregador",
                                     FUENTE_GOOGLE, url, "alta", "confirmado")
            return info
        info["revisado"] = True
        res = self.website.research(url)
        if not res.ok:
            self.db.add_evidence(pid, "sitio_web_estado", res.error or "No se pudo revisar", FUENTE_WEB, url, "alta",
                                 "no_disponible")
            self.db.log_event(pid, "Sitio web no revisado", res.error or "", run_id)
            senales = dict(p.get("senales") or {})
            senales["sitio_bloqueado_robots"] = res.bloqueado_por_robots
            self.db.update_prospect(pid, {"senales": senales})
            return info
        info["ok"] = True
        updates: dict = {}
        for f in res.hallazgos:
            if f.campo == "contacto":
                nombre, _, cargo = f.valor.partition(" | ")
                self.db.add_evidence(pid, "contacto", f.valor, FUENTE_WEB, f.url, f.confianza, f.verificacion)
                if not p.get("contacto_nombre") and "contacto_nombre" not in updates:
                    updates.update({"contacto_nombre": nombre, "contacto_cargo": cargo, "contacto_fuente_url": f.url})
                continue
            self.db.add_evidence(pid, f.campo, f.valor, FUENTE_WEB, f.url, f.confianza, f.verificacion)
            if f.campo in {"correo", "whatsapp", "formulario_contacto", "instagram", "facebook", "linkedin", "tiktok"}:
                if not p.get(f.campo) and f.campo not in updates:
                    updates[f.campo] = f.valor
            if f.campo == "telefono" and not p.get("telefono") and "telefono" not in updates:
                updates["telefono"] = f.valor
                updates["telefono_norm"] = normalize_phone(f.valor)
        senales = dict(p.get("senales") or {})
        for s, urls in res.senales.items():
            senales[s] = True
            self.db.add_evidence(pid, f"senal_{s}", "detectada", FUENTE_WEB, urls[0], "media", "estimado")
        senales["precios_detectados"] = res.precios_detectados
        senales["menciones_sedes"] = res.menciones_sedes
        if res.precios_detectados:
            self.db.add_evidence(pid, "precios_publicados", f"~{res.precios_detectados} precios en la página",
                                 FUENTE_WEB, res.paginas[0], "media", "estimado")
        if res.descripcion:
            self.db.add_evidence(pid, "descripcion", res.descripcion, FUENTE_WEB, res.paginas[0], "alta", "confirmado")
            if not p.get("descripcion"):
                updates["descripcion"] = res.descripcion
        updates["senales"] = senales
        self.db.update_prospect(pid, updates)
        self.db.log_event(pid, "Sitio web revisado", f"{len(res.paginas)} páginas; {len(res.hallazgos)} datos", run_id)
        return info

    def qualify(self, pid: int, servicio_objetivo: str | None = None, run_id: int | None = None,
                generate_messages: bool = True) -> dict:
        p = self.db.get_prospect(pid)
        servicio_objetivo = servicio_objetivo or p.get("servicio_recomendado") or "diagnostico_rentabilidad"
        sedes = int(p.get("num_sedes") or 1)
        updates: dict = {"tamano_estimado": size_estimate(sedes, int(p.get("num_resenas") or 0))}
        self.db.add_evidence(pid, "tamano_estimado", updates["tamano_estimado"], "Estimación del agente", None, "baja", "estimado")
        p.update(updates)
        score = score_prospect(p, self.offer, servicio_objetivo)
        brief = build_brief(p, self.db.evidence(pid), self.offer, score, servicio_objetivo, self.llm)
        top_reasons = []
        for key in ("necesidad", "icp", "crecimiento"):
            top_reasons += score["criterios"][key]["razones"][:2]
        updates.update({
            "puntaje": score["total"], "clasificacion": score["clasificacion"], "puntaje_detalle": score,
            "ficha": brief, "servicio_recomendado": brief["servicio_recomendado"],
            "problema_potencial": brief["necesidad_principal"],
            "justificacion": brief["oportunidad"] + " Razones: " + " ".join(top_reasons),
        })
        if score["descartes"]:
            updates.update({"excluido": 1, "motivo_exclusion": "; ".join(score["descartes"]),
                            "estado_comercial": "Descartado"})
        elif p.get("estado_comercial") in EARLY_STATES:
            updates["estado_comercial"] = ("Prospecto calificado" if score["total"] >= 60 else
                                           "Pendiente de investigación" if score["total"] >= 40 else "Nuevo prospecto")
        self.db.update_prospect(pid, updates)
        self.db.log_event(pid, "Calificado", f"{score['total']}/100 – {score['clasificacion']} (servicio: {servicio_objetivo})", run_id)
        n_msgs = 0
        if generate_messages and not score["descartes"] and score["total"] >= 60:
            n_msgs = self.generate_messages(pid, run_id)
        return {"score": score, "brief": brief, "mensajes": n_msgs}

    def generate_messages(self, pid: int, run_id: int | None = None) -> int:
        p = self.db.get_prospect(pid)
        ok, reasons = can_contact(self.db, p, self.offer.contact_rules)
        if not ok and self.db.is_suppressed(identifiers(p)):
            self.db.log_event(pid, "Mensajes no generados", " ".join(reasons), run_id)
            return 0
        brief = p.get("ficha") or {}
        if not brief:
            return 0
        msgs, origen = build_messages(p, brief, self.offer, self.llm)
        self.db.delete_drafts(pid)
        for canal in CHANNELS:
            m = msgs.get(canal)
            if m:
                self.db.add_message(pid, canal, m["cuerpo"], asunto=m.get("asunto"),
                                    necesidad=brief.get("necesidad_principal"),
                                    servicio=brief.get("servicio_recomendado"), generado_por=origen)
        self.db.log_event(pid, "Mensajes preparados", f"{len(msgs)} borradores ({origen}); requieren aprobación", run_id)
        return len(msgs)

    def research(self, pid: int, servicio_objetivo: str | None = None, run_id: int | None = None) -> dict:
        web = self.research_website(pid, run_id)
        result = self.qualify(pid, servicio_objetivo, run_id)
        result["web"] = web
        return result

    # ------------------------------------------------------------------
    # Corridas
    # ------------------------------------------------------------------
    def _log(self, rid: int, msg: str) -> None:
        self.db.append_run_log(rid, msg)

    def run(self, rid: int) -> dict:
        r = self.db.get_run(rid)
        stats = RunStats()
        try:
            self.db.update_run(rid, estado="planificando")
            plan: SearchPlan = plan_instruction(r["instruccion"], self.offer, self.llm)
            stats.solicitadas = plan.cantidad
            self.db.update_run(rid, plan=plan.to_dict())
            self._log(rid, f"Plan ({plan.interpretado_por}): {plan.cantidad} empresas · sectores "
                           f"{', '.join(self.offer.sector_name(s) for s in plan.sectores)} · ciudades {', '.join(plan.ciudades)}"
                           f" · servicio: {self.offer.service_name(plan.servicio_objetivo)}"
                           + (f" · mínimo {plan.min_sedes} sedes" if plan.min_sedes > 1 else ""))
            if not self.places:
                raise PlacesError(
                    "No hay una fuente de búsqueda configurada: falta GOOGLE_PLACES_API_KEY. El agente no inventa "
                    "resultados. Configura la clave en el archivo .env o importa empresas desde un CSV.")

            # Fase 1: búsqueda y deduplicación
            self.db.update_run(rid, estado="buscando")
            touched: list[int] = []
            center = (self.offer.geography["centro"]["lat"], self.offer.geography["centro"]["lng"])
            for q in plan.consultas:
                if plan.min_sedes <= 1 and stats.empresas_nuevas >= plan.cantidad:
                    break
                in_metro = q["ciudad"] in self.offer.cities
                try:
                    places = self.places.text_search(q["texto"], max_results=q["max"],
                                                     center=center if in_metro else None,
                                                     radius_m=self.offer.geography.get("radio_m", 20000))
                except PlacesError as exc:
                    stats.advertencias.append(f"Consulta '{q['texto']}' falló: {exc}")
                    self._log(rid, f"ERROR en '{q['texto']}': {exc}")
                    if "403" in str(exc) or "429" in str(exc):
                        raise
                    continue
                stats.consultas_ejecutadas += 1
                stats.resultados_fuente += len(places)
                nuevos_q = 0
                for pl in places:
                    if plan.min_sedes <= 1 and stats.empresas_nuevas >= plan.cantidad:
                        break
                    pid, status = self.ingest_place(pl, q["sector"], rid)
                    if status == "nuevo":
                        stats.empresas_nuevas += 1
                        nuevos_q += 1
                        touched.append(pid)
                    elif status == "sede_agregada":
                        stats.sedes_agregadas += 1
                        if pid not in touched:
                            touched.append(pid)
                    elif status == "existente":
                        stats.ya_existian += 1
                    elif status == "cerrado":
                        stats.cerradas += 1
                    elif status == "excluido_lista":
                        stats.en_lista_exclusion += 1
                self._log(rid, f"'{q['texto']}': {len(places)} resultados, {nuevos_q} empresas nuevas")

            # Fase 2: investigación, calificación, ficha y mensajes
            self.db.update_run(rid, estado="investigando")
            total = len(touched)
            for i, pid in enumerate(touched, start=1):
                p = self.db.get_prospect(pid)
                if plan.min_sedes > 1 and int(p.get("num_sedes") or 1) < plan.min_sedes:
                    stats.fuera_de_filtro += 1
                    self.db.update_prospect(pid, {"observaciones": ((p.get("observaciones") or "") +
                                            f" No cumple el filtro de {plan.min_sedes}+ sedes de la corrida #{rid}.").strip()})
                    self.qualify(pid, plan.servicio_objetivo, rid, generate_messages=False)
                else:
                    web = self.research_website(pid, rid)
                    if web["revisado"]:
                        stats.sitios_revisados += 1
                        if not web["ok"]:
                            stats.sitios_bloqueados_o_fallidos += 1
                    out = self.qualify(pid, plan.servicio_objetivo, rid)
                    stats.mensajes_preparados += out["mensajes"]
                p = self.db.get_prospect(pid)
                s = p.get("puntaje") or 0
                if p.get("excluido"):
                    stats.descartadas_icp += 1
                elif s >= 80:
                    stats.prioritarias += 1
                elif s >= 60:
                    stats.calificadas += 1
                elif s >= 40:
                    stats.por_investigar += 1
                else:
                    stats.baja_prioridad += 1
                has_channel = any(p.get(k) for k in ("telefono", "whatsapp", "correo", "formulario_contacto", "instagram"))
                if has_channel:
                    stats.con_canal_contacto += 1
                if p.get("estado_negocio") == "OPERATIONAL" and has_channel:
                    stats.verificadas += 1
                if i % 5 == 0 or i == total:
                    self._log(rid, f"Investigadas {i}/{total} empresas")

            if stats.empresas_nuevas < plan.cantidad:
                stats.advertencias.append(
                    f"Se pidieron {plan.cantidad} empresas y se encontraron {stats.empresas_nuevas} nuevas. "
                    "Amplía ciudades, sectores o palabras clave para encontrar más.")
            report = self._report(stats, plan)
            self.db.update_run(rid, estado="completada", terminada=now(), reporte=report)
            self._log(rid, "Corrida completada")
            return report
        except Exception as exc:  # se registra el error real; nunca se simulan resultados
            report = self._report(stats, None)
            report["error"] = str(exc)
            self.db.update_run(rid, estado="error", terminada=now(), error=str(exc), reporte=report)
            self._log(rid, f"ERROR: {exc}")
            if not isinstance(exc, PlacesError):
                self._log(rid, traceback.format_exc(limit=3))
            return report

    def _report(self, stats: RunStats, plan: SearchPlan | None) -> dict:
        d = stats.__dict__.copy()
        d["calificadas_total"] = stats.prioritarias + stats.calificadas
        d["solicitudes_google"] = getattr(self.places, "requests_made", 0) if self.places else 0
        d["uso_ia"] = self.llm.usage_summary()
        if plan:
            d["servicio_objetivo"] = self.offer.service_name(plan.servicio_objetivo)
        return d

    def start(self, instruction: str) -> int:
        rid = self.db.create_run(instruction)
        threading.Thread(target=self.run, args=(rid,), daemon=True, name=f"corrida-{rid}").start()
        return rid
