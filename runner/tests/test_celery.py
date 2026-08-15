from __future__ import annotations


def test_celery_configuration_honours_contract_queue_and_safety(secrets_dir: object) -> None:
    from capataz_runner.celery_app import create_celery_app
    from capataz_runner.config import Settings

    app = create_celery_app(Settings(secrets_dir=secrets_dir))
    assert app.conf.task_default_queue == "automation"
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.worker_concurrency == 2
    assert (
        app.conf.beat_schedule["reap-stuck-executions"]["task"]
        == "capataz_runner.tasks.reap_stuck_executions"
    )
