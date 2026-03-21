"""Testes de integração — fluxo async completo."""
import asyncio

import pytest
import pytest_asyncio
import httpx

from qualia.api import app
from qualia.api.deps import set_job_manager
from qualia.api.jobs import JobManager


@pytest.fixture(autouse=True)
def fresh_manager():
    manager = JobManager(max_concurrent=1)
    set_job_manager(manager)
    yield manager


@pytest_asyncio.fixture
async def ac():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestAsyncFlowIntegration:
    @pytest.mark.asyncio
    async def test_analyze_async_then_poll(self, ac):
        """Analyze com ?async=true → poll até completed."""
        resp = await ac.post("/analyze/sentiment_analyzer?async=true", json={
            "text": "This is a great product!",
            "config": {},
        })
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # Poll até completar
        for _ in range(50):
            resp = await ac.get(f"/jobs/{job_id}")
            assert resp.status_code == 200
            if resp.json()["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"] is not None

    @pytest.mark.asyncio
    async def test_analyze_sync_unchanged(self, ac):
        """Analyze sem parâmetros → sync como sempre."""
        resp = await ac.post("/analyze/sentiment_analyzer", json={
            "text": "This is a great product!",
            "config": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "result" in data

    @pytest.mark.asyncio
    async def test_process_async_then_poll(self, ac):
        """Process com ?async=true → poll até completed."""
        resp = await ac.post("/process/teams_cleaner?async=true", json={
            "text": "The quick brown fox jumps over the lazy dog. This is a simple sentence.",
            "config": {},
        })
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        for _ in range(50):
            resp = await ac.get(f"/jobs/{job_id}")
            if resp.json()["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        assert resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_pipeline_async_default(self, ac):
        """Pipeline → async por default → poll até completed."""
        resp = await ac.post("/pipeline", data={
            "steps": '[{"plugin_id": "sentiment_analyzer"}]',
            "text": "This is amazing!",
        })
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        for _ in range(50):
            resp = await ac.get(f"/jobs/{job_id}")
            if resp.json()["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        data = resp.json()
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_cancel_pending_job_via_api(self, ac, fresh_manager):
        """Cancela job pending via DELETE."""
        from qualia.core.jobs import Job
        job = Job.create_single(plugin_id="sentiment_analyzer")
        fresh_manager.store(job)

        resp = await ac.delete(f"/jobs/{job.id}")
        assert resp.status_code == 200

        resp = await ac.get(f"/jobs/{job.id}")
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_list_jobs_returns_active(self, ac, fresh_manager):
        """GET /jobs retorna jobs ativos."""
        from qualia.core.jobs import Job
        j1 = Job.create_single(plugin_id="a")
        j2 = Job.create_single(plugin_id="b")
        fresh_manager.store(j1)
        fresh_manager.store(j2)

        resp = await ac.get("/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_get_nonexistent_job_404(self, ac):
        """GET /jobs/{id} com id inexistente → 404."""
        resp = await ac.get("/jobs/nonexistent-uuid")
        assert resp.status_code == 404


class TestRegressionExistingEndpoints:
    @pytest.mark.asyncio
    async def test_analyze_sync_no_regression(self, ac):
        resp = await ac.post("/analyze/sentiment_analyzer", json={
            "text": "Test text for regression",
            "config": {},
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_process_sync_no_regression(self, ac):
        resp = await ac.post("/process/teams_cleaner", json={
            "text": "Test text for regression checking with multiple words.",
            "config": {},
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_pipeline_sync_override_no_regression(self, ac):
        resp = await ac.post("/pipeline?sync=true", data={
            "steps": '[{"plugin_id": "sentiment_analyzer"}]',
            "text": "Test text",
        })
        assert resp.status_code == 200
