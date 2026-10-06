import asyncio
import logging
from pathlib import Path

from sqlalchemy import delete, func, select

from .config import settings
from .database import SessionLocal
from .knowledge import extract_text, split_chunks
from .models import AccountBrief, AccountContact, AccountSource, DocumentChunk, IcpProfile, IntentSignal, JobRun, KnowledgeDocument, Offer, OfferSourceSelection, TargetAccount, WorkflowRun, WorkflowStep, utcnow
from .workflow import ensure_run, set_step
from .worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, name="leadengine360.index_document")
def index_document(self, job_id: str, tenant_id: str, document_id: str):
    db = SessionLocal()
    job = db.scalar(select(JobRun).where(JobRun.id == job_id, JobRun.tenant_id == tenant_id))
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.tenant_id == tenant_id))
    if job is None or document is None:
        db.close()
        return {"status": "discarded"}
    if job.status == "completed" and document.status == "indexed":
        db.close()
        return {"status": "completed"}
    job.status = "processing"
    job.attempts = self.request.retries + 1
    job.progress = 10
    job.started_at = job.started_at or utcnow()
    document.status = "indexing"
    db.commit()
    try:
        suffix = Path(document.filename).suffix.lower()
        path = Path(settings.upload_dir) / tenant_id / f"{document.id}{suffix}"
        text = extract_text(document.filename, path.read_bytes())
        chunks = split_chunks(text)
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id, DocumentChunk.tenant_id == tenant_id))
        for index, content in enumerate(chunks):
            db.add(DocumentChunk(tenant_id=tenant_id, offer_id=document.offer_id, document_id=document.id, chunk_index=index, content=content))
        document.status = "indexed"
        job.status = "completed"
        job.progress = 100
        job.error = None
        job.finished_at = utcnow()
        db.commit()
        return {"status": "completed", "chunks": len(chunks)}
    except Exception as exc:
        db.rollback()
        logger.exception("document_indexing_failed", extra={"job_id": job_id, "tenant_id": tenant_id, "document_id": document_id})
        job = db.scalar(select(JobRun).where(JobRun.id == job_id, JobRun.tenant_id == tenant_id))
        document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.tenant_id == tenant_id))
        if self.request.retries < self.max_retries:
            if job:
                job.status = "retrying"
                job.error = "Falha temporária ao processar o documento"
            if document:
                document.status = "queued"
            db.commit()
            raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1)))
        if job:
            job.status = "failed"
            job.error = "Não foi possível extrair e indexar este documento"
            job.finished_at = utcnow()
        if document:
            document.status = "failed"
        db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, rate_limit="2/m", name="leadengine360.discover_accounts")
