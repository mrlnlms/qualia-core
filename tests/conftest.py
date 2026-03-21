"""
Fixtures compartilhadas para os testes do Qualia.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qualia.api import app


# Diretórios de artefatos que os testes geram
# Nota: NÃO incluir "cache/" (pode conter dados de dev) nem ".pytest_cache/" (gerido pelo pytest, necessário para --lf)
_PROJECT_ROOT = Path(__file__).parent.parent
_ARTIFACTS = []


def pytest_sessionfinish(session, exitstatus):
    """Limpa artefatos gerados pelos testes ao final da sessão."""
    for path in _ARTIFACTS:
        if path.is_dir():
            shutil.rmtree(path)


@pytest.fixture(autouse=True)
def _ensure_job_manager():
    """Garante que JobManager está inicializado para todos os testes."""
    from qualia.api.deps import get_job_manager, set_job_manager
    try:
        get_job_manager()
    except RuntimeError:
        from qualia.api.jobs import JobManager
        set_job_manager(JobManager(max_concurrent=2))


@pytest.fixture
def client():
    """Cliente de teste para a API"""
    return TestClient(app)


@pytest.fixture
def sample_text():
    """Texto de exemplo para testes"""
    return "Este é um texto de teste. Teste teste palavra repetida repetida."


@pytest.fixture(autouse=False)
def reset_monitor_state():
    """Reseta estado global do monitor entre testes.

    Nao é autouse — só aplica nos testes que pedem explicitamente.
    """
    from qualia.api.monitor import metrics, request_times, active_streams
    import time

    # Salvar estado
    old_total = metrics.requests_total
    old_rpm = metrics.requests_per_minute
    old_errors = metrics.errors_total
    old_last_error = metrics.last_error
    old_plugin_usage = dict(metrics.plugin_usage)
    old_webhook_stats = dict(metrics.webhook_stats)

    # Resetar
    metrics.requests_total = 0
    metrics.requests_per_minute = 0.0
    metrics.errors_total = 0
    metrics.last_error = ""
    metrics.plugin_usage.clear()
    metrics.webhook_stats.clear()
    request_times.clear()
    active_streams.clear()

    yield

    # Restaurar (evita poluição entre módulos de teste)
    metrics.requests_total = old_total
    metrics.requests_per_minute = old_rpm
    metrics.errors_total = old_errors
    metrics.last_error = old_last_error
    metrics.plugin_usage.clear()
    metrics.plugin_usage.update(old_plugin_usage)
    metrics.webhook_stats.clear()
    metrics.webhook_stats.update(old_webhook_stats)
