"""Estrategia de acercamiento: borradores de WhatsApp, correo, LinkedIn, guion de
llamada, guion de visita, preguntas de primera reunión y propuesta de valor.

Los mensajes se guardan como BORRADOR. Nunca se envían automáticamente:
el usuario los aprueba y los envía él mismo (ver compliance.py).
"""
from __future__ import annotations

from ..offer import Offer
from .intel import PROHIBITED_PHRASES
from .llm import LLM, LLMError, obj

CHANNELS = ["whatsapp", "correo", "linkedin", "llamada", "visita", "preguntas_reunion", "propuesta_valor"]
CHANNEL_LABELS = {
    "whatsapp": "WhatsApp Business",
    "correo": "Correo comercial",
    "linkedin": "Mensaje de LinkedIn",
    "llamada": "Guion de llamada",
    "visita": "Guion de visita presencial",
    "preguntas_reunion": "Preguntas para la primera reunión",
    "propuesta_valor": "Propuesta de valor personalizada",
}


def _hook(p: dict, offer: Offer) -> str:
    """Un detalle verificable que demuestra que conocemos el negocio (sin afirmar problemas)."""
    s = p.get("senales") or {}
    sedes = int(p.get("num_sedes") or 1)
    if sedes >= 2:
        return f"vi que ya tienen {sedes} sedes"
    if s.get("nueva_sede"):
        return "vi que están anunciando una nueva sede"
    if s.get("domicilios") or s.get("domicilios_google"):
        return "vi que también venden por domicilios"
    if int(s.get("precios_detectados") or 0) >= 25:
        return "estuve viendo su carta, que es bastante completa"
    if p.get("ciudad"):
        return f"conozco su {offer.sector_name(p.get('sector')).lower()} en {p['ciudad']}"
    return "conozco su negocio"


def _question(need: str) -> str:
    n = need.lower()
    if "domicilio" in n:
        return "¿tienen claro cuánto les queda de cada pedido de domicilio después de la comisión de la app?"
    if "sede" in n:
        return "¿pueden ver hoy, sede por sede, cuánto deja cada producto y cómo va la caja?"
    if "caja" in n:
        return "¿tienen una forma sencilla de ver cómo va a estar la caja en las próximas semanas?"
    if "inventario" in n or "rotación" in n:
        return "¿tienen claro qué líneas de producto les dejan más margen y cuál inventario se está quedando quieto?"
    if "cartera" in n:
        return "¿tienen claro cuántos días se están demorando sus clientes en pagar y cuánto margen deja cada uno?"
    if "punto de equilibrio" in n or "meta" in n:
        return "¿tienen claro cuánto necesitan vender al día para cubrir todos los gastos del mes?"
    if "nueva sede" in n or "proyección" in n:
        return "¿ya tienen proyectado cuánto tiempo le tomaría a la nueva sede cubrir sus costos?"
    return "¿tienen claro cuánto les deja realmente cada producto después de las últimas alzas de insumos?"


