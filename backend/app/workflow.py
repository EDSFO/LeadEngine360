"""Persistence helpers for the per-account processing pipeline."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import WorkflowRun, WorkflowStep, utcnow

STEP_NAMES = ("source", "contacts", "signals", "score", "brief")


def ensure_run(db: Session, tenant_id: str, offer_id: str, account_id: str, discovery_job_id: str) -> WorkflowRun:
    run = db.scalar(select(WorkflowRun).where(
        WorkflowRun.tenant_id == tenant_id, WorkflowRun.offer_id == offer_id,
        WorkflowRun.account_id == account_id, WorkflowRun.discovery_job_id == discovery_job_id,
    ))
    if run is None:
        run = WorkflowRun(tenant_id=tenant_id, offer_id=offer_id, account_id=account_id, discovery_job_id=discovery_job_id)
        db.add(run)
        db.flush()
    existing = set(db.scalars(select(WorkflowStep.name).where(WorkflowStep.run_id == run.id)).all())
    for name in STEP_NAMES:
        if name not in existing:
            db.add(WorkflowStep(run_id=run.id, tenant_id=tenant_id, name=name))
    db.flush()
    return run


def set_step(db: Session, run: WorkflowRun, name: str, status: str, details: dict | None = None, error: str | None = None) -> WorkflowStep:
    step = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.tenant_id == run.tenant_id, WorkflowStep.name == name))
    if step is None:
        step = WorkflowStep(run_id=run.id, tenant_id=run.tenant_id, name=name)
        db.add(step)
    if status == "processing":
        step.attempts += 1
        step.started_at = utcnow()
        step.finished_at = None
    if status in ("completed", "skipped", "failed"):
        step.finished_at = utcnow()
    step.status = status
    step.error = error
    if details is not None:
        step.details = details
    return step
