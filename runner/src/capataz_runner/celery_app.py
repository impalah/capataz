"""Celery configuration for the isolated runner worker."""

from __future__ import annotations

from celery import Celery

from capataz_runner.config import Settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Create a worker configured for conservative, at-least-once processing."""
    configured = settings or Settings()
    app = Celery("capataz_runner", broker=configured.redis_url, backend=configured.redis_url)
    app.conf.update(
        task_default_queue=configured.celery_queue,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        task_publish_retry=True,
        task_publish_retry_policy={"max_retries": 3, "interval_start": 0, "interval_step": 0.2},
        task_soft_time_limit=configured.celery_soft_time_limit_seconds,
        task_time_limit=configured.celery_hard_time_limit_seconds,
        worker_prefetch_multiplier=1,
        worker_concurrency=configured.celery_concurrency,
        broker_connection_retry_on_startup=True,
        # Reconciles executions stranded in 'running' by a dead/killed worker (see tasks.py);
        # the task itself is idempotent (UPDATE ... WHERE status='running'), so redundant runs
        # across a beat restart or, if ever scaled out, multiple embedded-beat workers are harmless.
        beat_schedule={
            "reap-stuck-executions": {
                "task": "capataz_runner.tasks.reap_stuck_executions",
                "schedule": max(60, configured.celery_hard_time_limit_seconds // 2),
            },
        },
    )
    app.autodiscover_tasks(["capataz_runner"])
    return app


app = create_celery_app()


def main() -> None:
    """Run the worker with the queue name fixed by the integration contract."""
    settings = Settings()
    app.worker_main(
        [
            "worker",
            "--loglevel",
            settings.log_level.lower(),
            "--queues",
            settings.celery_queue,
            "-B",
            "--schedule=/tmp/celerybeat-schedule",
        ]
    )
