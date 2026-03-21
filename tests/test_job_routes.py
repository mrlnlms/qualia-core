"""Testes para os endpoints /jobs."""
import time

import pytest

from starlette.testclient import TestClient
from qualia.api import app
from qualia.api.deps import set_job_manager
from qualia.api.jobs import JobManager
from qualia.core.jobs import Job, JobStatus


@pytest.fixture(autouse=True)
def fresh_manager():
    """JobManager limpo para cada teste — setado ANTES do TestClient."""
    manager = JobManager(max_concurrent=1)
    set_job_manager(manager)
    yield manager


@pytest.fixture
def client():
    return TestClient(app)


class TestGetJob:
    def test_get_existing_job(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment")
        fresh_manager.store(job)
        resp = client.get(f"/jobs/{job.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job.id
        assert data["status"] == "pending"

    def test_get_nonexistent_job_returns_404(self, client):
        resp = client.get("/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_get_expired_job_returns_404(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment", ttl=0)
        fresh_manager.store(job)
        time.sleep(0.01)
        resp = client.get(f"/jobs/{job.id}")
        assert resp.status_code == 404


class TestListJobs:
    def test_list_empty(self, client):
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_all_jobs(self, client, fresh_manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        fresh_manager.store(j1)
        fresh_manager.store(j2)
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_filter_by_status(self, client, fresh_manager):
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        j2.status = JobStatus.running
        fresh_manager.store(j1)
        fresh_manager.store(j2)
        resp = client.get("/jobs?status=pending")
        assert len(resp.json()) == 1

    def test_list_filter_by_plugin(self, client, fresh_manager):
        j1 = Job.create_single(plugin_id="sentiment")
        j2 = Job.create_single(plugin_id="wordcloud")
        fresh_manager.store(j1)
        fresh_manager.store(j2)
        resp = client.get("/jobs?plugin_id=sentiment")
        assert len(resp.json()) == 1

    def test_list_invalid_status_returns_422(self, client):
        resp = client.get("/jobs?status=bogus")
        assert resp.status_code == 422


class TestCancelJob:
    def test_cancel_pending_job(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment")
        fresh_manager.store(job)
        resp = client.delete(f"/jobs/{job.id}")
        assert resp.status_code == 200
        assert fresh_manager.get(job.id).status == JobStatus.cancelled

    def test_cancel_running_job_returns_409(self, client, fresh_manager):
        job = Job.create_single(plugin_id="sentiment")
        job.status = JobStatus.running
        fresh_manager.store(job)
        resp = client.delete(f"/jobs/{job.id}")
        assert resp.status_code == 409

    def test_cancel_nonexistent_returns_404(self, client):
        resp = client.delete("/jobs/nonexistent")
        assert resp.status_code == 404
