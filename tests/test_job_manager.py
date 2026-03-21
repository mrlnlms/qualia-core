"""Testes para o JobManager."""
import asyncio
import os
import tempfile
import time

import pytest

from qualia.api.jobs import JobManager
from qualia.core.jobs import Job, JobStatus, JobType


@pytest.fixture
def manager():
    return JobManager(max_concurrent=1)


class TestJobManagerStore:
    def test_create_and_get_job(self, manager):
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        retrieved = manager.get(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get("nonexistent") is None

    def test_list_all_jobs(self, manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        manager.store(j1)
        manager.store(j2)
        jobs = manager.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_filter_by_status(self, manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        j2.status = JobStatus.running
        manager.store(j1)
        manager.store(j2)
        pending = manager.list_jobs(status=JobStatus.pending)
        assert len(pending) == 1
        assert pending[0].plugin_id == "a"

    def test_list_jobs_filter_by_plugin(self, manager):
        j1 = Job.create_single(plugin_id="sentiment")
        j2 = Job.create_single(plugin_id="wordcloud")
        manager.store(j1)
        manager.store(j2)
        result = manager.list_jobs(plugin_id="sentiment")
        assert len(result) == 1

    def test_cancel_pending_job(self, manager):
        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        success = manager.cancel(job.id)
        assert success is True
        assert manager.get(job.id).status == JobStatus.cancelled

    def test_cancel_running_job_fails(self, manager):
        job = Job.create_single(plugin_id="sentiment")
        job.status = JobStatus.running
        manager.store(job)
        success = manager.cancel(job.id)
        assert success is False

    def test_cancel_nonexistent_returns_none(self, manager):
        result = manager.cancel("nonexistent")
        assert result is None

    def test_cleanup_expired_jobs(self, manager):
        job = Job.create_single(plugin_id="sentiment", ttl=0)
        manager.store(job)
        time.sleep(0.01)
        removed = manager.cleanup_expired()
        assert removed == 1
        assert manager.get(job.id) is None

    def test_cleanup_removes_temp_files(self, manager):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        assert os.path.exists(tmp.name)

        job = Job.create_single(plugin_id="sentiment", ttl=0, temp_files=[tmp.name])
        manager.store(job)
        time.sleep(0.01)
        manager.cleanup_expired()
        assert not os.path.exists(tmp.name)

    def test_cleanup_ignores_missing_temp_files(self, manager):
        job = Job.create_single(plugin_id="sentiment", ttl=0, temp_files=["/tmp/nonexistent_abc123"])
        manager.store(job)
        time.sleep(0.01)
        # Não deve levantar exceção
        manager.cleanup_expired()


class TestJobManagerExecution:
    @pytest.mark.asyncio
    async def test_submit_single_job_completes(self, manager):
        """Plugin simples roda e job fica completed."""
        def fake_executor(job_id):
            return {"sentiment_score": 0.85}

        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        await manager.submit(job.id, fake_executor)

        # Aguarda execução
        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.completed
        assert result_job.result == {"sentiment_score": 0.85}
        assert result_job.started_at is not None
        assert result_job.completed_at is not None
        assert result_job.progress == 1.0

    @pytest.mark.asyncio
    async def test_submit_single_job_failure(self, manager):
        """Plugin que levanta exceção → job failed."""
        def failing_executor(job_id):
            raise RuntimeError("Plugin crashed")

        job = Job.create_single(plugin_id="sentiment")
        manager.store(job)
        await manager.submit(job.id, failing_executor)

        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.failed
        assert "Plugin crashed" in result_job.error

    @pytest.mark.asyncio
    async def test_submit_pipeline_job_completes(self, manager):
        """Pipeline com 3 steps roda sequencialmente."""
        call_order = []

        def make_executor(step_idx):
            def executor(job_id):
                call_order.append(step_idx)
                return {f"result_{step_idx}": True}
            return executor

        job = Job.create_pipeline(plugin_ids=["a", "b", "c"])
        manager.store(job)

        executors = [make_executor(i) for i in range(3)]
        await manager.submit_pipeline(job.id, executors)

        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.completed
        assert call_order == [0, 1, 2]
        assert all(s.status == JobStatus.completed for s in result_job.steps)

    @pytest.mark.asyncio
    async def test_pipeline_fail_fast(self, manager):
        """Pipeline para no primeiro step que falha."""
        def ok_executor(job_id):
            return {"ok": True}

        def fail_executor(job_id):
            raise RuntimeError("Step 2 failed")

        job = Job.create_pipeline(plugin_ids=["a", "b", "c"])
        manager.store(job)

        executors = [ok_executor, fail_executor, ok_executor]
        await manager.submit_pipeline(job.id, executors)

        for _ in range(50):
            if manager.get(job.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        result_job = manager.get(job.id)
        assert result_job.status == JobStatus.failed
        assert result_job.steps[0].status == JobStatus.completed
        assert result_job.steps[1].status == JobStatus.failed
        assert result_job.steps[2].status == JobStatus.pending  # never ran

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, manager):
        """Segundo job fica pending até o primeiro terminar."""
        gate = asyncio.Event()

        def slow_executor(job_id):
            import time
            for _ in range(100):
                if gate.is_set():
                    break
                time.sleep(0.01)
            return {"done": True}

        j1 = Job.create_single(plugin_id="heavy_a")
        j2 = Job.create_single(plugin_id="heavy_b")
        manager.store(j1)
        manager.store(j2)

        await manager.submit(j1.id, slow_executor)
        await asyncio.sleep(0.05)  # Dá tempo do j1 iniciar
        await manager.submit(j2.id, slow_executor)
        await asyncio.sleep(0.05)

        # j1 rodando, j2 deve estar pending
        assert manager.get(j1.id).status == JobStatus.running
        assert manager.get(j2.id).status == JobStatus.pending

        # Libera j1
        gate.set()
        for _ in range(100):
            if manager.get(j2.id).status.is_terminal:
                break
            await asyncio.sleep(0.05)

        assert manager.get(j1.id).status == JobStatus.completed
        assert manager.get(j2.id).status == JobStatus.completed
