"""Normalización de nombres, teléfonos y dominios para detectar duplicados."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse

LEGAL_SUFFIXES = r"\b(s\.?\s?a\.?\s?s\.?|s\.?\s?a\.?|ltda\.?|e\.?\s?u\.?|y\s+cia\.?|& cia\.?|limitada|sociedad por acciones simplificada)\s*$"

# Dominios que NO identifican a una empresa (redes, agregadores, link-in-bio)
NON_COMPANY_DOMAINS = {
    "instagram.com", "facebook.com", "fb.com", "linktr.ee", "linkin.bio", "wa.me", "api.whatsapp.com",
    "whatsapp.com", "tiktok.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "google.com",
    "goo.gl", "maps.app.goo.gl", "rappi.com", "rappi.com.co", "ifood.com.co", "didi-food.com", "beacons.ai",
    "taplink.cc", "bit.ly", "tripadvisor.com", "tripadvisor.co", "wixsite.com", "site.google.com",
}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.es", "live.com", "icloud.com",
    "hotmail.es", "outlook.es", "msn.com", "aol.com", "protonmail.com",
}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    n = strip_accents((name or "").lower())
    n = re.sub(r"[|·\-–—].*$", "", n) if len(n) > 25 else n  # "Café X - Sede Laureles" → "café x"
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"\bsede\b.*$", " ", n)
    n = re.sub(LEGAL_SUFFIXES, " ", n.strip())
    n = n.replace("&", " y ")
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("57") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) < 7:
        return None
    return digits[-10:]


def company_domain(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    for d in NON_COMPANY_DOMAINS:
        if host == d or host.endswith("." + d):
            return None
    return host


def is_mobile_co(phone: str | None) -> bool:
    p = normalize_phone(phone)
    return bool(p and len(p) == 10 and p.startswith("3"))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()
