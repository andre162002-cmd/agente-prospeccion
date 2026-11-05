"""Investigación del sitio web corporativo de un prospecto.

Reglas: respeta robots.txt, identifica al bot con su User-Agent, visita pocas
páginas, no evade CAPTCHAs ni autenticación, y solo registra canales de
contacto PUBLICADOS por el propio negocio. Nunca deduce correos.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ..normalize import FREE_EMAIL_DOMAINS, company_domain, normalize_phone, strip_accents

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?57[\s.-]?)?(?:\(?60\d\)?[\s.-]?\d{3}[\s.-]?\d{4}|3\d{2}[\s.-]?\d{3}[\s.-]?\d{4})")
PRICE_RE = re.compile(r"\$\s?\d{1,3}(?:[.,]\d{3})+|\$\s?\d{4,6}\b")
ROLE_RE = re.compile(
    r"\b((?i:fundador(?:a)?|cofundador(?:a)?|propietari[oa]|gerente(?: general)?|administrador(?:a)?|directora? (?:general|administrativ[oa]|financier[oa])|ceo|chef propietari[oa]))"
    r"\s*[:\-–,]?\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2})"
)
SOCIAL_PATTERNS = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?", re.I),
    "facebook": re.compile(r"https?://(?:www\.|m\.|web\.)?facebook\.com/([A-Za-z0-9_.\-]+)/?", re.I),
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([A-Za-z0-9_\-%]+)/?", re.I),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]+)/?", re.I),
}
WHATSAPP_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send/?\?phone=|whatsapp\.com/send/?\?phone=)\+?(\d{10,13})", re.I)
INTERESTING_LINKS = re.compile(
    r"contact|contacto|nosotros|quienes|quiénes|about|historia|sedes|ubicaci|tiendas|locales|menu|menú|carta|trabaja|empleo|vacantes",
    re.I,
)
IGNORED_EMAIL_PARTS = ("sentry", "wixpress", "example.", "@2x", ".png", ".jpg", ".webp", ".gif", "domain.com", "email.com", "tuemail", "correo@")

SIGNAL_KEYWORDS = {
    "domicilios": ["domicilio", "domicilios", "rappi", "didi food", "ifood", "pide en linea", "pedidos en linea", "delivery"],
    "contratando": ["trabaja con nosotros", "vacante", "vacantes", "estamos contratando", "unete a nuestro equipo", "empleo"],
    "nueva_sede": ["nueva sede", "nuevo local", "abrimos", "inauguramos", "proximamente", "próximamente", "gran apertura"],
    "eventos_catering": ["catering", "eventos empresariales", "eventos corporativos", "pedidos corporativos"],
    "tienda_online": ["agregar al carrito", "anadir al carrito", "añadir al carrito", "checkout", "tienda en linea", "tienda online"],
    "franquicia": ["franquicia", "franquicias", "adquiere tu franquicia"],
}


@dataclass
class Finding:
    campo: str
    valor: str
    url: str
    confianza: str = "alta"
    verificacion: str = "confirmado"


@dataclass
class WebsiteResult:
    url: str
    ok: bool = False
    bloqueado_por_robots: bool = False
    error: str | None = None
    paginas: list[str] = field(default_factory=list)
    hallazgos: list[Finding] = field(default_factory=list)
    senales: dict[str, list[str]] = field(default_factory=dict)  # señal -> urls donde aparece
    descripcion: str | None = None
    precios_detectados: int = 0
    menciones_sedes: int = 0
    texto_muestra: str = ""

    def first(self, campo: str) -> Finding | None:
        return next((h for h in self.hallazgos if h.campo == campo), None)

    def values(self, campo: str) -> list[str]:
        return [h.valor for h in self.hallazgos if h.campo == campo]


class WebsiteResearcher:
    def __init__(self, user_agent: str, timeout: float = 10.0, max_pages: int = 4,
                 transport: httpx.BaseTransport | None = None, delay_s: float = 0.5):
        self.user_agent = user_agent
        self.max_pages = max_pages
        self.delay_s = delay_s
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True, transport=transport,
            headers={"User-Agent": user_agent, "Accept-Language": "es-CO,es;q=0.9"},
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    def _robots(self, base: str) -> RobotFileParser | None:
        rp = RobotFileParser()
        robots_url = urljoin(base, "/robots.txt")
        try:
            r = self._client.get(robots_url)
        except httpx.HTTPError:
            rp.parse([])  # inaccesible por red: se trata como sin restricciones explícitas
            return rp
        if r.status_code >= 500:
            return None  # servidor con error: por prudencia no rastreamos
        if r.status_code >= 400:
            rp.parse([])
        else:
            rp.parse(r.text.splitlines())
        return rp

    def research(self, url: str) -> WebsiteResult:
        if "://" not in url:
            url = "https://" + url
        result = WebsiteResult(url=url)
        domain = company_domain(url)
        if not domain:
            result.error = "El enlace no es un sitio propio (red social o agregador); se registra solo como enlace."
            return result
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots(base)
        if rp is None:
            result.error = "robots.txt no disponible (error del servidor); no se rastrea por prudencia."
            return result

        queue = [url]
        seen: set[str] = set()
        while queue and len(result.paginas) < self.max_pages:
            page = queue.pop(0)
            key = page.split("#")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            if not rp.can_fetch(self.user_agent, page):
                if not result.paginas:
                    result.bloqueado_por_robots = True
                    result.error = "El sitio no permite el rastreo automatizado (robots.txt)."
                    return result
                continue
            try:
                resp = self._client.get(page)
            except httpx.HTTPError as exc:
                if not result.paginas:
                    result.error = f"No se pudo abrir el sitio: {exc.__class__.__name__}"
                    return result
                continue
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or "html" not in ctype:
                if not result.paginas:
                    result.error = f"El sitio respondió {resp.status_code}"
                    return result
                continue
            final_url = str(resp.url)
            result.paginas.append(final_url)
            links = self._parse_page(resp.text, final_url, domain, result)
            if len(result.paginas) == 1:
                queue += links
            if self.delay_s:
                time.sleep(self.delay_s)
        result.ok = bool(result.paginas)
        self._dedupe(result)
        return result

    # ------------------------------------------------------------------
    def _parse_page(self, html: str, page_url: str, domain: str, result: WebsiteResult) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        lines = [" ".join(t.split()) for t in soup.get_text("\n").split("\n") if t.strip()]
        text = " ".join(lines)
        text_l = strip_accents(text.lower())
        if not result.texto_muestra:
            result.texto_muestra = text[:3000]

        if result.descripcion is None:
            meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta and meta.get("content"):
                result.descripcion = meta["content"].strip()[:500]

        hrefs = [a.get("href", "") for a in soup.find_all("a")]
        # Correos publicados
        emails = {h[7:].split("?")[0] for h in hrefs if h.lower().startswith("mailto:")}
        emails |= set(EMAIL_RE.findall(text))
        for e in emails:
            e = e.strip().strip(".").lower()
            if not EMAIL_RE.fullmatch(e) or any(p in e for p in IGNORED_EMAIL_PARTS):
                continue
            edomain = e.split("@")[1]
            if edomain == domain or edomain.endswith("." + domain):
                result.hallazgos.append(Finding("correo", e, page_url, "alta", "confirmado"))
            elif edomain in FREE_EMAIL_DOMAINS:
                # Publicado por el negocio en su sitio, pero en dominio gratuito: podría ser personal.
                result.hallazgos.append(Finding("correo", e, page_url, "media", "confirmado"))
        # Teléfonos
        phones = {h[4:] for h in hrefs if h.lower().startswith("tel:")}
        phones |= set(PHONE_RE.findall(text))
        for p in phones:
            n = normalize_phone(p)
            if n and len(n) == 10:
                result.hallazgos.append(Finding("telefono", n, page_url))
        # WhatsApp empresarial publicado
        for h in hrefs:
            m = WHATSAPP_RE.search(h)
            if m:
                n = normalize_phone(m.group(1))
                if n:
                    result.hallazgos.append(Finding("whatsapp", n, page_url))
        # Redes sociales
        for h in hrefs:
            for red, rx in SOCIAL_PATTERNS.items():
                m = rx.match(h)
                if m and m.group(1).lower() not in {"sharer", "share", "intent", "p", "reel", "explore", "tr", "plugins", "dialog"}:
                    result.hallazgos.append(Finding(red, h.split("?")[0], page_url))
        # Formulario de contacto
        for form in soup.find_all("form"):
            fields = " ".join(str(i) for i in form.find_all(["input", "textarea"])).lower()
            if "textarea" in fields or "email" in fields or "mensaje" in fields:
                result.hallazgos.append(Finding("formulario_contacto", page_url, page_url))
                break
        # Personas con cargo publicadas explícitamente en el sitio
        for line in lines:  # línea por línea, para no unir el nombre con el texto vecino
            for m in ROLE_RE.finditer(line):
                cargo, nombre = m.group(1), m.group(2)
                result.hallazgos.append(Finding("contacto", f"{nombre} | {cargo.capitalize()}", page_url, "media", "confirmado"))
        # Señales comerciales
        for senal, words in SIGNAL_KEYWORDS.items():
            if any(strip_accents(w) in text_l for w in words):
                result.senales.setdefault(senal, []).append(page_url)
        result.precios_detectados = max(result.precios_detectados, len(PRICE_RE.findall(text)))
        result.menciones_sedes = max(result.menciones_sedes, len(re.findall(r"\bsede\b", text_l)))

        # Enlaces internos interesantes para la siguiente visita
        out = []
        for h in hrefs:
            if not h or h.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urljoin(page_url, h)
            if company_domain(absolute) == domain and INTERESTING_LINKS.search(absolute):
                out.append(absolute)
        return out[:8]

    @staticmethod
    def _dedupe(result: WebsiteResult) -> None:
        seen, unique = set(), []
        for h in result.hallazgos:
            key = (h.campo, h.valor.lower().rstrip("/"))
            if key not in seen:
                seen.add(key)
                unique.append(h)
        result.hallazgos = unique
        for k in result.senales:
            result.senales[k] = sorted(set(result.senales[k]))
