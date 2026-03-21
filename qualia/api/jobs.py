"""JobManager — orquestração de jobs assíncronos."""
import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from qualia.core.jobs import Job, JobStatus, JobType

logger = logging.getLogger(__name__)


class JobManager:
    """Gerencia ciclo de vida de jobs assíncronos."""

    def __init__(self, max_concurrent: int = 1):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent
        self._pending_queue: list[tuple[str, tuple]] = []  # (job_id, ("single"|"pipeline", executor(s)))
        self._streams: dict[str, set[asyncio.Queue]] = {}
        self._streams_lock = asyncio.Lock()

    # --- Stub for notify (implemented in Task 5) ---

    async def _notify_job(self, job_id: str) -> None:
        """Envia estado do job para subscribers SSE. Stub até Task 5."""
        pass

    def store(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.is_expired:
                return None
            return job

    def list_jobs(
        self,
        status: JobStatus | None = None,
        plugin_id: str | None = None,
    ) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if not j.is_expired]
        if status:
            jobs = [j for j in jobs if j.status == status]
        if plugin_id:
            jobs = [j for j in jobs if j.plugin_id == plugin_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool | None:
        """Cancela job. Retorna True se cancelou, False se não pode, None se não existe."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status != JobStatus.pending:
                return False
            job.status = JobStatus.cancelled
            job.completed_at = datetime.now(timezone.utc)
            # Remove da fila de pendentes se estiver lá
            self._pending_queue = [
                (jid, entry) for jid, entry in self._pending_queue if jid != job_id
            ]
            self._cleanup_temp_files(job)
            return True

    def cleanup_expired(self) -> int:
        with self._lock:
            expired_ids = [jid for jid, j in self._jobs.items() if j.is_expired]
            for jid in expired_ids:
                job = self._jobs.pop(jid)
                self._cleanup_temp_files(job)
            return len(expired_ids)

    def _cleanup_temp_files(self, job: Job) -> None:
        for path in job.temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass
