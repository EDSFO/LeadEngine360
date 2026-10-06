from celery import Celery
from datetime import timedelta

from .config import settings

celery_app = Celery("leadengine360", broker=settings.redis_url, include=["app.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    beat_schedule={"refresh-scores-daily": {"task": "leadengine360.refresh_scores", "schedule": timedelta(days=1)}},
)
