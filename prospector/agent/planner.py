"""Interpreta una instrucción en lenguaje natural y la convierte en un plan de búsqueda."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

from ..normalize import strip_accents
from ..offer import Offer
from .llm import LLM, LLMError, obj

SERVICE_KEYWORDS = [
    ("control_caja", ["flujo de caja", "control de caja", "caja", "liquidez"]),
    ("acompanamiento_mensual", ["acompanamiento", "mensual", "cfo", "seguimiento financiero"]),
    ("proyectos_adicionales", ["presupuesto", "credito", "power bi", "tablero", "modelo financiero", "inversion"]),
    ("costos_inventario_comercio", ["inventario", "cartera", "cuentas por pagar", "cuentas por cobrar", "conciliacion"]),
    ("diagnostico_rentabilidad", ["costo", "costos", "rentabilidad", "precio", "precios", "food cost", "margen",
                                  "diagnostico", "organizacion financiera", "consultoria financiera", "punto de equilibrio"]),
]

METRO_WORDS = ["valle de aburra", "area metropolitana", "área metropolitana", "aburra"]


@dataclass
class SearchPlan:
    instruccion: str
    cantidad: int = 30
    sectores: list[str] = field(default_factory=list)
    ciudades: list[str] = field(default_factory=list)
    servicio_objetivo: str = "diagnostico_rentabilidad"
    min_sedes: int = 1
    palabras_clave: list[str] = field(default_factory=list)
    consultas: list[dict] = field(default_factory=list)  # {texto, sector, ciudad, max}
    justificacion: str = ""
    interpretado_por: str = "reglas"

    def to_dict(self) -> dict:
        return asdict(self)


def _rule_plan(instruction: str, offer: Offer) -> SearchPlan:
    t = strip_accents(instruction.lower())
    plan = SearchPlan(instruccion=instruction)

    m = re.search(r"\b(\d{1,4})\b", t)
    if m:
        plan.cantidad = max(1, min(int(m.group(1)), 500))

    plan.sectores = offer.sector_from_text(instruction)
    if "gastronom" in t and not plan.sectores:
        plan.sectores = [s for s, v in offer.sectors.items() if v.get("prioridad") == 1]
    if not plan.sectores:
        plan.sectores = ["cafeteria", "restaurante"]

    if any(strip_accents(w) in t for w in METRO_WORDS):
        plan.ciudades = list(offer.cities)
    else:
        plan.ciudades = [c for c in offer.cities if strip_accents(c.lower()) in t]
    if not plan.ciudades:
        plan.ciudades = ["Medellín"]

    servicio = None
    for sid, words in SERVICE_KEYWORDS:
        if any(w in t for w in words):
            servicio = sid
            break
    commerce = all(offer.sector_priority(s) >= 2 for s in plan.sectores)
    if servicio is None or (servicio == "diagnostico_rentabilidad" and commerce):
        servicio = "costos_inventario_comercio" if commerce else "diagnostico_rentabilidad"
    if servicio == "costos_inventario_comercio" and not commerce:
        servicio = "diagnostico_rentabilidad"
    plan.servicio_objetivo = servicio

    if re.search(r"varias sedes|sucursales|mas de una sede|multiples sedes|cadena local", t):
        plan.min_sedes = 2
    plan.justificacion = "Plan construido con reglas a partir de palabras clave de la instrucción y de la oferta configurada."
    return plan


def _llm_plan(instruction: str, offer: Offer, llm: LLM) -> SearchPlan:
    sector_ids = list(offer.sectors)
    service_ids = list(offer.services)
    schema = obj({
        "cantidad": {"type": "integer"},
        "sectores": {"type": "array", "items": {"type": "string", "enum": sector_ids}},
        "ciudades": {"type": "array", "items": {"type": "string"}},
        "servicio_objetivo": {"type": "string", "enum": service_ids},
        "min_sedes": {"type": "integer"},
        "palabras_clave": {"type": "array", "items": {"type": "string"}},
        "justificacion": {"type": "string"},
    })
    system = (
        "Eres el planificador de un agente de prospección B2B. Conviertes la instrucción del usuario en un plan de "
        "búsqueda que se ejecutará en Google Places. Respeta la oferta comercial: no inventes servicios ni sectores. "
        "Si la instrucción no indica cantidad usa 30; si no indica ciudad usa Medellín. 'Valle de Aburrá' significa "
        "todas las ciudades del área metropolitana listadas. palabras_clave: 0 a 3 términos de búsqueda adicionales "
        "útiles en Google Maps (por ejemplo 'café de especialidad'), sin ciudades.\n\nOFERTA:\n" + offer.summary_for_llm()
        + "\n\nSECTORES DISPONIBLES: " + ", ".join(f"{k} ({v['nombre']})" for k, v in offer.sectors.items())
        + "\nCIUDADES DISPONIBLES: " + ", ".join(offer.cities)
    )
    data = llm.json(system, f"Instrucción: {instruction}", schema, effort="low", max_tokens=4000)
    plan = SearchPlan(instruccion=instruction, interpretado_por="Claude")
    plan.cantidad = max(1, min(int(data.get("cantidad") or 30), 500))
    plan.sectores = [s for s in data.get("sectores", []) if s in offer.sectors] or ["cafeteria", "restaurante"]
    known = {strip_accents(c.lower()): c for c in offer.cities}
    plan.ciudades = []
    for c in data.get("ciudades", []):
        canon = known.get(strip_accents(c.lower()))
        if canon and canon not in plan.ciudades:
            plan.ciudades.append(canon)
        elif not canon and c and c not in plan.ciudades:
            plan.ciudades.append(c.strip())  # ampliación a otras ciudades/países
    plan.ciudades = plan.ciudades or ["Medellín"]
    plan.servicio_objetivo = data.get("servicio_objetivo") if data.get("servicio_objetivo") in offer.services else "diagnostico_rentabilidad"
    plan.min_sedes = max(1, int(data.get("min_sedes") or 1))
    plan.palabras_clave = [k for k in data.get("palabras_clave", []) if k][:3]
    plan.justificacion = data.get("justificacion", "")
    return plan


def build_queries(plan: SearchPlan, offer: Offer) -> None:
    """Genera las consultas de búsqueda (sector × ciudad [× palabra clave])."""
    combos = []
    for s in plan.sectores:
        base = offer.sectors.get(s, {}).get("consulta_base", offer.sector_name(s))
        terms = [base] + plan.palabras_clave
        for city in plan.ciudades:
            region = "Antioquia" if city in offer.cities else ""
            for term in terms:
                texto = f"{term} en {city}" + (f", {region}" if region else "")
                combos.append({"texto": texto, "sector": s, "ciudad": city})
    # Se sobremuestrea porque parte de los resultados serán duplicados, cadenas o cerrados.
    objetivo = math.ceil(plan.cantidad * 1.8)
    per_query = max(5, min(60, math.ceil(objetivo / max(1, len(combos)))))
    for c in combos:
        c["max"] = per_query
    plan.consultas = combos


def plan_instruction(instruction: str, offer: Offer, llm: LLM | None = None) -> SearchPlan:
    plan = None
    if llm and llm.available:
        try:
            plan = _llm_plan(instruction, offer, llm)
        except LLMError:
            plan = None
    if plan is None:
        plan = _rule_plan(instruction, offer)
    build_queries(plan, offer)
    return plan
