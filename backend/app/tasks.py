import logging
from pathlib import Path

from sqlalchemy import delete, select

from .config import settings
from .database import SessionLocal
from .knowledge import extract_text, split_chunks
from .models import DocumentChunk, JobRun, KnowledgeDocument, utcnow
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
