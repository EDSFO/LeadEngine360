"""Provider catalog for the sales-intelligence workflow.

Catalog entries describe product direction; only entries marked available are
currently callable by the MVP. Credentials and provider payloads are never
stored in this selection table.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Offer, OfferSourceSelection, User
from .security import current_user, require_roles

router = APIRouter()

CATALOG = [
    {"id": "osm-overpass", "stage": "Descoberta de empresas", "name": "OpenStreetMap / Overpass", "providers": "OpenStreetMap", "type": "open", "status": "available", "description": "Busca negócios com site por tag OSM e área geográfica configuradas no ICP. Cobertura varia por nicho e região; requer worker ativo."},
    {"id": "apollo", "stage": "Fornecedores de leads", "name": "Apollo.io", "providers": "Apollo.io", "type": "commercial", "status": "available", "description": "Busca empresas pela API oficial. Requer APOLLO_API_KEY e acesso do plano ao Organization Search."},
    {"id": "hunter", "stage": "Fornecedores de leads", "name": "Hunter", "providers": "Hunter", "type": "commercial", "status": "available", "description": "Discover busca empresas; Domain Search encontra contatos em domínios encontrados. Requer HUNTER_API_KEY e cota disponível."},
    {"id": "linkedin-sales-nav", "stage": "Fornecedores de leads", "name": "LinkedIn Sales Navigator", "providers": "LinkedIn", "type": "commercial", "status": "planned", "description": "Entrada por integração/exportação autorizada; automação de navegação não faz parte do MVP."},
    {"id": "ocean", "stage": "Fornecedores de leads", "name": "Ocean.io", "providers": "Ocean.io", "type": "commercial", "status": "planned", "description": "Conector de descoberta/enriquecimento sujeito a API e contrato."},
    {"id": "hubspot", "stage": "Leads de marketing inbound", "name": "HubSpot", "providers": "HubSpot", "type": "commercial", "status": "planned", "description": "Integração oficial/API ou webhook após configurar credenciais."},
    {"id": "inbound-webhook", "stage": "Leads de marketing inbound", "name": "Webhook de entrada", "providers": "Integração própria", "type": "open", "status": "planned", "description": "Receber leads de formulários e automações compatíveis."},
    {"id": "contact-enrichment", "stage": "Mapeamento de e-mail e telefone", "name": "Enriquecimento de contatos", "providers": "Prospeo · LeadMagic · LeadIQ", "type": "commercial", "status": "planned", "description": "Adaptadores de API opcionais; não há base aberta equivalente com cobertura geral."},
    {"id": "public-intent", "stage": "Sinais de interesse de compra", "name": "Sinais públicos e registrados", "providers": "LeadEngine360", "type": "open", "status": "available", "description": "Registro manual com fonte, evidência, data e confiança; pontuação considera força e recência."},
    {"id": "intent-provider", "stage": "Sinais de interesse de compra", "name": "Provedores de intenção", "providers": "PredictLeads · RE2B e similares", "type": "commercial", "status": "planned", "description": "Conectores opcionais para dados de intenção fornecidos por terceiros."},
    {"id": "whatweb", "stage": "Mapeamento de tecnologia", "name": "WhatWeb", "providers": "WhatWeb", "type": "open", "status": "planned", "description": "Fingerprinting de tecnologias detectáveis em sites públicos."},
    {"id": "builtwith", "stage": "Mapeamento de tecnologia", "name": "BuiltWith / PredictLeads", "providers": "BuiltWith · PredictLeads", "type": "commercial", "status": "planned", "description": "Fontes comerciais opcionais para cobertura e histórico ampliados."},
    {"id": "crawl4ai", "stage": "Extração pública", "name": "Crawl4AI", "providers": "Crawl4AI", "type": "open", "status": "planned", "description": "Crawler self-hosted para sites públicos autorizados, com limites e lista de domínios permitidos."},
    {"id": "apify", "stage": "Extração pública", "name": "Apify", "providers": "Apify", "type": "commercial", "status": "planned", "description": "Plataforma de extração opcional via API."},
    {"id": "ai-openrouter", "stage": "Análise e escrita", "name": "OpenRouter", "providers": "OpenRouter", "type": "commercial", "status": "available", "description": "Gera ICP e briefs com o modelo configurado quando a chave de API está disponível; há fallback heurístico."},
    {"id": "outbound-manual", "stage": "Outbound e CRM", "name": "Exportação e execução humana", "providers": "CSV · equipe comercial", "type": "open", "status": "available", "description": "Exporta contas priorizadas; atividade e resultado são registrados no sistema."},
    {"id": "mautic", "stage": "Outbound e CRM", "name": "Mautic / Twenty", "providers": "Mautic · Twenty", "type": "open", "status": "planned", "description": "Possíveis integrações self-hosted para automação consentida e CRM."},
    {"id": "salesloft", "stage": "Outbound e CRM", "name": "Salesloft / HeyReach", "providers": "Salesloft · HeyReach", "type": "commercial", "status": "planned", "description": "Integração futura via API oficial e credenciais do cliente."},
]
CATALOG_BY_ID = {item["id"]: item for item in CATALOG}


class SelectionIn(BaseModel):
    provider_ids: list[str] = Field(max_length=40)


@router.get("/api/v1/integrations/catalog")
def get_catalog():
    return {"items": CATALOG}


@router.get("/api/v1/offers/{offer_id}/integrations")
def get_offer_integrations(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    rows = db.scalars(select(OfferSourceSelection).where(OfferSourceSelection.offer_id == offer.id, OfferSourceSelection.tenant_id == user.tenant_id, OfferSourceSelection.enabled.is_(True))).all()
    return {"provider_ids": [row.provider_id for row in rows if row.provider_id in CATALOG_BY_ID]}


@router.put("/api/v1/offers/{offer_id}/integrations")
def save_offer_integrations(offer_id: str, payload: SelectionIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "analyst"))):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    unknown = sorted(set(payload.provider_ids) - CATALOG_BY_ID.keys())
    if unknown:
        raise HTTPException(status_code=422, detail=f"Conectores desconhecidos: {', '.join(unknown)}")
    if len(set(payload.provider_ids)) != len(payload.provider_ids):
        raise HTTPException(status_code=422, detail="A lista contém conectores repetidos")
    rows = db.scalars(select(OfferSourceSelection).where(OfferSourceSelection.offer_id == offer.id, OfferSourceSelection.tenant_id == user.tenant_id)).all()
    existing = {row.provider_id: row for row in rows}
    wanted = set(payload.provider_ids)
    for provider_id, row in existing.items():
        row.enabled = provider_id in wanted
    for provider_id in wanted - existing.keys():
        db.add(OfferSourceSelection(tenant_id=user.tenant_id, offer_id=offer.id, provider_id=provider_id, enabled=True))
    db.commit()
    return {"provider_ids": sorted(wanted), "saved": True, "note": "Preferências salvas. Apollo e Hunter exigem chaves configuradas no servidor e acesso do plano aos endpoints."}
