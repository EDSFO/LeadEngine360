from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .ai import generate_profile
from .config import settings
from .database import Base, engine, get_db
from .knowledge import SUPPORTED, retrieve
from .integrations import router as integrations_router
from .leads import calculate_score, router as leads_router
from .models import DocumentChunk, IcpProfile, JobRun, KnowledgeDocument, Offer, SellerCompany, TargetAccount, Tenant, User, utcnow
from .schemas import IcpUpdateIn, LoginIn, OfferIn, OnboardingIn, ProfileOut, RegisterIn
from .security import create_token, current_user, hash_password, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="LeadEngine360 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(leads_router)
app.include_router(integrations_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "leadengine360-api"}


@app.post("/api/v1/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Este e-mail já possui uma conta")
    tenant = Tenant(name=payload.company_name.strip())
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_token(user), "token_type": "bearer", "tenant_id": tenant.id, "email": user.email}


@app.post("/api/v1/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    return {"access_token": create_token(user), "token_type": "bearer", "tenant_id": user.tenant_id, "email": user.email}


@app.get("/api/v1/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, user.tenant_id)
    company = db.scalar(select(SellerCompany).where(SellerCompany.tenant_id == user.tenant_id).options(joinedload(SellerCompany.offers)))
    return {"tenant_id": user.tenant_id, "tenant_name": tenant.name, "email": user.email, "company": _company_payload(company) if company else None}


def _company_payload(company: SellerCompany) -> dict:
    return {"id": company.id, "name": company.name, "website": company.website, "description": company.description, "sales_regions": company.sales_regions, "offers": [{"id": offer.id, "name": offer.name, "category": offer.category, "description": offer.description, "problem_solved": offer.problem_solved, "differentiators": offer.differentiators, "target_customer_hint": offer.target_customer_hint, "restrictions": offer.restrictions} for offer in company.offers]}


@app.put("/api/v1/onboarding")
def save_onboarding(payload: OnboardingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = db.scalar(select(SellerCompany).where(SellerCompany.tenant_id == user.tenant_id).options(joinedload(SellerCompany.offers)))
    if company is None:
        company = SellerCompany(tenant_id=user.tenant_id, name=payload.company_name.strip())
        db.add(company)
        db.flush()
    company.name = payload.company_name.strip()
    company.website = payload.website
    company.description = payload.company_description
    company.sales_regions = payload.sales_regions
    existing = {offer.id: offer for offer in company.offers}
    received_ids: set[str] = set()
    for offer_data in payload.offers:
        data = offer_data.model_dump()
        offer_id = data.pop("id", None)
        offer = existing.get(offer_id) if offer_id else None
        if offer is None:
            offer = Offer(tenant_id=user.tenant_id, company_id=company.id, **data)
            db.add(offer)
        else:
            for key, value in data.items():
                setattr(offer, key, value)
        received_ids.add(offer.id)
    db.commit()
    saved_company = db.scalar(select(SellerCompany).where(SellerCompany.id == company.id).options(joinedload(SellerCompany.offers)).execution_options(populate_existing=True))
    return _company_payload(saved_company)


@app.get("/api/v1/onboarding")
def get_onboarding(db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = db.scalar(select(SellerCompany).where(SellerCompany.tenant_id == user.tenant_id).options(joinedload(SellerCompany.offers)))
    return _company_payload(company) if company else None


@app.post("/api/v1/offers/{offer_id}/documents", status_code=201)
async def upload_document(offer_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    filename = Path(file.filename or "documento").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(status_code=415, detail="Formato não suportado. Envie PDF, DOCX, TXT ou MD.")
    raw = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"O arquivo excede o limite de {settings.max_upload_mb} MB")
    document_id = str(uuid4())
    storage_path = Path(settings.upload_dir) / user.tenant_id / f"{document_id}{suffix}"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(raw)
    document = KnowledgeDocument(id=document_id, tenant_id=user.tenant_id, offer_id=offer.id, filename=filename, media_type=file.content_type or "application/octet-stream", status="queued")
    job = JobRun(tenant_id=user.tenant_id, job_type="document_index", entity_id=document_id, status="queued")
    db.add(document)
    db.add(job)
    previous_icp = db.scalar(select(IcpProfile).where(IcpProfile.tenant_id == user.tenant_id, IcpProfile.offer_id == offer.id))
    if previous_icp and previous_icp.status == "approved":
        previous_icp.status = "draft"
    db.commit()
    try:
        from .tasks import index_document

        index_document.delay(job.id, user.tenant_id, document.id)
    except Exception:
        document.status = "failed"
        job.status = "failed"
        job.error = "A fila de processamento está indisponível. Tente enviar o arquivo novamente."
        job.finished_at = utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="A fila de processamento está indisponível") from None
    return {"id": document.id, "filename": document.filename, "status": document.status, "job_id": job.id}


@app.get("/api/v1/offers/{offer_id}/documents")
def list_documents(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    documents = db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.offer_id == offer.id, KnowledgeDocument.tenant_id == user.tenant_id).order_by(KnowledgeDocument.created_at.desc())).all()
    return [{"id": doc.id, "filename": doc.filename, "status": doc.status, "created_at": doc.created_at} for doc in documents]


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.scalar(select(JobRun).where(JobRun.id == job_id, JobRun.tenant_id == user.tenant_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return {"id": job.id, "job_type": job.job_type, "entity_id": job.entity_id, "status": job.status, "progress": job.progress, "attempts": job.attempts, "error": job.error, "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at}


@app.post("/api/v1/offers/{offer_id}/profile", response_model=ProfileOut)
async def create_profile(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    pending_documents = db.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.offer_id == offer.id, KnowledgeDocument.tenant_id == user.tenant_id, KnowledgeDocument.status.in_(["queued", "indexing"])).limit(1))
    if pending_documents:
        raise HTTPException(status_code=409, detail="Aguarde a indexação dos documentos antes de gerar o ICP")
    company = db.scalar(select(SellerCompany).where(SellerCompany.id == offer.company_id, SellerCompany.tenant_id == user.tenant_id))
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    rows = db.execute(select(DocumentChunk.id, KnowledgeDocument.filename, DocumentChunk.content).join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id).where(DocumentChunk.tenant_id == user.tenant_id, DocumentChunk.offer_id == offer.id, KnowledgeDocument.tenant_id == user.tenant_id)).all()
    query = " ".join([offer.name, offer.description, offer.problem_solved or "", offer.differentiators or "", offer.target_customer_hint or ""])
    evidence = retrieve(query, [(row.id, row.filename, row.content) for row in rows])
    profile, model = await generate_profile({"name": company.name, "website": company.website, "description": company.description, "sales_regions": company.sales_regions}, {"name": offer.name, "category": offer.category, "description": offer.description, "problem_solved": offer.problem_solved, "differentiators": offer.differentiators, "target_customer_hint": offer.target_customer_hint, "restrictions": offer.restrictions}, evidence)
    icp = db.scalar(select(IcpProfile).where(IcpProfile.tenant_id == user.tenant_id, IcpProfile.offer_id == offer.id))
    if icp is None:
        icp = IcpProfile(tenant_id=user.tenant_id, offer_id=offer.id, version=0)
        db.add(icp)
    icp.profile_json = profile
    icp.evidence_json = [{"chunk_id": row["chunk_id"], "filename": row["filename"], "content": row["content"], "relevance": row["relevance"]} for row in evidence]
    icp.generated_with = model
    icp.status = "draft"
    icp.version = (icp.version or 0) + 1
    db.commit()
    return {"offer_id": offer.id, "generated_with": model, "profile": profile, "evidence": [{"chunk_id": row["chunk_id"], "filename": row["filename"], "content": row["content"], "relevance": row["relevance"]} for row in evidence]}


@app.get("/api/v1/offers/{offer_id}/icp")
def get_icp(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    icp = db.scalar(select(IcpProfile).where(IcpProfile.offer_id == offer_id, IcpProfile.tenant_id == user.tenant_id))
    if icp is None:
        return None
    return {"id": icp.id, "offer_id": icp.offer_id, "profile": icp.profile_json, "evidence": icp.evidence_json, "status": icp.status, "generated_with": icp.generated_with, "version": icp.version, "updated_at": icp.updated_at}


@app.put("/api/v1/offers/{offer_id}/icp")
def update_icp(offer_id: str, payload: IcpUpdateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    icp = db.scalar(select(IcpProfile).where(IcpProfile.offer_id == offer.id, IcpProfile.tenant_id == user.tenant_id))
    if icp is None:
        icp = IcpProfile(tenant_id=user.tenant_id, offer_id=offer.id, profile_json=payload.profile, status=payload.status, generated_with="user", version=1)
        db.add(icp)
    else:
        icp.profile_json = payload.profile
        icp.status = payload.status
        icp.generated_with = "user"
        icp.version += 1
    db.commit()
    db.refresh(icp)
    if icp.status == "approved":
        accounts = db.scalars(select(TargetAccount).where(TargetAccount.tenant_id == user.tenant_id, TargetAccount.offer_id == offer.id)).all()
        for account in accounts:
            calculate_score(db, account, icp)
        db.commit()
    return {"id": icp.id, "offer_id": icp.offer_id, "profile": icp.profile_json, "evidence": icp.evidence_json, "status": icp.status, "generated_with": icp.generated_with, "version": icp.version, "updated_at": icp.updated_at}
