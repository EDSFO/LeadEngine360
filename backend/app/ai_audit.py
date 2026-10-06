from sqlalchemy.orm import Session

from .models import AiCall


def record_ai_calls(db: Session, tenant_id: str, offer_id: str, task: str, trace: list[dict], account_id: str | None = None) -> None:
    for item in trace:
        db.add(AiCall(
            tenant_id=tenant_id, offer_id=offer_id, account_id=account_id,
            task=task, model=item["model"], status=item["status"],
            latency_ms=item["latency_ms"], prompt_tokens=item.get("prompt_tokens"),
            completion_tokens=item.get("completion_tokens"), cost_usd=item.get("cost_usd"),
            error_type=item.get("error_type"),
        ))
