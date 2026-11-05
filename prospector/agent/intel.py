"""Inteligencia comercial: relaciona cada empresa con UNA necesidad y UN servicio
de la oferta, y arma la ficha comercial.

Regla de lenguaje: nunca se afirma que una empresa tiene problemas. Se habla
de "necesidad potencial", "oportunidad por validar" o "posible área de mejora".
"""
from __future__ import annotations

from ..normalize import is_mobile_co
from ..offer import Offer
from .llm import LLM, LLMError, obj

PROHIBITED_PHRASES = ["tiene problemas", "está perdiendo", "esta perdiendo", "pierde dinero", "va a quebrar",
                      "garantizamos", "garantizado", "100%"]


def _signal_needs(p: dict, offer: Offer) -> list[dict]:
    """Necesidades potenciales priorizadas por las señales observadas."""
    sector = p.get("sector")
    gastro = offer.sector_priority(sector) == 1
    s = p.get("senales") or {}
    sedes = int(p.get("num_sedes") or 1)
    needs: list[dict] = []
    if gastro and (s.get("domicilios") or s.get("domicilios_google")):
        needs.append({"necesidad": "Rentabilidad real de las ventas por domicilios después de comisiones de las apps",
                      "servicio": "diagnostico_rentabilidad",
                      "evidencia": "Vende por domicilios (Google o su sitio web)."})
    if sedes >= 2:
        needs.append({"necesidad": "Vista consolidada de costos, márgenes y caja entre sedes",
                      "servicio": "acompanamiento_mensual" if sedes >= 3 else "diagnostico_rentabilidad",
                      "evidencia": f"Opera {sedes} sedes."})
    if s.get("nueva_sede"):
        needs.append({"necesidad": "Proyección financiera de la nueva sede (inversión, punto de equilibrio)",
                      "servicio": "proyectos_adicionales", "evidencia": "Anuncia una nueva sede o apertura."})
    if gastro and int(s.get("precios_detectados") or 0) >= 25:
        needs.append({"necesidad": "Carta amplia: identificar qué productos se venden mucho pero dejan poco (matriz de menú)",
                      "servicio": "diagnostico_rentabilidad",
                      "evidencia": f"Carta publicada con ~{s.get('precios_detectados')} precios."})
    for n in offer.sectors.get(sector or "", {}).get("necesidades", []):
        needs.append({"necesidad": n["necesidad"], "servicio": n["servicio"],
                      "evidencia": f"Necesidad frecuente en {offer.sector_name(sector)} (no verificada en esta empresa)."})
    return needs


def best_channel(p: dict) -> dict:
    if p.get("whatsapp"):
        return {"canal": "whatsapp", "valor": p["whatsapp"], "detalle": "WhatsApp empresarial publicado"}
    if p.get("telefono") and is_mobile_co(p.get("telefono")):
        return {"canal": "whatsapp", "valor": p["telefono"], "detalle": "Celular comercial publicado (confirmar si tiene WhatsApp)"}
    if p.get("instagram"):
        return {"canal": "instagram", "valor": p["instagram"], "detalle": "Mensaje directo en Instagram"}
    if p.get("correo"):
        return {"canal": "correo", "valor": p["correo"], "detalle": "Correo publicado"}
    if p.get("telefono"):
        return {"canal": "telefono", "valor": p["telefono"], "detalle": "Teléfono comercial publicado"}
    if p.get("formulario_contacto"):
        return {"canal": "formulario", "valor": p["formulario_contacto"], "detalle": "Formulario de su sitio web"}
    if p.get("direccion"):
        return {"canal": "visita", "valor": p["direccion"], "detalle": "Visita presencial (sin canal digital publicado)"}
    return {"canal": "ninguno", "valor": "", "detalle": "Sin canal de contacto publicado"}


