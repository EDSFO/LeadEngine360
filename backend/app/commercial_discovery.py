"""Bounded discovery through the official Apollo and Hunter APIs."""

import httpx

from .config import settings
from .discovery import DiscoveryConfigError, _domain


def _criteria(profile: dict) -> dict:
    criteria = profile.get("ideal_customer_profile") if isinstance(profile, dict) else None
    if not isinstance(criteria, dict):
        raise DiscoveryConfigError("O ICP precisa de critérios de busca")
    if not any(criteria.get(key) for key in ("segments", "company_size", "regions")):
        raise DiscoveryConfigError("O ICP precisa de segmento, porte ou região")
    return criteria


def _values(criteria: dict, key: str) -> list[str]:
    values = criteria.get(key) or []
    return [str(value).strip() for value in values if isinstance(value, str) and value.strip()][:5]


def _candidate(provider: str, name: str, domain: str, external_id: str, *, segment: str | None = None, region: str | None = None, employee_band: str | None = None) -> dict:
    return {
        "name": name[:240], "domain": domain, "website": f"https://{domain}" if domain else None,
        "segment": segment, "region": region, "employee_band": employee_band,
        "source": provider, "provider_id": provider, "external_id": external_id,
        "source_url": f"https://{domain}" if domain else None,
        "contact_email": None, "contact_phone": None,
    }


def build_hunter_filters(profile: dict) -> dict:
    criteria = _criteria(profile)
    segments, sizes, regions = (_values(criteria, key) for key in ("segments", "company_size", "regions"))
    filters: dict = {}
    if segments:
        filters["keywords"] = {"include": segments, "match": "any"}
    if sizes:
        filters["headcount"] = sizes
    if regions:
        countries = {"brasil": "BR", "brazil": "BR", "estados unidos": "US", "united states": "US", "portugal": "PT"}
        codes = [countries.get(region.casefold(), region.upper() if len(region) == 2 else None) for region in regions]
        if any(code is None for code in codes):
            raise DiscoveryConfigError("Hunter requer país do ICP em código ISO de duas letras ou Brasil, Portugal ou Estados Unidos")
        filters["headquarters_location"] = {"include": [{"country": code} for code in codes]}
    if not filters:
        raise DiscoveryConfigError("Configure segmento, porte ou região no ICP")
    return filters


def fetch_hunter_accounts(profile: dict) -> list[dict]:
    if not settings.hunter_api_key:
        raise DiscoveryConfigError("Configure HUNTER_API_KEY no servidor")
    filters = build_hunter_filters(profile)
    response = httpx.post("https://api.hunter.io/v2/discover", json=filters, headers={"X-API-KEY": settings.hunter_api_key}, timeout=30)
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list):
        raise ValueError("Resposta inválida do Hunter Discover")
    results = []
    for row in data[:100]:
        if not isinstance(row, dict):
            continue
        domain = _domain(row.get("domain"))
        name = row.get("organization")
        if domain and isinstance(name, str) and name.strip():
            results.append(_candidate("hunter", name.strip(), domain, domain))
    return results


def build_apollo_params(profile: dict) -> list[tuple[str, str | int]]:
    criteria = _criteria(profile)
    segments, sizes, regions = (_values(criteria, key) for key in ("segments", "company_size", "regions"))
    params: list[tuple[str, str | int]] = [("page", 1), ("per_page", 100)]
    params += [("q_organization_keyword_tags[]", value) for value in segments]
    params += [("organization_locations[]", value) for value in regions]
    for size in sizes:
        pair = size.replace("-", ",").replace("+", ",200000")
        if len(pair.split(",")) == 2 and all(part.strip().isdigit() for part in pair.split(",")):
            params.append(("organization_num_employees_ranges[]", pair))
    if len(params) == 2:
        raise DiscoveryConfigError("O ICP não contém filtros compatíveis com Apollo")
    return params


def fetch_apollo_accounts(profile: dict) -> list[dict]:
    if not settings.apollo_api_key:
        raise DiscoveryConfigError("Configure APOLLO_API_KEY no servidor")
    params = build_apollo_params(profile)
    response = httpx.post("https://api.apollo.io/api/v1/mixed_companies/search", params=params, headers={"x-api-key": settings.apollo_api_key, "Content-Type": "application/json"}, timeout=30)
    response.raise_for_status()
    data = response.json().get("organizations")
    if not isinstance(data, list):
        raise ValueError("Resposta inválida do Apollo Organization Search")
    results = []
    for row in data[:100]:
        if not isinstance(row, dict):
            continue
        name, external_id = row.get("name"), row.get("id") or row.get("organization_id")
        domain = _domain(row.get("primary_domain") or row.get("website_url"))
        if isinstance(name, str) and name.strip() and isinstance(external_id, str) and domain:
            results.append(_candidate("apollo", name.strip(), domain, external_id, segment=row.get("industry"), region=row.get("city") or row.get("country"), employee_band=str(row["estimated_num_employees"]) if row.get("estimated_num_employees") else None))
    return results


def fetch_hunter_contacts(domain: str) -> list[dict]:
    if not settings.hunter_api_key:
        raise DiscoveryConfigError("Configure HUNTER_API_KEY no servidor")
    domain = _domain(domain)
    if not domain:
        return []
    response = httpx.get("https://api.hunter.io/v2/domain-search", params={"domain": domain}, headers={"X-API-KEY": settings.hunter_api_key}, timeout=30)
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, dict) or not isinstance(data.get("emails"), list):
        raise ValueError("Resposta inválida do Hunter Domain Search")
    results = []
    for row in data["emails"][:10]:
        if not isinstance(row, dict):
            continue
        email = row.get("value")
        if not isinstance(email, str) or "@" not in email or len(email) > 320:
            continue
        name = " ".join(str(row.get(key) or "").strip() for key in ("first_name", "last_name")).strip() or None
        sources = row.get("sources") or []
        source_url = sources[0].get("uri") if isinstance(sources, list) and sources and isinstance(sources[0], dict) else None
        confidence = row.get("confidence")
        results.append({"email": email.lower(), "name": name, "title": row.get("position"), "phone": row.get("phone_number"), "kind": "person" if row.get("type") == "personal" else "general", "confidence": max(0, min(1, confidence / 100)) if isinstance(confidence, (int, float)) else 0.5, "source_url": source_url})
    return results


def fetch_hunter_company(domain: str) -> dict | None:
    """Get sourced company attributes; missing domains are a normal outcome."""
    if not settings.hunter_api_key:
        raise DiscoveryConfigError("Configure HUNTER_API_KEY no servidor")
    domain = _domain(domain)
    if not domain:
        return None
    response = httpx.get("https://api.hunter.io/v2/companies/find", params={"domain": domain}, headers={"X-API-KEY": settings.hunter_api_key}, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, dict):
        raise ValueError("Resposta inválida do Hunter Company Enrichment")
    category = data.get("category") if isinstance(data.get("category"), dict) else {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    geo = data.get("geo") if isinstance(data.get("geo"), dict) else {}
    return {
        "segment": category.get("industry") or category.get("sector"),
        "employee_band": metrics.get("employees"),
        "region": geo.get("country") or data.get("location"),
    }
