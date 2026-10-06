"""Bounded OpenStreetMap discovery from an approved ICP.

The first connector covers geographic business niches with an OSM tag and a
small bounding box. Other ICPs need a provider with matching data coverage.
"""

import re
from urllib.parse import urlparse

import httpx

from .config import settings

MAX_RESULTS = 200
_TAG = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
_VALUE = re.compile(r"^[\w .:/()&+-]{1,100}$", re.UNICODE)


class DiscoveryConfigError(ValueError):
    pass


def validate_osm_discovery(profile: dict) -> tuple[str, str, tuple[float, float, float, float]]:
    discovery = profile.get("discovery")
    if not isinstance(discovery, dict):
        raise DiscoveryConfigError("Configure discovery.osm_tag e discovery.bbox no ICP")
    tag = discovery.get("osm_tag")
    if not isinstance(tag, dict):
        raise DiscoveryConfigError("discovery.osm_tag deve conter key e value")
    key, value = tag.get("key"), tag.get("value")
    if not isinstance(key, str) or not _TAG.fullmatch(key) or not isinstance(value, str) or not _VALUE.fullmatch(value):
        raise DiscoveryConfigError("Tag OSM inválida")
    bbox = discovery.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in bbox):
        raise DiscoveryConfigError("discovery.bbox deve ser [sul, oeste, norte, leste]")
    south, west, north, east = map(float, bbox)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise DiscoveryConfigError("Coordenadas da área de busca inválidas")
    if north - south > 1 or east - west > 1:
        raise DiscoveryConfigError("A área de busca excede o limite de um grau por eixo")
    segment_label = discovery.get("segment_label")
    if segment_label is not None:
        segments = (profile.get("ideal_customer_profile") or {}).get("segments", [])
        if not isinstance(segment_label, str) or segment_label not in segments:
            raise DiscoveryConfigError("O segmento associado à tag OSM deve existir no ICP aprovado")
    return key, value, (south, west, north, east)


def overpass_query(profile: dict) -> str:
    key, value, bbox = validate_osm_discovery(profile)
    coords = ",".join(str(n) for n in bbox)
    return f'[out:json][timeout:25];nwr["{key}"="{value}"]({coords});out center {MAX_RESULTS};'


def _domain(raw: str | None) -> str | None:
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")
    return host[:253] if host and "." in host and " " not in host else None


def _contact_value(raw: object, kind: str) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.split(";")[0].strip()
    if kind == "email":
        return value.lower() if len(value) <= 320 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) else None
    return value if 5 <= len(value) <= 80 and re.fullmatch(r"[+()0-9 .-]+", value) else None


def fetch_osm_accounts(profile: dict) -> list[dict]:
    query = overpass_query(profile)
    response = httpx.post(settings.overpass_url, data={"data": query}, timeout=35, headers={"User-Agent": "LeadEngine360/0.1 (business discovery)"})
    response.raise_for_status()
    payload = response.json()
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("Resposta da fonte não contém elementos")
    results = []
    for item in elements[:MAX_RESULTS]:
        if not isinstance(item, dict) or not isinstance(item.get("tags"), dict):
            continue
        tags = item["tags"]
        name = tags.get("name")
        website = tags.get("website") or tags.get("contact:website")
        if not isinstance(website, str):
            website = None
        domain = _domain(website)
        element_type, element_id = item.get("type"), item.get("id")
        if not isinstance(name, str) or not name.strip() or element_type not in ("node", "way", "relation") or not isinstance(element_id, int):
            continue
        results.append({
            "name": name.strip()[:240],
            "domain": domain,
            "website": website[:500] if website else None,
            "segment": profile["discovery"].get("segment_label") or tags.get("amenity") or tags.get("shop") or tags.get("office"),
            "region": tags.get("addr:city") or tags.get("addr:state"),
            "source": "osm-overpass",
            "external_id": f"{element_type}/{element_id}",
            "source_url": f"https://www.openstreetmap.org/{element_type}/{element_id}",
            "contact_email": _contact_value(tags.get("contact:email") or tags.get("email"), "email"),
            "contact_phone": _contact_value(tags.get("contact:phone") or tags.get("phone"), "phone"),
        })
    return results
