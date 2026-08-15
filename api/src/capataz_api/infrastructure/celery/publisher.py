import asyncio
from uuid import UUID

from celery import Celery


class CeleryExecutionPublisher:
    def __init__(self, broker_url: str, queue: str = "automation") -> None:
        self.queue = queue
        self.app = Celery("capataz_api", broker=broker_url, backend=broker_url)

    async def enqueue(self, execution_id: UUID) -> str:
        # Celery's send_task is a blocking network call; run it off the event loop so a slow
        # broker doesn't stall every other request being served by this worker.
        result = await asyncio.to_thread(
            self.app.send_task,
            "capataz_runner.tasks.process_execution",
            kwargs={"execution_id": str(execution_id)},
            queue=self.queue,
        )
        return result.id
