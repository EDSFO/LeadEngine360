import csv
import io
import math
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .ai import generate_account_brief
from .ai_audit import record_ai_calls
from .models import AccountActivity, AccountBrief, AccountContact, AccountScore, AccountSource, IcpProfile, IntentSignal, JobRun, Offer, OfferSourceSelection, TargetAccount, User, WorkflowRun, WorkflowStep, utcnow
from .schemas import ActivityIn, SignalIn
from .security import current_user, require_roles

router = APIRouter(prefix="/api/v1/offers/{offer_id}", tags=["accounts"])
MAX_CSV_BYTES = 5 * 1024 * 1024
ALIASES = {
    "name": {"name", "company", "company_name", "nome", "empresa", "razao_social"},
    "domain": {"domain", "dominio", "website", "site", "url", "company_website"},
    "segment": {"segment", "industry", "setor", "segmento", "industria"},
    "employee_band": {"employee_band", "employees", "company_size", "porte", "funcionarios", "tamanho"},
    "region": {"region", "location", "regiao", "localizacao", "cidade", "estado", "pais"},
}


def _normalized(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _size_matches(actual: str, candidate: str) -> bool:
    """Match a provider's numeric headcount against an ICP size interval."""
    observed = re.fullmatch(r"\s*(\d+)\s*", actual)
    expected = re.fullmatch(r"\s*(\d+)\s*[-–,]\s*(\d+)\s*", candidate)
    if observed and expected:
        lower, upper = int(expected[1]), int(expected[2])
        return lower <= int(observed[1]) <= upper
    minimum = re.fullmatch(r"\s*(\d+)\s*\+\s*", candidate)
    if observed and minimum:
        return int(observed[1]) >= int(minimum[1])
    return _normalized(candidate) == _normalized(actual)


def _region_matches(actual: str, candidate: str) -> bool:
    observed, expected = _normalized(actual), _normalized(candidate)
    if expected in observed or observed in expected:
        return True
    country_aliases = {
        "brasil": "br", "brazil": "br", "br": "br",
        "estados unidos": "us", "united states": "us", "usa": "us", "us": "us",
        "portugal": "pt", "pt": "pt",
    }
    return country_aliases.get(observed) is not None and country_aliases.get(observed) == country_aliases.get(expected)


def _domain(value: str | None) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").removeprefix("www.").rstrip(".")
    if not host or "." not in host or " " in host:
        return None
    return host[:253]


def _approved_offer(db: Session, offer_id: str, user: User) -> tuple[Offer, IcpProfile]:
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    icp = db.scalar(select(IcpProfile).where(IcpProfile.offer_id == offer.id, IcpProfile.tenant_id == user.tenant_id))
    if icp is None or icp.status != "approved":
        raise HTTPException(status_code=409, detail="Gere e aprove o ICP desta oferta antes de importar contas")
    return offer, icp


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def calculate_score(db: Session, account: TargetAccount, icp: IcpProfile) -> AccountScore:
    # Sessions disable autoflush. Include newly recorded signals, activities and
    # scores before querying; this also makes repeated domains in a CSV visible.
    db.flush()
    profile = icp.profile_json if isinstance(icp.profile_json, dict) else {}
    criteria = profile.get("ideal_customer_profile") or {}
    if not isinstance(criteria, dict):
        criteria = {}
    dimensions = [("segments", "segment", account.segment), ("company_size", "porte", account.employee_band), ("regions", "região", account.region)]
    configured = [(key, label, actual, values) for key, label, actual in dimensions if (values := criteria.get(key))]
    raw_weights = criteria.get("weights") or profile.get("weights") or {}
    if not isinstance(raw_weights, dict):
        raw_weights = {}
    weighted_criteria = []
    for key, label, actual, values in configured:
        try:
            weight = float(raw_weights.get(key, 1))
        except (TypeError, ValueError):
            weight = 1.0
        if not math.isfinite(weight) or weight <= 0:
            weight = 0.0
        weighted_criteria.append((key, label, actual, values, weight))
    matched = []
    missing = []
    excluded = []
    matched_weight = total_weight = 0.0
    for key, label, actual, values, weight in weighted_criteria:
        candidates = [str(item) for item in (values if isinstance(values, list) else [values]) if item]
        total_weight += weight
        if not actual:
            missing.append(label)
            continue
        actual_normalized = _normalized(actual)
        if any(_size_matches(str(actual), candidate) if key == "company_size" else _region_matches(str(actual), candidate) if key == "regions" else (_normalized(candidate) in actual_normalized or actual_normalized in _normalized(candidate)) for candidate in candidates):
            matched.append(label)
            matched_weight += weight
        else:
            excluded.append(label)
    fit = round(40 * matched_weight / total_weight) if total_weight else 0
    raw_exclusions = criteria.get("exclusions", [])
    if not isinstance(raw_exclusions, list):
        raw_exclusions = [raw_exclusions]
    exclusions = [str(value) for value in raw_exclusions if value]
    account_text = _normalized(" ".join([account.name, account.domain or "", account.segment or "", account.employee_band or "", account.region or ""]))
    matched_exclusions = [value for value in exclusions if _normalized(value) and _normalized(value) in account_text]
    if matched_exclusions:
        fit = 0
    required_keys = criteria.get("required", []) if isinstance(criteria.get("required", []), list) else []
    matched_keys = {key for key, label, _, _, _ in weighted_criteria if label in matched}
    missing_required = [key for key in required_keys if key not in matched_keys]
    if missing_required:
        fit = 0

    signals = db.scalars(select(IntentSignal).where(IntentSignal.account_id == account.id, IntentSignal.tenant_id == account.tenant_id)).all()
    now = utcnow()
    live_signals = []
    intent_raw = 0.0
    signal_contributions = []
    latest_signal = None
    for signal in signals:
        occurred = _as_utc(signal.occurred_at)
        age_days = max(0, (now - occurred).days)
        if age_days > 180:
            continue
        recency_weight = max(0.0, 1 - age_days / 181)
        confidence = min(1.0, max(0.0, float(signal.confidence)))
        strength = min(5, max(1, int(signal.strength)))
        contribution = 30 * (strength / 5) * confidence * recency_weight
        intent_raw += contribution
        signal_contributions.append({"title": signal.title, "type": signal.signal_type, "source": signal.source_url or "Registro manual", "confidence": confidence, "strength": strength, "age_days": age_days, "intent_points": round(contribution, 2)})
        live_signals.append(signal)
        if latest_signal is None or occurred > _as_utc(latest_signal.occurred_at):
            latest_signal = signal
    intent = min(30, round(intent_raw))
    timing = 0
    if latest_signal:
        age_days = max(0, (now - _as_utc(latest_signal.occurred_at)).days)
        timing = 10 if age_days <= 7 else 8 if age_days <= 30 else 5 if age_days <= 90 else 2
    activities = db.scalars(select(AccountActivity).where(AccountActivity.account_id == account.id, AccountActivity.tenant_id == account.tenant_id)).all()
    engagement_weights = {"contacted": 2, "replied": 8, "meeting": 12, "opportunity": 16, "won": 20, "lost": 0}
    engagement = 0
    engagement_source = None
    for activity in activities:
        age_days = max(0, (now - _as_utc(activity.occurred_at)).days)
        if age_days <= 180:
            points = round(engagement_weights.get(activity.activity_type, 0) * max(0, 1 - age_days / 181))
            if points > engagement:
                engagement = points
                engagement_source = activity.activity_type
    total = min(100, fit + intent + engagement + timing)
    raw_thresholds = profile.get("classification_thresholds") or {}
    if not isinstance(raw_thresholds, dict):
        raw_thresholds = {}
    def threshold(name: str, default: int) -> int:
        try:
            return min(100, max(0, int(raw_thresholds.get(name, default))))
        except (TypeError, ValueError):
            return default
    hot_total = threshold("hot", 80)
    warm_total = threshold("warm", 60)
    target_total = threshold("target", 40)
    minimum_hot_fit = threshold("minimum_hot_fit", 24)
    try:
        minimum_hot_confidence = min(1.0, max(0.0, float(raw_thresholds.get("minimum_hot_confidence", 0.6))))
    except (TypeError, ValueError):
        minimum_hot_confidence = 0.6
    if matched_exclusions or missing_required:
        classification = "Cold"
    elif total >= hot_total and fit >= minimum_hot_fit and any(signal.confidence >= minimum_hot_confidence for signal in live_signals):
        classification = "Hot"
    elif total >= warm_total:
        classification = "Warm"
    elif total >= target_total:
        classification = "Target"
    else:
        classification = "Cold"
    explanation = {
        "matched_fit_criteria": matched,
        "fit_criterion_weights": {key: weight for key, _, _, _, weight in weighted_criteria},
        "mismatched_fit_criteria": excluded,
        "missing_fit_data": missing,
        "matched_exclusions": matched_exclusions,
        "missing_required_criteria": missing_required,
        "active_signal_count": len(live_signals),
        "signal_contributions": signal_contributions,
        "latest_signal_title": latest_signal.title if latest_signal else None,
        "engagement_source": engagement_source,
        "score_caps": {"fit": 40, "intent": 30, "engagement": 20, "timing": 10},
        "note": "Sem critérios configurados no ICP, o Fit Score fica em zero. Sem fonte ou interação cadastrada, os respectivos scores também ficam em zero.",
    }
    result = db.scalar(select(AccountScore).where(AccountScore.tenant_id == account.tenant_id, AccountScore.account_id == account.id, AccountScore.offer_id == account.offer_id))
    if result is None:
        result = AccountScore(tenant_id=account.tenant_id, account_id=account.id, offer_id=account.offer_id)
        db.add(result)
    result.fit, result.intent, result.engagement, result.timing = fit, intent, engagement, timing
    result.total, result.classification, result.explanation = total, classification, explanation
    result.scoring_version = icp.version
    return result


def _account_payload(account: TargetAccount, score: AccountScore | None) -> dict:
    return {
        "id": account.id, "offer_id": account.offer_id, "name": account.name, "domain": account.domain,
        "website": account.website, "segment": account.segment, "employee_band": account.employee_band,
        "region": account.region, "source": account.source, "status": account.status,
        "created_at": account.created_at,
        "score": {"fit": score.fit, "intent": score.intent, "engagement": score.engagement, "timing": score.timing, "total": score.total, "classification": score.classification, "explanation": score.explanation} if score else None,
    }


@router.post("/discovery", status_code=202)
def start_discovery(offer_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "analyst")), provider_id: str | None = None):
    from .discovery import DiscoveryConfigError, validate_osm_discovery

    offer, icp = _approved_offer(db, offer_id, user)
    # Serialize concurrent starts for the same offer on PostgreSQL.
    db.scalar(select(Offer).where(Offer.id == offer.id, Offer.tenant_id == user.tenant_id).with_for_update())
    provider_id = provider_id or "osm-overpass"
    if provider_id not in {"osm-overpass", "apollo", "hunter"}:
        raise HTTPException(status_code=422, detail="Fonte de descoberta inválida")
    selected = db.scalar(select(OfferSourceSelection.id).where(
        OfferSourceSelection.offer_id == offer.id,
        OfferSourceSelection.tenant_id == user.tenant_id,
        OfferSourceSelection.provider_id == provider_id,
        OfferSourceSelection.enabled.is_(True),
    ))
    if not selected:
        raise HTTPException(status_code=409, detail="Ative a fonte escolhida nas integrações desta oferta")
    try:
        if provider_id == "osm-overpass":
            validate_osm_discovery(icp.profile_json)
        else:
            from .commercial_discovery import build_apollo_params, build_hunter_filters
            from .config import settings
            if provider_id == "apollo":
                build_apollo_params(icp.profile_json)
            else:
                build_hunter_filters(icp.profile_json)
            if provider_id == "apollo" and not settings.apollo_api_key:
                raise HTTPException(status_code=409, detail="APOLLO_API_KEY não configurada no servidor")
            if provider_id == "hunter" and not settings.hunter_api_key:
                raise HTTPException(status_code=409, detail="HUNTER_API_KEY não configurada no servidor")
    except DiscoveryConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    active = db.scalar(select(JobRun).where(
        JobRun.tenant_id == user.tenant_id, JobRun.entity_id == offer.id,
        JobRun.job_type == "account_discovery", JobRun.status.in_(["queued", "processing", "retrying"]),
    ).order_by(JobRun.created_at.desc()))
    if active:
        return {"job_id": active.id, "status": active.status, "provider_id": active.provider_id}
    job = JobRun(tenant_id=user.tenant_id, entity_id=offer.id, job_type="account_discovery", provider_id=provider_id, status="queued")
    db.add(job)
    db.commit()
    try:
        from .tasks import discover_accounts

        discover_accounts.delay(job.id, user.tenant_id, offer.id)
    except Exception:
        job.status = "failed"
        job.error = "A fila de descoberta está indisponível"
        job.finished_at = utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="A fila de descoberta está indisponível") from None
    return {"job_id": job.id, "status": job.status, "provider_id": job.provider_id}