def _next_step(p: dict, score: float, offer: Offer, canal: dict) -> str:
    in_metro = bool(offer.canonical_city(p.get("ciudad")) or offer.canonical_city(p.get("direccion")))
    if score < 40:
        return "Baja prioridad: no contactar por ahora; revisar si aparecen nuevas señales."
    if score < 60:
        return "Completar la investigación (confirmar canal de contacto, sedes y responsable) antes de contactar."
    pasos = []
    if canal["canal"] == "whatsapp":
        pasos.append("Revisar y aprobar el mensaje de WhatsApp y enviarlo manualmente")
    elif canal["canal"] == "instagram":
        pasos.append("Escribir por mensaje directo de Instagram con el borrador aprobado")
    elif canal["canal"] in ("correo", "formulario"):
        pasos.append("Enviar el correo aprobado")
    elif canal["canal"] == "telefono":
        pasos.append("Llamar con el guion de llamada")
    if in_metro:
        pasos.append("si no responde en 3 días, visitarlo entre 3 y 5 p. m. con la hoja de la calculadora")
    pasos.append("ofrecer el chequeo gratis de 45 minutos")
    return "; ".join(pasos).capitalize() + "."


def rule_brief(p: dict, offer: Offer, score: dict, servicio_objetivo: str | None) -> dict:
    needs = _signal_needs(p, offer)
    applicable = [n for n in needs if (offer.service(n["servicio"]) or {}).get("sectores") and
                  p.get("sector") in offer.service(n["servicio"])["sectores"]]
    preferred = [n for n in applicable if n["servicio"] == servicio_objetivo]
    top = (preferred or applicable or needs or [{"necesidad": "Claridad sobre costos y márgenes", "servicio": servicio_objetivo or "diagnostico_rentabilidad", "evidencia": "Necesidad general de la oferta."}])[0]
    svc = offer.service(top["servicio"]) or offer.service("diagnostico_rentabilidad") or {}
    canal = best_channel(p)
    que_hace = p.get("descripcion") or (
        f"{p.get('actividad') or offer.sector_name(p.get('sector'))} en {p.get('ciudad') or 'ubicación no verificada'}"
        + (f", con {p.get('num_sedes')} sedes" if (p.get("num_sedes") or 1) > 1 else "")
        + "."
    )
    servicio_txt = svc.get("nombre", "")
    gastro = offer.sector_priority(p.get("sector")) == 1
    primer_paso = ("un chequeo gratis de 45 minutos en el que costeamos 3 productos de su carta" if gastro
                   else "una conversación sin costo de 30 minutos para revisar sus números")
    argumento = (
        f"En muchos negocios de {offer.sector_name(p.get('sector')).lower()} las ventas se mueven, pero no siempre está "
        f"claro cuánto queda al final. Con el {servicio_txt} tendrían claridad sobre {top['necesidad'][0].lower() + top['necesidad'][1:]}"
        f" y una herramienta para seguir actualizando sus números. El primer paso sería {primer_paso}."
    )
    return {
        "empresa": p.get("nombre"),
        "que_hace": que_hace,
        "oportunidad": f"Necesidad potencial: {top['necesidad'].lower()}. {top['evidencia']} Oportunidad por validar en el chequeo.",
        "necesidad_principal": top["necesidad"],
        "necesidades_potenciales": [n["necesidad"] for n in needs[:5]],
        "servicio_recomendado": top["servicio"],
        "servicio_nombre": servicio_txt,
        "argumento_comercial": argumento,
        "contacto_recomendado": canal,
        "prioridad": f"{score['total']}/100 – {score['clasificacion']}",
        "proximo_paso": _next_step(p, score["total"], offer, canal),
        "generado_por": "reglas",
    }


BRIEF_SCHEMA_PROPS = {
    "que_hace": {"type": "string"},
    "necesidad_principal": {"type": "string"},
    "necesidades_potenciales": {"type": "array", "items": {"type": "string"}},
    "oportunidad": {"type": "string"},
    "servicio_recomendado": {"type": "string"},
    "argumento_comercial": {"type": "string"},
    "proximo_paso": {"type": "string"},
}


