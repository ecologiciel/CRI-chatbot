"""Ingestion tasks must not be claimed by the unrelated purge worker."""

from arq.constants import default_queue_name

from app.workers.ingestion import WorkerSettings as IngestionWorkerSettings
from app.workers.learning import WorkerSettings as LearningWorkerSettings
from app.workers.purge import WorkerSettings as PurgeWorkerSettings


def test_purge_worker_uses_a_separate_queue_from_ingestion():
    ingestion_queue = getattr(IngestionWorkerSettings, "queue_name", default_queue_name)
    assert PurgeWorkerSettings.queue_name != ingestion_queue
    assert LearningWorkerSettings.queue_name not in {
        ingestion_queue,
        PurgeWorkerSettings.queue_name,
    }