@router.get("/discovery")
def latest_discovery(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    job = db.scalar(select(JobRun).where(
        JobRun.tenant_id == user.tenant_id, JobRun.entity_id == offer.id,
        JobRun.job_type == "account_discovery",
    ).order_by(JobRun.created_at.desc(), JobRun.id.desc()))
    return {"job_id": job.id, "status": job.status, "error": job.error, "progress": job.progress} if job else None


@router.get("/workflows")
def list_workflows(offer_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    where = (WorkflowRun.tenant_id == user.tenant_id, WorkflowRun.offer_id == offer_id)
    total = db.scalar(select(func.count()).select_from(WorkflowRun).where(*where)) or 0
    rows = db.execute(select(WorkflowRun, TargetAccount.name).join(TargetAccount, TargetAccount.id == WorkflowRun.account_id).where(*where).order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [{"id": run.id, "account_id": run.account_id, "account_name": name, "discovery_job_id": run.discovery_job_id, "status": run.status, "attempts": run.attempts, "error": run.error, "created_at": run.created_at, "finished_at": run.finished_at} for run, name in rows]}


@router.get("/workflows/{run_id}")
def get_workflow(offer_id: str, run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.offer_id == offer_id, WorkflowRun.tenant_id == user.tenant_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Processamento não encontrado")
    steps = db.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.tenant_id == user.tenant_id).order_by(WorkflowStep.id)).all()
    return {"id": run.id, "account_id": run.account_id, "status": run.status, "attempts": run.attempts, "error": run.error, "steps": [{"name": step.name, "status": step.status, "attempts": step.attempts, "error": step.error, "details": step.details, "started_at": step.started_at, "finished_at": step.finished_at} for step in steps]}


@router.post("/workflows/{run_id}/retry", status_code=202)
def retry_workflow(offer_id: str, run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "analyst"))):
    from .tasks import process_account

    run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.offer_id == offer_id, WorkflowRun.tenant_id == user.tenant_id).with_for_update())
    if run is None:
        raise HTTPException(status_code=404, detail="Processamento não encontrado")
    if run.status != "failed":
        raise HTTPException(status_code=409, detail="Apenas processamentos com falha podem ser reenfileirados")
    _, icp = _approved_offer(db, offer_id, user)
    run.status = "queued"
    run.error = None
    run.finished_at = None
    db.commit()
    try:
        process_account.delay(run.id, user.tenant_id)
    except Exception:
        run.status = "failed"
        run.error = "A fila de processamento está indisponível"
        run.finished_at = utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail=run.error) from None
    return {"id": run.id, "status": run.status, "icp_version": icp.version}