def rule_messages(p: dict, brief: dict, offer: Offer) -> dict[str, dict]:
    b = offer.brand
    firma_nombre = b.get("responsable", "").split(" ")[0] + " " + (b.get("responsable", "").split(" ")[1] if len(b.get("responsable", "").split(" ")) > 1 else "")
    firma_nombre = firma_nombre.strip()
    negocio = p.get("nombre", "su negocio")
    sector = offer.sector_name(p.get("sector")).lower()
    need = brief.get("necesidad_principal") or "claridad sobre costos y márgenes"
    svc = offer.service(brief.get("servicio_recomendado")) or {}
    pregunta = _question(need)
    hook = _hook(p, offer)
    gastro = offer.sector_priority(p.get("sector")) == 1
    especialidad = "cafeterías y restaurantes de Medellín" if gastro else "negocios de Medellín"
    chequeo = ("un chequeo gratis de 45 minutos donde costeamos 3 productos de su carta en vivo, sin compromiso"
               if gastro else "una conversación de 30 minutos sin costo para revisar sus números, sin compromiso")

    whatsapp = (
        f"Hola, ¿cómo están? Soy {firma_nombre}, trabajo con {especialidad} en temas de costos y rentabilidad. "
        f"{hook.capitalize()} y les quería hacer una pregunta puntual: {pregunta}\n\n"
        f"Estoy haciendo {chequeo}. ¿Les interesa que lo agendemos esta semana?"
    )
    correo_asunto = f"Una pregunta sobre los costos de {negocio}"
    correo = (
        f"Hola, equipo de {negocio}:\n\n"
        f"Soy {b.get('responsable')}, analista financiero en Medellín. Trabajo con {especialidad} ayudándoles a saber "
        f"cuánto les deja cada producto y qué ajustar.\n\n"
        f"{hook.capitalize()}, y por eso les escribo con una pregunta concreta: {pregunta}\n\n"
        f"En muchos negocios de {sector} esto no está claro, sobre todo después de las alzas de insumos. Les propongo "
        f"{chequeo}. Si después quieren profundizar, el siguiente paso sería un {svc.get('nombre', 'diagnóstico')}.\n\n"
        f"¿Les queda bien una conversación corta esta semana o la próxima?\n\n"
        f"Un saludo,\n{b.get('responsable')}\n{b.get('nombre')} · {b.get('posicionamiento')}\n"
        f"WhatsApp: {b.get('whatsapp')} · Instagram: {b.get('instagram')}\n\n"
        f"Si prefieren no recibir más mensajes míos, respondan \"no\" y no los vuelvo a contactar."
    )
    linkedin = (
        f"Hola, soy {firma_nombre}. Trabajo con {especialidad} en costos y rentabilidad. {hook.capitalize()}. "
        f"Me gustaría conectar y, si les sirve, compartirles cómo otros negocios de {sector} están calculando el costo "
        f"real de sus productos. Sin compromiso."
    )
    llamada = (
        "1. Saludo (15 s): «Hola, ¿hablo con el dueño o el administrador de " + negocio + "? Soy " + firma_nombre +
        ", trabajo con " + especialidad + " en costos. ¿Tiene dos minutos?»\n"
        "2. Motivo (30 s): «" + hook.capitalize() + ". Le llamo por algo puntual: " + pregunta + "»\n"
        "3. Escuchar (1–2 min): dejar que cuente cómo lo manejan hoy. No vender todavía.\n"
        "4. Propuesta (30 s): «Estoy ofreciendo " + chequeo + ". Al final queda con 3 productos costeados.»\n"
        "5. Cierre: proponer dos horarios concretos. Si dice que no, agradecer y preguntar si puede volver a "
        "escribirle en unos meses. Si pide no ser contactado, registrarlo en la lista de exclusión."
    )
    visita = (
        f"Mejor horario: entre 3 y 5 p. m. (fuera de la hora pico).\n"
        f"1. Pedir hablar con el dueño o el administrador; si no está, dejar la hoja de una página con el QR de la "
        f"calculadora y preguntar el mejor momento para volver.\n"
        f"2. Apertura: «Soy {firma_nombre}, ayudo a {especialidad} a saber cuánto les deja cada producto. "
        f"{hook.capitalize()}.»\n"
        f"3. Pregunta: «{pregunta[0].upper() + pregunta[1:]}»\n"
        f"4. Ofrecer el chequeo gratis y agendar día y hora en ese momento.\n"
        f"5. Registrar el resultado de la visita en el CRM."
    )
    preguntas = "\n".join(f"- {q}" for q in [
        "¿Cómo deciden hoy los precios de la carta y cada cuánto los revisan?",
        "¿Saben cuál es el producto que más vende y cuál es el que más les deja?",
        pregunta[0].upper() + pregunta[1:],
        "¿Qué información tienen a la mano: ventas por producto del POS, facturas de proveedores, recetas?",
        "¿Tienen contador? ¿Qué reportes les entrega y cada cuánto?",
        "Si pudieran resolver una sola cosa de sus números este mes, ¿cuál sería?",
        "¿Quién más participa en la decisión de contratar un servicio así?",
    ])
    propuesta = (
        f"Para {negocio}: {svc.get('nombre', 'Diagnóstico de Rentabilidad')}. "
        f"Necesidad potencial a validar: {need.lower()}. "
        f"Qué recibirían: {svc.get('descripcion', '').strip()} "
        f"Inversión de referencia: {svc.get('precio', 'por cotizar')}. "
        f"Primer paso sin costo: {chequeo}. Los resultados dependen de la información y de su implementación; "
        f"no se garantizan cifras."
    )
    return {
        "whatsapp": {"cuerpo": whatsapp},
        "correo": {"asunto": correo_asunto, "cuerpo": correo},
        "linkedin": {"cuerpo": linkedin},
        "llamada": {"cuerpo": llamada},
        "visita": {"cuerpo": visita},
        "preguntas_reunion": {"cuerpo": preguntas},
        "propuesta_valor": {"cuerpo": propuesta},
    }


