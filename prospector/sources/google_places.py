"""Cliente de Google Places API (New) – Text Search.

Fuente oficial y autorizada: https://developers.google.com/maps/documentation/places/web-service/text-search
Requiere GOOGLE_PLACES_API_KEY con "Places API (New)" habilitada y facturación activa.
No se hace scraping de Google Maps.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# Solo los campos necesarios (minimización de datos y de costo).
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.location",
    "places.types",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.businessStatus",
    "places.googleMapsUri",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.editorialSummary",
    "places.delivery",
    "places.takeout",
    "nextPageToken",
])

PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "gratis",
    "PRICE_LEVEL_INEXPENSIVE": "económico",
    "PRICE_LEVEL_MODERATE": "moderado",
    "PRICE_LEVEL_EXPENSIVE": "alto",
    "PRICE_LEVEL_VERY_EXPENSIVE": "muy alto",
}


class PlacesError(RuntimeError):
    pass


@dataclass
class Place:
    place_id: str
    nombre: str
    direccion: str | None = None
    ciudad: str | None = None
    departamento: str | None = None
    pais: str | None = None
    lat: float | None = None
    lng: float | None = None
    tipos: list[str] = field(default_factory=list)
    tipo_principal: str | None = None
    tipo_principal_texto: str | None = None
    estado_negocio: str | None = None
    maps_url: str | None = None
    telefono: str | None = None
    telefono_internacional: str | None = None
    sitio_web: str | None = None
    rating: float | None = None
    num_resenas: int | None = None
    nivel_precio: str | None = None
    resumen: str | None = None
    domicilios: bool | None = None
    para_llevar: bool | None = None
    consulta: str | None = None

    @classmethod
    def from_api(cls, p: dict[str, Any], consulta: str | None = None) -> "Place":
        comps = p.get("addressComponents") or []

        def comp(kind: str) -> str | None:
            for c in comps:
                if kind in (c.get("types") or []):
                    return c.get("longText")
            return None

        loc = p.get("location") or {}
        return cls(
            place_id=p["id"],
            nombre=(p.get("displayName") or {}).get("text") or "",
            direccion=p.get("formattedAddress"),
            ciudad=comp("locality") or comp("administrative_area_level_2"),
            departamento=comp("administrative_area_level_1"),
            pais=comp("country"),
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            tipos=p.get("types") or [],
            tipo_principal=p.get("primaryType"),
            tipo_principal_texto=(p.get("primaryTypeDisplayName") or {}).get("text"),
            estado_negocio=p.get("businessStatus"),
            maps_url=p.get("googleMapsUri"),
            telefono=p.get("nationalPhoneNumber"),
            telefono_internacional=p.get("internationalPhoneNumber"),
            sitio_web=p.get("websiteUri"),
            rating=p.get("rating"),
            num_resenas=p.get("userRatingCount"),
            nivel_precio=PRICE_LEVELS.get(p.get("priceLevel") or ""),
            resumen=(p.get("editorialSummary") or {}).get("text"),
            domicilios=p.get("delivery"),
            para_llevar=p.get("takeout"),
            consulta=consulta,
        )


class GooglePlacesClient:
    def __init__(self, api_key: str, *, timeout: float = 20.0, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise PlacesError("Falta GOOGLE_PLACES_API_KEY")
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }
        self.requests_made = 0

    def text_search(
        self,
        query: str,
        *,
        max_results: int = 20,
        center: tuple[float, float] | None = None,
        radius_m: float = 20000,
        included_type: str | None = None,
    ) -> list[Place]:
        """Ejecuta una búsqueda de texto con paginación (Google entrega hasta 60 resultados)."""
        results: list[Place] = []
        token: str | None = None
        while len(results) < max_results:
            body: dict[str, Any] = {
                "textQuery": query,
                "languageCode": "es",
                "regionCode": "CO",
                "pageSize": min(20, max_results - len(results)),
            }
            if center:
                body["locationBias"] = {
                    "circle": {"center": {"latitude": center[0], "longitude": center[1]},
                               "radius": float(min(radius_m, 50000))}
                }
            if included_type:
                body["includedType"] = included_type
            if token:
                body["pageToken"] = token
            data = self._post(body)
            results += [Place.from_api(p, consulta=query) for p in data.get("places", [])]
            token = data.get("nextPageToken")
            if not token:
                break
            time.sleep(0.3)
        return results[:max_results]

    def _post(self, body: dict) -> dict:
        try:
            resp = self._client.post(ENDPOINT, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise PlacesError(f"No se pudo conectar con Google Places: {exc}") from exc
        self.requests_made += 1
        if resp.status_code == 200:
            return resp.json()
        try:
            msg = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            msg = resp.text
        hints = {
            400: "Solicitud inválida.",
            403: "Clave rechazada: verifica que la clave sea válida, que 'Places API (New)' esté habilitada y que haya facturación activa.",
            429: "Cuota de Google Places agotada; intenta más tarde o sube la cuota.",
        }
        raise PlacesError(f"Google Places respondió {resp.status_code}. {hints.get(resp.status_code, '')} Detalle: {msg[:300]}")

    def close(self) -> None:
        self._client.close()