@router.post("/accounts/import", status_code=201)
async def import_accounts(offer_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "analyst"))):
    offer, icp = _approved_offer(db, offer_id, user)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Envie um arquivo CSV")
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="O limite para CSV é 5 MB")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = {_normalized(str(header)).replace(" ", "_"): header for header in (reader.fieldnames or [])}
        columns = {field: next((headers[alias] for alias in aliases if alias in headers), None) for field, aliases in ALIASES.items()}
        if not columns["name"]:
            raise ValueError("Inclua uma coluna chamada empresa, company ou name")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"CSV inválido: {exc}") from None
    if len(rows) > 2_000:
        raise HTTPException(status_code=413, detail="O limite por importação é 2.000 linhas; divida lotes maiores")
    created = updated = skipped = 0
    errors = []
    for row_number, row in enumerate(rows, start=2):
        name = (row.get(columns["name"]) or "").strip()
        if not name:
            skipped += 1
            if len(errors) < 20:
                errors.append({"row": row_number, "reason": "Nome da empresa vazio"})
            continue
        supplied_domain = row.get(columns["domain"]) if columns["domain"] else None
        domain = _domain(supplied_domain)
        if supplied_domain and not domain:
            skipped += 1
            if len(errors) < 20:
                errors.append({"row": row_number, "reason": "Domínio ou URL inválido"})
            continue
        account = None
        if domain:
            account = db.scalar(select(TargetAccount).where(TargetAccount.tenant_id == user.tenant_id, TargetAccount.offer_id == offer.id, TargetAccount.domain == domain))
        values = {
            "name": name, "domain": domain,
            "website": (supplied_domain or "").strip() or None,
            "segment": (row.get(columns["segment"]) or "").strip() or None if columns["segment"] else None,
            "employee_band": (row.get(columns["employee_band"]) or "").strip() or None if columns["employee_band"] else None,
            "region": (row.get(columns["region"]) or "").strip() or None if columns["region"] else None,
        }
        if account:
            for key, value in values.items():
                if value:
                    setattr(account, key, value)
            updated += 1
        else:
            account = TargetAccount(tenant_id=user.tenant_id, offer_id=offer.id, **values)
            db.add(account)
            db.flush()
            created += 1
        calculate_score(db, account, icp)
    db.commit()
    return {"offer_id": offer.id, "created": created, "updated": updated, "skipped": skipped, "rows_seen": len(rows), "errors": errors, "errors_truncated": skipped > len(errors)}


