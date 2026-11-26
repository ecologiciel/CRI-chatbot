"""A maintenance stop must allow an in-flight ARQ job to finish."""

import asyncio
import signal

import pytest
from arq.worker import Worker

from app.workers.ingestion import WorkerSettings as Ingestion
from app.workers.learning import WorkerSettings as Learning
from app.workers.purge import WorkerSettings as Purge


@pytest.mark.parametrize("settings", [Ingestion, Learning, Purge])
def test_shutdown_wait_covers_job_timeout(settings):
    assert settings.job_completion_wait > settings.job_timeout


@pytest.mark.asyncio
async def test_arq_stops_accepting_jobs_and_finishes_inflight_work():
    release = asyncio.Event()

    async def work(ctx):
        await release.wait()
        return "completed"

    worker = Worker(functions=[work], handle_signals=False, job_completion_wait=3)
    task = asyncio.create_task(work({}))
    worker.tasks["fixture"] = task
    task.add_done_callback(lambda _: worker.tasks.pop("fixture", None))
    await asyncio.sleep(0)
    worker.handle_sig_wait_for_completion(signal.SIGTERM)
    await asyncio.sleep(0.05)
    assert worker.allow_pick_jobs is False
    assert not task.done()
    release.set()
    assert await asyncio.wait_for(task, timeout=1) == "completed"
    # Let ARQ's signal-handling coroutine finish before closing the event loop.
    await asyncio.sleep(0.2)
