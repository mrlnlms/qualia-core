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

    # --- Execution ---

    async def submit(self, job_id: str, executor: callable) -> None:
        """Submete um job single para execução."""
        if not self._try_acquire_slot(job_id, ("single", executor)):
            return  # fica pending na fila
        asyncio.create_task(self._run_single(job_id, executor))

    async def submit_pipeline(self, job_id: str, executors: list[callable]) -> None:
        """Submete um pipeline job para execução."""
        if not self._try_acquire_slot(job_id, ("pipeline", executors)):
            return
        asyncio.create_task(self._run_pipeline(job_id, executors))

    def _try_acquire_slot(self, job_id: str, entry: tuple) -> bool:
        """Tenta adquirir um slot de execução. Retorna False se cheio."""
        with self._lock:
            running_count = sum(
                1 for j in self._jobs.values() if j.status == JobStatus.running
            )
            if running_count >= self._max_concurrent:
                self._pending_queue.append((job_id, entry))
                return False
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.running
                job.started_at = datetime.now(timezone.utc)
            return True

    async def _run_single(self, job_id: str, executor: callable) -> None:
        """Executa um job single em background thread."""
        try:
            result = await asyncio.to_thread(executor, job_id)
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.status = JobStatus.completed
                    job.result = result
                    job.progress = 1.0
                    job.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.status = JobStatus.failed
                    job.error = str(e)
                    job.completed_at = datetime.now(timezone.utc)
        finally:
            await self._notify_job(job_id)
            await self._process_pending_queue()
            self._cleanup_temp_files_if_terminal(job_id)

    async def _run_pipeline(self, job_id: str, executors: list[callable]) -> None:
        """Executa pipeline steps sequencialmente."""
        try:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    return

            for i, executor in enumerate(executors):
                with self._lock:
                    job = self._jobs[job_id]
                    job.current_step = i
                    job.steps[i].status = JobStatus.running
                await self._notify_job(job_id)

                try:
                    result = await asyncio.to_thread(executor, job_id)
                    with self._lock:
                        job.steps[i].status = JobStatus.completed
                        job.steps[i].result = result
                        job.update_progress()
                except Exception as e:
                    with self._lock:
                        job.steps[i].status = JobStatus.failed
                        job.steps[i].error = str(e)
                        job.status = JobStatus.failed
                        job.error = f"Step {i} ({job.steps[i].plugin_id}): {e}"
                        job.completed_at = datetime.now(timezone.utc)
                    await self._notify_job(job_id)
                    return

            with self._lock:
                job.status = JobStatus.completed
                job.progress = 1.0
                job.result = {
                    "steps_executed": len(executors),
                    "results": [
                        {"plugin_id": s.plugin_id, "result": s.result}
                        for s in job.steps
                    ],
                }
                job.completed_at = datetime.now(timezone.utc)
        finally:
            await self._notify_job(job_id)
            await self._process_pending_queue()
            self._cleanup_temp_files_if_terminal(job_id)

    async def _process_pending_queue(self) -> None:
        """Inicia o próximo job pendente válido se há slot disponível."""
        with self._lock:
            running_count = sum(
                1 for j in self._jobs.values() if j.status == JobStatus.running
            )
            if running_count >= self._max_concurrent:
                return
            # Procura o próximo job válido (pula cancelados/expirados)
            while self._pending_queue:
                job_id, entry = self._pending_queue.pop(0)
                job = self._jobs.get(job_id)
                if job and job.status == JobStatus.pending:
                    job.status = JobStatus.running
                    job.started_at = datetime.now(timezone.utc)
                    break
            else:
                return  # fila vazia ou sem jobs válidos

        kind, executor_or_executors = entry
        if kind == "pipeline":
            asyncio.create_task(self._run_pipeline(job_id, executor_or_executors))
        else:
            asyncio.create_task(self._run_single(job_id, executor_or_executors))

    def _cleanup_temp_files_if_terminal(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status.is_terminal:
                self._cleanup_temp_files(job)

    def _cleanup_temp_files(self, job: Job) -> None:
        for path in job.temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass
