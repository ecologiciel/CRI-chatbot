"""ARQ background workers for the CRI platform.

Run the ingestion worker:
    arq app.workers.ingestion.WorkerSettings

Run the archive worker (weekly audit log archival):
    arq app.workers.archive.WorkerSettings

Run the campaign worker (WhatsApp mass-messaging):
    arq app.workers.campaign.WorkerSettings

Run the learning worker (supervised learning Qdrant reinjection):
    arq app.workers.learning.WorkerSettings
"""
