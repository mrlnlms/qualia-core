"""Upload → job → contrato real do core, com inferência substituída."""
import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
import httpx
import pytest

from qualia.api.jobs import JobManager
from qualia.core import QualiaCore
from qualia.core.config import ConfigurationRegistry
from plugins.documents.transcription_structured import TranscriptionStructuredPlugin


@pytest.fixture
def isolated_api(tmp_path, monkeypatch):
    empty = tmp_path / 'plugins'
    empty.mkdir()
    core = QualiaCore(plugins_dir=empty, cache_dir=tmp_path / 'cache')
    plugin = TranscriptionStructuredPlugin()
    core.registry[plugin.meta().id] = plugin.meta()
    core.loader.loaded_plugins[plugin.meta().id] = plugin
    core.config_registry = ConfigurationRegistry(core.registry)
    manager = JobManager(max_concurrent=1)
    transcribe = importlib.import_module('qualia.api.routes.transcribe')
    jobs = importlib.import_module('qualia.api.routes.jobs')
    monkeypatch.setattr(transcribe, 'get_core', lambda: core)
    monkeypatch.setattr(transcribe, 'get_job_manager', lambda: manager)
    monkeypatch.setattr(jobs, 'get_job_manager', lambda: manager)
    app = FastAPI()
    app.include_router(transcribe.router)
    app.include_router(jobs.router)
    return app, manager


@pytest.mark.asyncio
async def test_async_upload_preserves_structured_result_and_cleans_source(isolated_api, monkeypatch):
    app, manager = isolated_api
    seen = []
    expected = {key: {} for key in TranscriptionStructuredPlugin().meta().provides}
    expected.update(transcription='Participant 3\nOlá', duration=42.5, detected_language='pt',
                    status='completed', exports={'txt': {'content': 'Participant 3\nOlá'}})

    def worker(audio, **config):
        seen.append(Path(audio))
        assert Path(audio).read_bytes() == b'fake audio'
        assert config['speech_boundaries'] is False
        return expected

    monkeypatch.setattr('plugins.documents.transcription_structured.run_structured', worker)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/transcribe/transcription_structured',
                                     files={'file': ('sample.wav', b'fake audio')}, data={'config': '{}'})
        assert response.status_code == 202
        job_id = response.json()['job_id']
        for _ in range(100):
            state = (await client.get(f'/jobs/{job_id}')).json()
            if state['status'] in ('completed', 'failed'):
                break
            await asyncio.sleep(.01)
        assert state['status'] == 'completed', state
        assert state['result'] == expected
    assert len(seen) == 1
    assert not seen[0].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('config', [{'num_speakers': 2}, {'language': 'auto'}, {'device': 'cuda'}])
async def test_invalid_config_does_not_queue_model_work(isolated_api, monkeypatch, config):
    app, manager = isolated_api
    worker = Mock(side_effect=AssertionError('não iniciar modelos'))
    monkeypatch.setattr('plugins.documents.transcription_structured.run_structured', worker)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/transcribe/transcription_structured',
                                     files={'file': ('sample.wav', b'fake')}, data={'config': json.dumps(config)})
    assert response.status_code == 422
    assert not manager.list_jobs()
    worker.assert_not_called()


@pytest.mark.asyncio
async def test_worker_failure_is_reported_and_upload_is_cleaned(isolated_api, monkeypatch):
    app, manager = isolated_api
    seen = []

    def fail(audio, **config):
        seen.append(Path(audio))
        raise RuntimeError('Ambiente de alinhamento indisponível')

    monkeypatch.setattr('plugins.documents.transcription_structured.run_structured', fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/transcribe/transcription_structured',
                                     files={'file': ('sample.wav', b'fake audio')})
        job_id = response.json()['job_id']
        for _ in range(100):
            state = (await client.get(f'/jobs/{job_id}')).json()
            if state['status'] == 'failed':
                break
            await asyncio.sleep(.01)
    assert state['status'] == 'failed'
    assert 'alinhamento' in state['error']
    assert state['result'] is None
    assert not seen[0].exists()