def discover_accounts(self, job_id: str, tenant_id: str, offer_id: str):
    from .discovery import fetch_osm_accounts
    from .leads import calculate_score

    db = SessionLocal()
    try:
        job = db.scalar(select(JobRun).where(JobRun.id == job_id, JobRun.tenant_id == tenant_id, JobRun.entity_id == offer_id))
        offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == tenant_id))
        icp = db.scalar(select(IcpProfile).where(IcpProfile.offer_id == offer_id, IcpProfile.tenant_id == tenant_id))
        if job is None or offer is None or icp is None or icp.status != "approved":
            return {"status": "discarded"}
        if job.status == "completed":
            return {"status": "completed"}
        job.status = "processing"
        job.attempts = self.request.retries + 1
        job.started_at = job.started_at or utcnow()
        job.progress = 10
        db.commit()

        provider_id = job.provider_id or "osm-overpass"
        if provider_id == "osm-overpass":
            candidates = fetch_osm_accounts(icp.profile_json)
        elif provider_id == "hunter":
            from .commercial_discovery import fetch_hunter_accounts
            candidates = fetch_hunter_accounts(icp.profile_json)
        elif provider_id == "apollo":
            from .commercial_discovery import fetch_apollo_accounts
            candidates = fetch_apollo_accounts(icp.profile_json)
        else:
            raise ValueError("Fonte de descoberta desconhecida")
        created = updated = 0
        seen = set()
        account_ids = set()
        for data in candidates:
            external_id = data["external_id"]
            if external_id in seen:
                continue
            seen.add(external_id)
            source = db.scalar(select(AccountSource).where(
                AccountSource.tenant_id == tenant_id, AccountSource.offer_id == offer_id,
                AccountSource.provider_id == provider_id, AccountSource.external_id == external_id,
            ))
            account = db.scalar(select(TargetAccount).where(TargetAccount.id == source.account_id, TargetAccount.tenant_id == tenant_id, TargetAccount.offer_id == offer_id)) if source else None
            if account is None and data.get("domain"):
                account = db.scalar(select(TargetAccount).where(TargetAccount.tenant_id == tenant_id, TargetAccount.offer_id == offer_id, TargetAccount.domain == data["domain"]))
            if account is None:
                values = {key: data.get(key) for key in ("name", "domain", "website", "segment", "employee_band", "region", "source")}
                account = TargetAccount(tenant_id=tenant_id, offer_id=offer_id, **values)
                db.add(account)
                db.flush()
                created += 1
            else:
                for key in ("name", "website", "segment", "employee_band", "region"):
                    if data.get(key):
                        setattr(account, key, data[key])
                updated += 1
            if source is None:
                db.add(AccountSource(tenant_id=tenant_id, offer_id=offer_id, account_id=account.id, provider_id=provider_id, external_id=external_id, source_url=data["source_url"]))
            else:
                source.observed_at = utcnow()
            contact = db.scalar(select(AccountContact).where(
                AccountContact.tenant_id == tenant_id, AccountContact.account_id == account.id,
                AccountContact.source_provider == provider_id, AccountContact.source_ref == external_id,
            ))
            email, phone = data.get("contact_email"), data.get("contact_phone")
            if email or phone:
                if contact is None:
                    contact = AccountContact(tenant_id=tenant_id, account_id=account.id, kind="general", source_provider=provider_id, source_ref=external_id)
                    db.add(contact)
                contact.email = email
                contact.phone = phone
                contact.source_url = data["source_url"]
                contact.observed_at = utcnow()
            elif contact is not None:
                db.delete(contact)
            calculate_score(db, account, icp)
            account_ids.add(account.id)
        runs = [ensure_run(db, tenant_id, offer_id, account_id, job.id) for account_id in sorted(account_ids)]
        job.progress = 80
        db.commit()
        failed_enqueue = 0
        for run in runs:
            if run.status == "completed":
                continue
            try:
                process_account.delay(run.id, tenant_id)
            except Exception:
                logger.exception("account_workflow_enqueue_failed", extra={"run_id": run.id, "tenant_id": tenant_id})
                run.status = "failed"
                run.error = "A fila de processamento da conta está indisponível"
                run.finished_at = utcnow()
                failed_enqueue += 1
        job.status = "failed" if failed_enqueue else "completed"
        job.progress = 80 if failed_enqueue else 100
        job.error = f"{failed_enqueue} conta(s) não foram enfileiradas" if failed_enqueue else None
        job.finished_at = utcnow()
        db.commit()
        return {"status": job.status, "created": created, "updated": updated, "candidates": len(candidates), "workflows": len(runs), "enqueue_failed": failed_enqueue}
    except Exception as exc:
        db.rollback()
        logger.exception("account_discovery_failed", extra={"job_id": job_id, "tenant_id": tenant_id, "offer_id": offer_id})
        job = db.scalar(select(JobRun).where(JobRun.id == job_id, JobRun.tenant_id == tenant_id))
        if job:
            if self.request.retries < self.max_retries:
                job.status = "retrying"
                job.error = "Falha temporária na fonte de descoberta"
                db.commit()
                raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)))
            job.status = "failed"
            job.error = "Não foi possível concluir a descoberta de contas"
            job.finished_at = utcnow()
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, rate_limit="12/m", name="leadengine360.process_account")
def process_account(self, run_id: str, tenant_id: str):
    from .leads import calculate_score, generate_and_store_brief

    db = SessionLocal()
    current_step = None
    try:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.tenant_id == tenant_id))
        if run is None:
            return {"status": "discarded"}
        if run.status == "completed":
            return {"status": "completed"}
        account = db.scalar(select(TargetAccount).where(TargetAccount.id == run.account_id, TargetAccount.tenant_id == tenant_id, TargetAccount.offer_id == run.offer_id))
        offer = db.scalar(select(Offer).where(Offer.id == run.offer_id, Offer.tenant_id == tenant_id))
        icp = db.scalar(select(IcpProfile).where(IcpProfile.offer_id == run.offer_id, IcpProfile.tenant_id == tenant_id))
        if account is None or offer is None or icp is None or icp.status != "approved":
            run.status = "failed"
            run.error = "Conta, oferta ou ICP aprovado não está disponível"
            run.finished_at = utcnow()
            db.commit()
            return {"status": "failed"}
        run.status = "processing"
        run.attempts = self.request.retries + 1
        run.started_at = run.started_at or utcnow()
        run.error = None
        db.commit()

        current_step = "source"
        hunter_enabled = db.scalar(select(OfferSourceSelection.id).where(
            OfferSourceSelection.tenant_id == tenant_id, OfferSourceSelection.offer_id == offer.id,
            OfferSourceSelection.provider_id == "hunter", OfferSourceSelection.enabled.is_(True),
        ))
        source_step = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.name == "source"))
        enriched = False
        if hunter_enabled and account.domain and settings.hunter_api_key and (source_step is None or source_step.status != "completed") and (not account.segment or not account.employee_band or not account.region):
            from .commercial_discovery import fetch_hunter_company

            set_step(db, run, "source", "processing")
            db.commit()
            company = fetch_hunter_company(account.domain)
            if company:
                for field in ("segment", "employee_band", "region"):
                    if not getattr(account, field) and company.get(field):
                        setattr(account, field, str(company[field])[:100 if field == "employee_band" else 200])
                        enriched = True
        sources = db.scalar(select(func.count()).select_from(AccountSource).where(AccountSource.account_id == account.id, AccountSource.tenant_id == tenant_id)) or 0
        set_step(db, run, "source", "completed" if sources else "skipped", {"count": sources, "hunter_company_enriched": enriched})
        db.commit()

        current_step = "contacts"
        contact_step = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.name == "contacts"))
        if hunter_enabled and account.domain and settings.hunter_api_key and (contact_step is None or contact_step.status != "completed"):
            from .commercial_discovery import fetch_hunter_contacts

            set_step(db, run, "contacts", "processing")
            db.commit()
            for data in fetch_hunter_contacts(account.domain):
                contact = db.scalar(select(AccountContact).where(
                    AccountContact.tenant_id == tenant_id, AccountContact.account_id == account.id,
                    AccountContact.source_provider == "hunter", AccountContact.source_ref == data["email"],
                ))
                if contact is None:
                    contact = AccountContact(tenant_id=tenant_id, account_id=account.id, source_provider="hunter", source_ref=data["email"])
                    db.add(contact)
                contact.kind = data["kind"]
                contact.name = data["name"]
                contact.title = data["title"]
                contact.email = data["email"]
                contact.phone = data["phone"]
                contact.confidence = data["confidence"]
                contact.source_url = data["source_url"]
                contact.observed_at = utcnow()
            db.flush()
        contacts = db.scalar(select(func.count()).select_from(AccountContact).where(AccountContact.account_id == account.id, AccountContact.tenant_id == tenant_id)) or 0
        set_step(db, run, "contacts", "completed" if contacts else "skipped", {"count": contacts, "hunter_enabled": bool(hunter_enabled), "note": "HUNTER_API_KEY não configurada" if hunter_enabled and not settings.hunter_api_key else None})
        db.commit()

        current_step = "signals"
        signals = db.scalar(select(func.count()).select_from(IntentSignal).where(IntentSignal.account_id == account.id, IntentSignal.tenant_id == tenant_id)) or 0
        set_step(db, run, "signals", "completed" if signals else "skipped", {"count": signals, "note": "Nenhuma fonte automática de sinais configurada" if not signals else None})
        db.commit()

        current_step = "score"
        set_step(db, run, "score", "processing")
        db.commit()
        score = calculate_score(db, account, icp)
        set_step(db, run, "score", "completed", {"total": score.total, "classification": score.classification, "version": icp.version})
        db.commit()

        current_step = "brief"
        existing_brief = db.scalar(select(AccountBrief).where(AccountBrief.account_id == account.id, AccountBrief.offer_id == offer.id, AccountBrief.tenant_id == tenant_id))
        brief_step = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.name == "brief"))
        if brief_step and brief_step.status == "completed" and existing_brief:
            model = existing_brief.generated_with
        else:
            set_step(db, run, "brief", "processing")
            db.commit()
            saved = asyncio.run(generate_and_store_brief(db, offer, account, icp))
            model = saved.generated_with
        set_step(db, run, "brief", "completed", {"generated_with": model})
        run.status = "completed"
        run.error = None
        run.finished_at = utcnow()
        db.commit()
        return {"status": "completed", "account_id": account.id, "score": score.total, "brief_model": model}
    except Exception as exc:
        db.rollback()
        logger.exception("account_workflow_failed", extra={"run_id": run_id, "tenant_id": tenant_id, "step": current_step})
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.tenant_id == tenant_id))
        if run:
            retrying = self.request.retries < self.max_retries
            run.status = "retrying" if retrying else "failed"
            run.error = f"Falha na etapa {current_step or 'inicial'}"
            if not retrying:
                run.finished_at = utcnow()
            if current_step:
                set_step(db, run, current_step, "retrying" if retrying else "failed", error="Não foi possível concluir esta etapa")
            db.commit()
            if retrying:
                raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)))
        raise
    finally:
        db.close()


@celery_app.task(name="leadengine360.refresh_scores")
def refresh_scores():
    """Recalculate time-decayed scores for accounts with an approved ICP."""
    from .leads import calculate_score

    db = SessionLocal()
    refreshed = 0
    try:
        last_id = ""
        while True:
            rows = db.execute(select(TargetAccount.id, IcpProfile.id).join(
                IcpProfile,
                (IcpProfile.offer_id == TargetAccount.offer_id) &
                (IcpProfile.tenant_id == TargetAccount.tenant_id) &
                (IcpProfile.status == "approved"),
            ).where(TargetAccount.id > last_id).order_by(TargetAccount.id).limit(100)).all()
            if not rows:
                break
            for account_id, icp_id in rows:
                account, icp = db.get(TargetAccount, account_id), db.get(IcpProfile, icp_id)
                if account and icp and icp.status == "approved":
                    calculate_score(db, account, icp)
                    refreshed += 1
            db.commit()
            last_id = rows[-1][0]
        return {"refreshed": refreshed}
    except Exception:
        db.rollback()
        logger.exception("score_refresh_failed")
        raise
    finally:
        db.close()