@router.get("/accounts")
def list_accounts(offer_id: str, classification: str | None = Query(default=None, pattern="^(Cold|Target|Warm|Hot)$"), search: str | None = None, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    query = select(TargetAccount, AccountScore).outerjoin(AccountScore, (AccountScore.account_id == TargetAccount.id) & (AccountScore.tenant_id == user.tenant_id) & (AccountScore.offer_id == offer.id)).where(TargetAccount.tenant_id == user.tenant_id, TargetAccount.offer_id == offer.id)
    if classification:
        query = query.where(AccountScore.classification == classification)
    if search:
        like = f"%{search.strip()}%"
        query = query.where((TargetAccount.name.ilike(like)) | (TargetAccount.domain.ilike(like)) | (TargetAccount.segment.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pairs = db.execute(query.order_by(AccountScore.total.desc().nullslast(), TargetAccount.name).offset(offset).limit(limit)).all()
    return {"items": [_account_payload(account, score) for account, score in pairs], "total": total, "limit": limit, "offset": offset}


@router.get("/accounts/export")
def export_accounts(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.tenant_id == user.tenant_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")
    query = select(TargetAccount, AccountScore).outerjoin(AccountScore, (AccountScore.account_id == TargetAccount.id) & (AccountScore.tenant_id == user.tenant_id) & (AccountScore.offer_id == offer.id)).where(TargetAccount.tenant_id == user.tenant_id, TargetAccount.offer_id == offer.id).order_by(AccountScore.total.desc().nullslast(), TargetAccount.name)
    output = io.StringIO(newline="")
    columns = ["empresa", "dominio", "segmento", "porte", "regiao", "fonte", "licenca_fonte", "fit", "intencao", "engajamento", "timing", "score_total", "classificacao", "explicacao"]
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for account, score in db.execute(query).all():
        writer.writerow({"empresa": account.name, "dominio": account.domain or "", "segmento": account.segment or "", "porte": account.employee_band or "", "regiao": account.region or "", "fonte": account.source, "licenca_fonte": "© OpenStreetMap contributors · ODbL · https://www.openstreetmap.org/copyright" if account.source == "osm-overpass" else "", "fit": score.fit if score else 0, "intencao": score.intent if score else 0, "engajamento": score.engagement if score else 0, "timing": score.timing if score else 0, "score_total": score.total if score else 0, "classificacao": score.classification if score else "Cold", "explicacao": "; ".join((score.explanation or {}).get("matched_fit_criteria", [])) if score else ""})
    output.seek(0)
    return StreamingResponse(iter(["\ufeff" + output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=leadengine360-{offer.id[:8]}.csv"})


@router.get("/accounts/{account_id}/signals")
def list_signals(offer_id: str, account_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer_id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    signals = db.scalars(select(IntentSignal).where(IntentSignal.account_id == account.id, IntentSignal.tenant_id == user.tenant_id).order_by(IntentSignal.occurred_at.desc())).all()
    return [{"id": signal.id, "signal_type": signal.signal_type, "title": signal.title, "description": signal.description, "source_url": signal.source_url, "evidence": signal.evidence, "occurred_at": signal.occurred_at, "confidence": signal.confidence, "strength": signal.strength} for signal in signals]


@router.get("/accounts/{account_id}/sources")
def list_account_sources(offer_id: str, account_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer_id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    sources = db.scalars(select(AccountSource).where(
        AccountSource.account_id == account.id, AccountSource.offer_id == offer_id,
        AccountSource.tenant_id == user.tenant_id,
    ).order_by(AccountSource.observed_at.desc())).all()
    return [{"provider_id": item.provider_id, "external_id": item.external_id, "source_url": item.source_url, "observed_at": item.observed_at} for item in sources]


@router.get("/accounts/{account_id}/contacts")
def list_account_contacts(offer_id: str, account_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer_id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    contacts = db.scalars(select(AccountContact).where(
        AccountContact.account_id == account.id, AccountContact.tenant_id == user.tenant_id,
    ).order_by(AccountContact.observed_at.desc())).all()
    return [{"id": item.id, "kind": item.kind, "name": item.name, "title": item.title, "email": item.email, "phone": item.phone, "confidence": item.confidence, "source_provider": item.source_provider, "source_url": item.source_url, "observed_at": item.observed_at} for item in contacts]


@router.get("/accounts/{account_id}/activities")
def list_activities(offer_id: str, account_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer_id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    activities = db.scalars(select(AccountActivity).where(AccountActivity.account_id == account.id, AccountActivity.tenant_id == user.tenant_id).order_by(AccountActivity.occurred_at.desc())).all()
    return [{"id": item.id, "activity_type": item.activity_type, "channel": item.channel, "outcome": item.outcome, "notes": item.notes, "occurred_at": item.occurred_at} for item in activities]


@router.post("/accounts/{account_id}/activities", status_code=201)
def create_activity(offer_id: str, account_id: str, payload: ActivityIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "sdr", "closer"))):
    offer, icp = _approved_offer(db, offer_id, user)
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer.id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    try:
        occurred = datetime.fromisoformat(payload.occurred_at.replace("Z", "+00:00")) if payload.occurred_at else utcnow()
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Data da atividade inválida") from None
    if (utcnow() - _as_utc(occurred)).total_seconds() < -86400:
        raise HTTPException(status_code=422, detail="A data da atividade não pode estar no futuro")
    activity = AccountActivity(tenant_id=user.tenant_id, account_id=account.id, activity_type=payload.activity_type, channel=payload.channel, outcome=payload.outcome, notes=payload.notes, occurred_at=occurred)
    db.add(activity)
    account.status = {"contacted": "contacted", "replied": "replied", "meeting": "meeting", "opportunity": "opportunity", "won": "won", "lost": "lost"}[payload.activity_type]
    score = calculate_score(db, account, icp)
    db.commit()
    db.refresh(score)
    return {"account_id": account.id, "status": account.status, "activity_type": activity.activity_type, "score": _account_payload(account, score)["score"]}


@router.post("/accounts/{account_id}/brief")
async def create_account_brief(offer_id: str, account_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "analyst", "sdr", "closer"))):
    offer, icp = _approved_offer(db, offer_id, user)
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer.id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    saved = await generate_and_store_brief(db, offer, account, icp)
    db.commit()
    db.refresh(saved)
    return {"id": saved.id, "account_id": account.id, "offer_id": offer.id, "generated_with": saved.generated_with, "brief": saved.brief_json, "updated_at": saved.updated_at}


async def generate_and_store_brief(db: Session, offer: Offer, account: TargetAccount, icp: IcpProfile) -> AccountBrief:
    signals = db.scalars(select(IntentSignal).where(IntentSignal.account_id == account.id, IntentSignal.tenant_id == account.tenant_id).order_by(IntentSignal.occurred_at.desc()).limit(20)).all()
    signal_data = [{"title": signal.title, "description": signal.description, "source_url": signal.source_url, "occurred_at": signal.occurred_at.isoformat(), "confidence": signal.confidence, "strength": signal.strength} for signal in signals]
    score = db.scalar(select(AccountScore).where(AccountScore.account_id == account.id, AccountScore.offer_id == offer.id, AccountScore.tenant_id == account.tenant_id))
    if score is None or score.scoring_version != icp.version:
        score = calculate_score(db, account, icp)
    score_context = {"fit": score.fit, "intent": score.intent, "engagement": score.engagement, "timing": score.timing, "total": score.total, "classification": score.classification, "explanation": score.explanation}
    trace: list[dict] = []
    brief, model = await generate_account_brief({"name": offer.name, "description": offer.description, "problem_solved": offer.problem_solved, "differentiators": offer.differentiators}, {"name": account.name, "domain": account.domain, "segment": account.segment, "employee_band": account.employee_band, "region": account.region}, signal_data, score_context, icp.profile_json, trace)
    saved = db.scalar(select(AccountBrief).where(AccountBrief.tenant_id == account.tenant_id, AccountBrief.account_id == account.id, AccountBrief.offer_id == offer.id))
    if saved is None:
        saved = AccountBrief(tenant_id=account.tenant_id, account_id=account.id, offer_id=offer.id)
        db.add(saved)
    saved.brief_json = brief
    saved.generated_with = model
    record_ai_calls(db, account.tenant_id, offer.id, "generate_brief", trace, account.id)
    return saved


@router.get("/accounts/{account_id}/brief")
def get_account_brief(offer_id: str, account_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer_id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    saved = db.scalar(select(AccountBrief).where(AccountBrief.tenant_id == user.tenant_id, AccountBrief.account_id == account.id, AccountBrief.offer_id == offer_id))
    if saved is None:
        raise HTTPException(status_code=404, detail="Brief ainda não gerado")
    return {"id": saved.id, "account_id": account.id, "offer_id": offer_id, "generated_with": saved.generated_with, "brief": saved.brief_json, "updated_at": saved.updated_at}


@router.post("/accounts/{account_id}/signals", status_code=201)
def create_signal(offer_id: str, account_id: str, payload: SignalIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager", "analyst"))):
    offer, icp = _approved_offer(db, offer_id, user)
    account = db.scalar(select(TargetAccount).where(TargetAccount.id == account_id, TargetAccount.offer_id == offer.id, TargetAccount.tenant_id == user.tenant_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    signal_type = payload.signal_type.strip()
    title = payload.title.strip()
    description = payload.description.strip()
    confidence = payload.confidence
    strength = payload.strength
    occurred_at = payload.occurred_at
    try:
        occurred = datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) if occurred_at else utcnow()
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Data do evento inválida") from None
    if (utcnow() - _as_utc(occurred)).total_seconds() < -86400:
        raise HTTPException(status_code=422, detail="A data do evento não pode estar no futuro")
    if (utcnow() - _as_utc(occurred)).days > 3650:
        raise HTTPException(status_code=422, detail="A data do evento é antiga demais")
    signal = IntentSignal(tenant_id=user.tenant_id, account_id=account.id, signal_type=signal_type, title=title, description=description, source_url=payload.source_url, evidence=payload.evidence, occurred_at=occurred, confidence=confidence, strength=strength)
    db.add(signal)
    score = calculate_score(db, account, icp)
    db.commit()
    db.refresh(signal)
    db.refresh(score)
    return {"id": signal.id, "account_id": account.id, "signal_type": signal.signal_type, "title": signal.title, "occurred_at": signal.occurred_at, "confidence": signal.confidence, "strength": signal.strength, "score": _account_payload(account, score)["score"]}
