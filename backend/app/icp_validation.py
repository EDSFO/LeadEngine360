"""Validate the ICP fields that drive discovery and Fit scoring."""

import math

from fastapi import HTTPException


FIT_FIELDS = ("segments", "company_size", "regions")


def validate_approved_icp(profile: dict) -> None:
    criteria = profile.get("ideal_customer_profile")
    if not isinstance(criteria, dict):
        raise HTTPException(status_code=422, detail="O ICP precisa de critérios de segmento, porte ou região")

    configured = 0
    for field in FIT_FIELDS:
        values = criteria.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise HTTPException(status_code=422, detail=f"Critério {field} deve ser uma lista de textos não vazios")
        configured += bool(values)
    if not configured:
        raise HTTPException(status_code=422, detail="Informe ao menos um segmento, porte ou região antes de aprovar o ICP")

    required = criteria.get("required", [])
    if not isinstance(required, list) or any(field not in FIT_FIELDS or not criteria.get(field) for field in required) or len(required) != len(set(required)):
        raise HTTPException(status_code=422, detail="Critérios obrigatórios devem referir campos configurados sem repetição")

    for field in ("exclusions", "buyer_roles"):
        values = criteria.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise HTTPException(status_code=422, detail=f"Critério {field} deve ser uma lista de textos não vazios")

    weights = criteria.get("weights", profile.get("weights", {}))
    if not isinstance(weights, dict) or any(key not in FIT_FIELDS for key in weights):
        raise HTTPException(status_code=422, detail="Pesos do ICP inválidos")
    for value in weights.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise HTTPException(status_code=422, detail="Os pesos do ICP devem ser números positivos")

    thresholds = profile.get("classification_thresholds", {})
    if not isinstance(thresholds, dict):
        raise HTTPException(status_code=422, detail="Limiares de classificação inválidos")
    levels = {"hot": 80, "warm": 60, "target": 40}
    for key in levels:
        value = thresholds.get(key, levels[key])
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise HTTPException(status_code=422, detail=f"Limiar {key} deve ser inteiro entre 0 e 100")
        levels[key] = value
    if not levels["hot"] > levels["warm"] > levels["target"]:
        raise HTTPException(status_code=422, detail="Os limiares devem seguir hot > warm > target")
    minimum_fit = thresholds.get("minimum_hot_fit", 24)
    minimum_confidence = thresholds.get("minimum_hot_confidence", 0.6)
    if isinstance(minimum_fit, bool) or not isinstance(minimum_fit, int) or not 0 <= minimum_fit <= 40:
        raise HTTPException(status_code=422, detail="minimum_hot_fit deve ser inteiro entre 0 e 40")
    if isinstance(minimum_confidence, bool) or not isinstance(minimum_confidence, (int, float)) or not math.isfinite(minimum_confidence) or not 0 <= minimum_confidence <= 1:
        raise HTTPException(status_code=422, detail="minimum_hot_confidence deve estar entre 0 e 1")