def llm_brief(p: dict, offer: Offer, score: dict, servicio_objetivo: str | None, evidence_text: str, llm: LLM) -> dict:
    props = dict(BRIEF_SCHEMA_PROPS)
    props["servicio_recomendado"] = {"type": "string", "enum": list(offer.services)}
    system = (
        "Eres el analista de inteligencia comercial de una consultoría financiera para negocios gastronómicos en "
        "Medellín. Analizas una empresa usando SOLO la evidencia entregada y la relacionas con UNA necesidad concreta "
        "y UN servicio de la oferta. Reglas: (1) no inventes datos; si algo no está en la evidencia, no lo afirmes; "
        "(2) nunca afirmes que la empresa tiene problemas: usa 'necesidad potencial', 'oportunidad por validar' o "
        "'posible área de mejora'; (3) no ofrezcas nada de la lista FUERA DE ALCANCE; (4) no prometas resultados; "
        "(5) español de Colombia, claro y breve; argumento_comercial en máximo 3 frases; proximo_paso concreto "
        "(canal y acción). Prefiere el servicio objetivo si encaja con el sector.\n\nOFERTA:\n" + offer.summary_for_llm()
    )
    prompt = (
        f"Servicio objetivo de la campaña: {offer.service_name(servicio_objetivo)} [{servicio_objetivo}]\n"
        f"Puntaje calculado: {score['total']}/100 ({score['clasificacion']})\n"
        f"Canal de contacto disponible: {best_channel(p)['detalle']}\n\nEVIDENCIA DE LA EMPRESA:\n{evidence_text}"
    )
    data = llm.json(system, prompt, obj(props), effort="low", max_tokens=6000)
    text_all = " ".join(str(v) for v in data.values()).lower()
    if any(ph in text_all for ph in PROHIBITED_PHRASES):
        raise LLMError("La ficha generada contiene afirmaciones no permitidas")
    svc = offer.service(data["servicio_recomendado"]) or offer.service(servicio_objetivo) or {}
    canal = best_channel(p)
    return {
        "empresa": p.get("nombre"),
        "que_hace": data["que_hace"],
        "oportunidad": data["oportunidad"],
        "necesidad_principal": data["necesidad_principal"],
        "necesidades_potenciales": data["necesidades_potenciales"][:5],
        "servicio_recomendado": svc.get("id", servicio_objetivo),
        "servicio_nombre": svc.get("nombre", ""),
        "argumento_comercial": data["argumento_comercial"],
        "contacto_recomendado": canal,
        "prioridad": f"{score['total']}/100 – {score['clasificacion']}",
        "proximo_paso": data["proximo_paso"],
        "generado_por": "Claude",
    }


def evidence_text(p: dict, evidence: list[dict], offer: Offer) -> str:
    lines = [
        f"Nombre: {p.get('nombre')}",
        f"Sector (clasificado): {offer.sector_name(p.get('sector'))}; actividad en Google: {p.get('actividad') or 'no disponible'}",
        f"Ciudad: {p.get('ciudad') or 'no disponible'}; dirección: {p.get('direccion') or 'no disponible'}",
        f"Sedes verificadas: {p.get('num_sedes') or 1}",
        f"Calificación Google: {p.get('rating') or 'no disponible'} ({p.get('num_resenas') or 0} reseñas); nivel de precios: {p.get('nivel_precio') or 'no disponible'}",
        f"Descripción publicada: {p.get('descripcion') or 'no disponible'}",
        f"Señales: {p.get('senales') or {}}",
    ]
    for e in evidence[:40]:
        if e["campo"] in {"correo", "telefono", "whatsapp", "contacto"}:
            continue  # los datos de contacto no son necesarios para el análisis (minimización)
        lines.append(f"- {e['campo']}: {str(e['valor'])[:300]} (fuente: {e['fuente']}, confianza {e['confianza']})")
    return "\n".join(lines)


def build_brief(p: dict, evidence: list[dict], offer: Offer, score: dict, servicio_objetivo: str | None,
                llm: LLM | None = None) -> dict:
    if llm and llm.available and score["total"] >= 40:
        try:
            return llm_brief(p, offer, score, servicio_objetivo, evidence_text(p, evidence, offer), llm)
        except LLMError:
            pass
    return rule_brief(p, offer, score, servicio_objetivo)
