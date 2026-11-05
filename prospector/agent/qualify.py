"""Calificación de leads (0–100), explicada criterio por criterio.

Principios:
- Cada punto se justifica con evidencia registrada; lo no verificado no suma
  como positivo (se marca "no disponible" o "estimado").
- Seguidores, likes o un sitio web atractivo NO suman puntos. Lo que pesa es
  la relación entre necesidades potenciales y nuestra oferta.
- Los pesos vienen de config/oferta.yaml y cambian según el servicio objetivo.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..normalize import FREE_EMAIL_DOMAINS, is_mobile_co
from ..offer import Offer

LABELS = {
    "icp": "Coincidencia con el cliente ideal",
    "necesidad": "Necesidad potencial de nuestros servicios",
    "capacidad": "Capacidad estimada de contratación",
    "accesibilidad": "Accesibilidad del contacto comercial",
    "crecimiento": "Señales de crecimiento o necesidad empresarial",
    "geografia": "Ubicación geográfica prioritaria",
}


@dataclass
class Criterion:
    factor: float = 0.0
    razones: list[str] | None = None

    def add(self, delta: float, razon: str) -> None:
        self.factor += delta
        (self.razones if self.razones is not None else []).append(razon)

    def clamp(self) -> float:
        self.factor = max(0.0, min(1.0, self.factor))
        return self.factor


def _c() -> Criterion:
    return Criterion(0.0, [])


def _senal(p: dict, key: str) -> bool:
    return bool((p.get("senales") or {}).get(key))


def score_prospect(p: dict, offer: Offer, servicio_objetivo: str | None = None) -> dict:
    sector = p.get("sector")
    prio = offer.sector_priority(sector)
    sedes = int(p.get("num_sedes") or 1)
    resenas = int(p.get("num_resenas") or 0)
    max_sedes = int(offer.icp.get("max_sedes_independiente", 8))
    descartes: list[str] = []

    # --- ICP ------------------------------------------------------------
    icp = _c()
    if prio == 1:
        icp.add(0.6, f"Sector {offer.sector_name(sector)}: es el nicho actual de la oferta.")
    elif prio == 2:
        icp.add(0.35, f"Sector {offer.sector_name(sector)}: mercado de expansión, no el nicho principal.")
    else:
        icp.add(0.1, "Sector fuera del foco actual o sin clasificar.")
    if offer.is_excluded_chain(p.get("nombre", "")):
        icp.factor = 0
        icp.razones.append("Cadena o franquicia grande de la lista de exclusión (tiene área financiera propia).")
        descartes.append("Cadena/franquicia grande")
    elif sedes > max_sedes:
        icp.factor *= 0.3
        icp.razones.append(f"{sedes} sedes: por tamaño probablemente ya tiene equipo financiero.")
        descartes.append("Demasiadas sedes para el cliente ideal")
    else:
        icp.add(0.15, "Negocio independiente (no figura como gran cadena).")
    if _senal(p, "franquicia"):
        icp.add(-0.3, "Su sitio menciona franquicias: decisiones financieras posiblemente centralizadas.")
    estado = p.get("estado_negocio")
    if estado == "OPERATIONAL":
        icp.add(0.15, "Google lo reporta en operación.")
    elif estado and estado.startswith("CLOSED"):
        icp.factor = 0
        icp.razones.append(f"Google lo reporta cerrado ({estado}).")
        descartes.append("Negocio cerrado")
    if resenas >= 30:
        icp.add(0.1, f"{resenas} reseñas en Google: señal de operación estable (estimado; la antigüedad no está verificada).")

    # --- Necesidad ------------------------------------------------------
    nec = _c()
    svc = offer.service(servicio_objetivo)
    if prio <= 2 and sector:
        nec.add(0.45, f"En {offer.sector_name(sector)} son habituales necesidades que atiende la oferta (costos, márgenes, caja).")
    else:
        nec.add(0.1, "Sin relación clara entre el sector y la oferta.")
    if p.get("senales", {}).get("domicilios") or p.get("senales", {}).get("domicilios_google"):
        nec.add(0.15, "Vende por domicilios: las comisiones de las apps presionan el margen (oportunidad por validar).")
    if sedes >= 2:
        nec.add(0.15, f"{sedes} sedes: controlar costos y márgenes entre puntos es más complejo.")
    precios = int((p.get("senales") or {}).get("precios_detectados") or 0)
    if precios >= 25:
        nec.add(0.1, f"Carta amplia publicada (~{precios} precios): útil una matriz de menú.")
    elif precios >= 10:
        nec.add(0.05, f"Carta publicada con ~{precios} precios.")
    if resenas >= 300:
        nec.add(0.1, "Alto volumen de clientes (muchas reseñas): pequeñas fugas de margen pesan más.")
    if _senal(p, "nueva_sede") or _senal(p, "contratando"):
        nec.add(0.05, "Señales de expansión: más gasto y decisiones de inversión.")
    if svc and sector and sector not in svc.get("sectores", []):
        nec.factor *= 0.4
        nec.razones.append(f"El servicio objetivo ({svc['nombre']}) no está pensado para este sector.")

    # --- Capacidad ------------------------------------------------------
    cap = _c()
    nivel = p.get("nivel_precio")
    if nivel in ("alto", "muy alto"):
        cap.add(0.6, f"Nivel de precios {nivel} en Google.")
    elif nivel == "moderado":
        cap.add(0.5, "Nivel de precios moderado en Google.")
    elif nivel == "económico":
        cap.add(0.25, "Nivel de precios económico: menor margen para contratar servicios.")
    else:
        cap.add(0.3, "Nivel de precios no disponible (valor neutro estimado).")
    if sedes >= 4:
        cap.add(0.3, f"{sedes} sedes.")
    elif sedes >= 2:
        cap.add(0.2, f"{sedes} sedes.")
    if resenas >= 500:
        cap.add(0.15, "Volumen alto de clientes (500+ reseñas).")
    elif resenas >= 150:
        cap.add(0.1, "Volumen medio-alto de clientes (150+ reseñas).")
    if p.get("dominio"):
        cap.add(0.05, "Tiene sitio web propio.")

    # --- Accesibilidad --------------------------------------------------
    acc = _c()
    if p.get("whatsapp"):
        acc.add(0.6, "WhatsApp empresarial publicado.")
    elif p.get("telefono"):
        if is_mobile_co(p.get("telefono")):
            acc.add(0.5, "Celular comercial publicado (WhatsApp por confirmar).")
        else:
            acc.add(0.35, "Teléfono fijo comercial publicado.")
    correo = p.get("correo") or ""
    if correo:
        if correo.split("@")[-1] in FREE_EMAIL_DOMAINS:
            acc.add(0.15, "Correo publicado (dominio gratuito).")
        else:
            acc.add(0.25, "Correo corporativo publicado.")
    if p.get("formulario_contacto"):
        acc.add(0.1, "Formulario de contacto en su sitio.")
    if p.get("instagram"):
        acc.add(0.15, "Perfil de Instagram del negocio (canal de mensaje directo).")
    if p.get("contacto_nombre"):
        acc.add(0.15, "Responsable identificado en fuente pública.")
    if not acc.razones:
        acc.razones.append("No se encontraron canales de contacto publicados.")

    # --- Crecimiento ----------------------------------------------------
    cre = _c()
    if sedes >= 2:
        cre.add(0.4, f"Opera {sedes} sedes.")
    if _senal(p, "nueva_sede"):
        cre.add(0.4, "Anuncia nueva sede o apertura.")
    if _senal(p, "contratando"):
        cre.add(0.3, "Publica vacantes o 'trabaja con nosotros'.")
    if _senal(p, "eventos_catering") or _senal(p, "tienda_online"):
        cre.add(0.1, "Diversifica canales (catering, eventos o tienda en línea).")
    if not cre.razones:
        cre.razones.append("Sin señales públicas verificadas de crecimiento (no significa que no existan).")

    # --- Geografía ------------------------------------------------------
    geo = _c()
    geo_cfg = offer.geography
    city = p.get("ciudad")
    canon = offer.canonical_city(city) or offer.canonical_city(p.get("direccion"))
    if canon:
        geo.add(float(offer.cities[canon]), f"{canon}: zona {'prioritaria' if offer.cities[canon] >= 0.8 else 'secundaria'} del Valle de Aburrá.")
    elif city and "antioquia" in (p.get("direccion") or "").lower():
        geo.add(float(geo_cfg.get("puntaje_resto_antioquia", 0.4)), f"{city}: Antioquia, fuera del Valle de Aburrá.")
    elif city and "colombia" in (p.get("direccion") or "").lower():
        geo.add(float(geo_cfg.get("puntaje_resto_colombia", 0.2)), f"{city}: fuera de Antioquia.")
    elif city:
        geo.add(float(geo_cfg.get("puntaje_otro_pais", 0.1)), f"{city}: fuera de la zona de cobertura actual.")
    else:
        geo.add(0.3, "Ciudad no verificada.")

    criterios = {"icp": icp, "necesidad": nec, "capacidad": cap, "accesibilidad": acc, "crecimiento": cre, "geografia": geo}
    pesos = offer.weights(servicio_objetivo)
    detalle = {}
    total = 0.0
    for key, crit in criterios.items():
        f = crit.clamp()
        peso = float(pesos.get(key, 0))
        puntos = round(peso * f, 1)
        total += puntos
        detalle[key] = {"nombre": LABELS[key], "peso": peso, "factor": round(f, 2), "puntos": puntos,
                        "razones": crit.razones}
    total = round(min(100.0, total))
    if descartes:
        total = min(total, 30)
    return {
        "total": total,
        "clasificacion": offer.classify(total),
        "criterios": detalle,
        "servicio_objetivo": servicio_objetivo,
        "descartes": descartes,
        "nota": "Puntaje basado en evidencia pública registrada; los seguidores en redes no suman puntos.",
    }
