"""Utilidades de prueba. Los transportes HTTP falsos existen SOLO en las pruebas,
para verificar el código sin gastar cuota ni depender de la red."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from prospector.agent.llm import LLM
from prospector.agent.runner import ProspectingAgent
from prospector.db import Database
from prospector.offer import load_offer
from prospector.settings import load_settings
from prospector.sources.google_places import GooglePlacesClient
from prospector.sources.website import WebsiteResearcher

ROOT = Path(__file__).resolve().parent.parent


def place(pid, name, *, types=("cafe",), primary="cafe", city="Medellín", phone=None, web=None, rating=4.6,
          reviews=120, price="PRICE_LEVEL_MODERATE", status="OPERATIONAL", delivery=None, address=None):
    return {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": address or f"Cl. 10 #{pid[-2:]}-20, {city}, Antioquia, Colombia",
        "addressComponents": [
            {"longText": city, "types": ["locality", "political"]},
            {"longText": "Antioquia", "types": ["administrative_area_level_1"]},
            {"longText": "Colombia", "types": ["country"]},
        ],
        "location": {"latitude": 6.2, "longitude": -75.57},
        "types": list(types), "primaryType": primary, "primaryTypeDisplayName": {"text": "Cafetería"},
        "businessStatus": status, "googleMapsUri": f"https://maps.google.com/?cid={pid}",
        "nationalPhoneNumber": phone, "websiteUri": web, "rating": rating, "userRatingCount": reviews,
        "priceLevel": price, "delivery": delivery,
    }


PLACES = [
    place("p01", "Café Laurel", phone="300 123 4567", web="https://cafelaurel.co", reviews=640, delivery=True),
    place("p02", "Café Laurel - Sede Envigado", city="Envigado", phone="300 123 4567", web="https://cafelaurel.co"),
    place("p03", "Juan Valdez Café", phone="604 444 1111", reviews=900),
    place("p04", "Panadería La Espiga", types=("bakery",), primary="bakery", phone="604 333 2222", reviews=40,
          price="PRICE_LEVEL_INEXPENSIVE"),
    place("p05", "Café Cerrado", status="CLOSED_PERMANENTLY"),
    place("p01", "Café Laurel", phone="300 123 4567", web="https://cafelaurel.co", reviews=640),  # repetido
]

SITE_HOME = """<html><head><meta name="description" content="Café de especialidad en Laureles y Envigado"></head>
<body><h1>Café Laurel</h1><p>Nuestras sedes: Sede Laureles, Sede Envigado. Domicilios por Rappi.</p>
<p>Fundadora: María Gómez</p>
<a href="mailto:hola@cafelaurel.co">Escríbenos</a>
<a href="https://wa.me/573001234567">WhatsApp</a>
<a href="https://www.instagram.com/cafelaurel/">IG</a>
<a href="/contacto">Contacto</a><a href="/trabaja-con-nosotros">Trabaja con nosotros</a>
<ul>""" + "".join(f"<li>Producto {i} $ {10 + i}.000</li>" for i in range(30)) + """</ul></body></html>"""
SITE_CONTACT = """<html><body><form><input type="email" name="email"><textarea name="mensaje"></textarea></form>
<p>Llámanos al 604 555 1234</p></body></html>"""
SITE_JOBS = "<html><body><h2>Vacantes</h2><p>Estamos contratando baristas</p></body></html>"


def places_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    q = body["textQuery"].lower()
    if "cafeter" in q:
        return httpx.Response(200, json={"places": PLACES})
    return httpx.Response(200, json={"places": []})


def web_handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host.endswith("cafelaurel.co"):
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /privado\n")
        pages = {"/": SITE_HOME, "/contacto": SITE_CONTACT, "/trabaja-con-nosotros": SITE_JOBS}
        if path in pages:
            return httpx.Response(200, text=pages[path], headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)
    if host.endswith("bloqueado.co"):
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})
    return httpx.Response(404)


@pytest.fixture
def offer():
    return load_offer(ROOT / "config" / "oferta.yaml")


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    return replace(s, db_path=tmp_path / "test.db", offer_path=ROOT / "config" / "oferta.yaml",
                   google_places_api_key="clave-de-prueba", anthropic_enabled=False)


@pytest.fixture
def website():
    return WebsiteResearcher("TestBot/1.0", transport=httpx.MockTransport(web_handler), delay_s=0)


@pytest.fixture
def agent(db, settings, offer, website):
    places = GooglePlacesClient("clave-de-prueba", transport=httpx.MockTransport(places_handler))
    return ProspectingAgent(db, settings, offer=offer, places=places, website=website,
                            llm=LLM(False, "claude-opus-5-5"))