def llm_messages(p: dict, brief: dict, offer: Offer, llm: LLM) -> dict[str, dict]:
    schema = obj({
        "whatsapp": {"type": "string"},
        "correo_asunto": {"type": "string"},
        "correo_cuerpo": {"type": "string"},
        "linkedin": {"type": "string"},
        "llamada": {"type": "string"},
        "visita": {"type": "string"},
        "preguntas_reunion": {"type": "array", "items": {"type": "string"}},
        "propuesta_valor": {"type": "string"},
    })
    b = offer.brand
    system = (
        "Escribes mensajes de primer contacto para " + str(b.get("responsable")) + " (" + str(b.get("nombre")) + "), "
        "consultor financiero independiente en Medellín. Reglas estrictas:\n"
        "- Español de Colombia, tono cercano y profesional, como lo escribiría una persona (no una empresa).\n"
        "- Breves: WhatsApp máximo 70 palabras; LinkedIn máximo 300 caracteres; correo máximo 150 palabras.\n"
        "- Centrados en UNA sola necesidad (la necesidad principal). No listes servicios.\n"
        "- Demuestra que conoces el negocio con un detalle de la evidencia, sin inventar nada.\n"
        "- Nunca afirmes que la empresa tiene problemas; formula la necesidad como pregunta.\n"
        "- Propón una conversación corta o el chequeo gratis de 45 minutos. Sin promesas de resultados.\n"
        "- Nada de mayúsculas sostenidas, emojis en exceso ni urgencia artificial.\n"
        "- El correo termina con firma y una línea para que puedan pedir no ser contactados.\n"
        "- llamada y visita: guiones paso a paso, cortos. preguntas_reunion: 5 a 7 preguntas abiertas.\n"
        f"Firma: {b.get('responsable')} · {b.get('nombre')} · WhatsApp {b.get('whatsapp')} · Instagram {b.get('instagram')}\n\n"
        "OFERTA:\n" + offer.summary_for_llm()
    )
    prompt = (
        f"Empresa: {p.get('nombre')} ({offer.sector_name(p.get('sector'))}, {p.get('ciudad') or 'ciudad no verificada'})\n"
        f"Qué hace: {brief.get('que_hace')}\n"
        f"Necesidad principal (potencial): {brief.get('necesidad_principal')}\n"
        f"Oportunidad: {brief.get('oportunidad')}\n"
        f"Servicio recomendado: {brief.get('servicio_nombre')}\n"
        f"Detalle verificable para personalizar: {_hook(p, offer)}\n"
        f"Señales: {p.get('senales') or {}}"
    )
    d = llm.json(system, prompt, schema, effort="low", max_tokens=8000)
    text_all = " ".join(str(v) for v in d.values()).lower()
    if any(ph in text_all for ph in PROHIBITED_PHRASES):
        raise LLMError("Mensajes con afirmaciones no permitidas")
    return {
        "whatsapp": {"cuerpo": d["whatsapp"]},
        "correo": {"asunto": d["correo_asunto"], "cuerpo": d["correo_cuerpo"]},
        "linkedin": {"cuerpo": d["linkedin"]},
        "llamada": {"cuerpo": d["llamada"]},
        "visita": {"cuerpo": d["visita"]},
        "preguntas_reunion": {"cuerpo": "\n".join(f"- {q}" for q in d["preguntas_reunion"])},
        "propuesta_valor": {"cuerpo": d["propuesta_valor"]},
    }


def build_messages(p: dict, brief: dict, offer: Offer, llm: LLM | None = None) -> tuple[dict[str, dict], str]:
    if llm and llm.available:
        try:
            return llm_messages(p, brief, offer, llm), "Claude"
        except LLMError:
            pass
    return rule_messages(p, brief, offer), "plantilla"
