"""Celery 应用：Redis 同时作为 broker 与 result backend。"""

from __future__ import annotations

from celery import Celery

from services.api.app.config import settings

celery_app = Celery(
    "zhixiu",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["services.worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)