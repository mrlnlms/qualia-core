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
