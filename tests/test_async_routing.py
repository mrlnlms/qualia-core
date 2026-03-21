"""Testes para roteamento sync/async dos endpoints existentes."""
import pytest
from unittest.mock import MagicMock

from qualia.api.routing import should_run_async


class TestShouldRunAsync:
    def test_light_plugin_default_is_sync(self):
        meta = MagicMock(heavy=False)
        assert should_run_async(meta, sync_override=False, async_override=False, is_pipeline=False) is False

    def test_heavy_plugin_default_is_async(self):
        meta = MagicMock(heavy=True)
        assert should_run_async(meta, sync_override=False, async_override=False, is_pipeline=False) is True

    def test_heavy_plugin_sync_override(self):
        meta = MagicMock(heavy=True)
        assert should_run_async(meta, sync_override=True, async_override=False, is_pipeline=False) is False

    def test_light_plugin_async_override(self):
        meta = MagicMock(heavy=False)
        assert should_run_async(meta, sync_override=False, async_override=True, is_pipeline=False) is True

    def test_pipeline_default_is_async(self):
        assert should_run_async(None, sync_override=False, async_override=False, is_pipeline=True) is True

    def test_pipeline_sync_override(self):
        assert should_run_async(None, sync_override=True, async_override=False, is_pipeline=True) is False

    def test_sync_and_async_both_true_sync_wins(self):
        meta = MagicMock(heavy=True)
        assert should_run_async(meta, sync_override=True, async_override=True, is_pipeline=False) is False


from starlette.testclient import TestClient
from qualia.api import app
from qualia.api.deps import set_job_manager
from qualia.api.jobs import JobManager


@pytest.fixture(autouse=True)
def fresh_manager():
    manager = JobManager(max_concurrent=1)
    set_job_manager(manager)
    yield manager


@pytest.fixture
def client():
    return TestClient(app)


class TestAnalyzeAsyncRouting:
    def test_light_plugin_returns_200_sync(self, client):
        """Plugin leve sem override -> sync como hoje."""
        resp = client.post("/analyze/sentiment_analyzer", json={
            "text": "I love this product",
            "config": {},
        })
        assert resp.status_code == 200

    def test_light_plugin_async_override_returns_202(self, client):
        """Plugin leve com ?async=true -> 202 + job_id."""
        resp = client.post("/analyze/sentiment_analyzer?async=true", json={
            "text": "I love this product",
            "config": {},
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert "status_url" in data
        assert "stream_url" in data


class TestProcessAsyncRouting:
    def test_process_sync_default(self, client):
        """Document plugin leve sem override -> sync 200."""
        resp = client.post("/process/teams_cleaner", json={
            "text": "Some document text to process for analysis.",
            "config": {},
        })
        assert resp.status_code == 200

    def test_process_async_override(self, client):
        """Document plugin com ?async=true -> 202 + job_id."""
        resp = client.post("/process/teams_cleaner?async=true", json={
            "text": "Some document text to process for analysis.",
            "config": {},
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert "status_url" in data
        assert "stream_url" in data

    def test_process_sync_override_stays_sync(self, client):
        """Document plugin com ?sync=true -> sync 200."""
        resp = client.post("/process/teams_cleaner?sync=true", json={
            "text": "Some document text to process for analysis.",
            "config": {},
        })
        assert resp.status_code == 200


class TestVisualizeAsyncRouting:
    VIZ_DATA = {"word_frequencies": {"hello": 5, "world": 3, "test": 2}}

    def test_visualize_sync_default(self, client):
        """Visualizer leve sem override -> sync 200."""
        resp = client.post("/visualize/wordcloud_d3", json={
            "data": self.VIZ_DATA,
            "config": {},
            "output_format": "html",
        })
        assert resp.status_code == 200

    def test_visualize_async_override(self, client):
        """Visualizer com ?async=true -> 202 + job_id."""
        resp = client.post("/visualize/wordcloud_d3?async=true", json={
            "data": self.VIZ_DATA,
            "config": {},
            "output_format": "html",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert "status_url" in data


class TestPipelineAsyncRouting:
    def test_pipeline_async_by_default(self, client):
        """Pipeline sem parâmetros -> 202 (async por default)."""
        resp = client.post("/pipeline", data={
            "steps": '[{"plugin_id": "sentiment_analyzer"}]',
            "text": "I love this product!",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert "status_url" in data
        assert "stream_url" in data

    def test_pipeline_sync_override(self, client):
        """Pipeline com ?sync=true -> 200 (sync, como antes)."""
        resp = client.post("/pipeline?sync=true", data={
            "steps": '[{"plugin_id": "sentiment_analyzer"}]',
            "text": "I love this product!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["steps_executed"] == 1
