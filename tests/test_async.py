"""
Testes de async e concorrência da API do Qualia.

Valida que requests simultâneos funcionam, que asyncio.to_thread
não bloqueia o event loop, e que timeouts/erros se comportam.
"""

import pytest
import pytest_asyncio
import asyncio
import httpx
import time

from qualia.api import app

pytestmark = pytest.mark.asyncio


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def ac():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def analyze_payload():
    return {
        "text": "Este é um texto para análise de frequência de palavras repetidas repetidas.",
        "config": {},
    }


# =============================================================================
# REQUESTS CONCORRENTES
# =============================================================================

class TestConcurrentRequests:

    async def test_simultaneous_analyze_requests(self, ac):
        """5 requests simultâneos ao analyze devem todos retornar 200.

        Usa config default (remove_stopwords=True) — o warm-up do NLTK
        no __init__ do plugin resolve a race condition do LazyCorpusLoader.
        """
        tasks = [
            ac.post("/analyze/word_frequency", json={
                "text": f"Texto único número {i} para evitar colisão de cache e doc_id.",
                "config": {},
            })
            for i in range(5)
        ]
        responses = await asyncio.gather(*tasks)
        for i, r in enumerate(responses):
            assert r.status_code == 200, f"Request {i} falhou: {r.text}"
            assert r.json()["status"] == "success"

    async def test_mixed_concurrent_requests(self, ac, analyze_payload):
        """Mix de endpoints concorrentes não deve crashar"""
        tasks = [
            ac.get("/health"),
            ac.get("/plugins"),
            ac.post("/analyze/word_frequency", json=analyze_payload),
            ac.get("/health"),
            ac.get("/plugins"),
        ]
        responses = await asyncio.gather(*tasks)
        for r in responses:
            assert r.status_code == 200

    async def test_concurrent_pipelines(self, ac):
        """3 pipelines simultâneos completam sem erro"""
        tasks = []
        for i in range(3):
            tasks.append(
                ac.post(
                    "/pipeline?sync=true",
                    data={
                        "steps": '[{"plugin_id": "word_frequency", "config": {}}]',
                        "text": f"Texto número {i} para pipeline concorrente.",
                    },
                )
            )
        responses = await asyncio.gather(*tasks)
        for r in responses:
            assert r.status_code == 200
            assert r.json()["steps_executed"] == 1


# =============================================================================
# EVENT LOOP NÃO BLOQUEADO
# =============================================================================

class TestEventLoopNotBlocked:

    async def test_health_responds_during_analysis(self, ac):
        """Health check responde rápido mesmo com análise rodando"""
        big_text = "Palavra repetida muitas vezes no texto grande. " * 500
        payload = {"text": big_text, "config": {}}

        # Dispara análise e health ao mesmo tempo
        analyze_task = asyncio.create_task(
            ac.post("/analyze/word_frequency", json=payload)
        )
        await asyncio.sleep(0.01)

        start = time.perf_counter()
        health_response = await ac.get("/health")
        health_time = time.perf_counter() - start

        assert health_response.status_code == 200
        assert health_time < 1.0

        analyze_response = await analyze_task
        assert analyze_response.status_code == 200


# =============================================================================
# TIMEOUT
# =============================================================================

class TestVisualization:

    async def test_fast_render_returns_200(self, ac):
        """Visualize com dados válidos retorna 200"""
        analyze_resp = await ac.post(
            "/analyze/word_frequency",
            json={"text": "Gato gato cachorro pato gato cachorro", "config": {}},
        )
        assert analyze_resp.status_code == 200
        freq_data = analyze_resp.json()["result"]

        viz_resp = await ac.post(
            "/visualize/wordcloud_d3",
            json={
                "data": freq_data,
                "config": {"width": 400, "height": 200},
                "output_format": "html",
            },
        )
        assert viz_resp.status_code == 200
        assert "html" in viz_resp.json()

    async def test_nonexistent_visualizer_returns_error(self, ac):
        """Visualizer inexistente retorna erro (400 ou 404)"""
        resp = await ac.post(
            "/visualize/nonexistent",
            json={"data": {}, "config": {}, "output_format": "png"},
        )
        assert resp.status_code in (400, 404)


# =============================================================================
# PIPELINE ERRORS
# =============================================================================

class TestPipelineErrors:

    async def test_invalid_plugin_in_pipeline(self, ac):
        """Plugin inexistente no pipeline retorna 404"""
        resp = await ac.post(
            "/pipeline?sync=true",
            data={
                "steps": '[{"plugin_id": "nonexistent_plugin", "config": {}}]',
                "text": "Texto de teste.",
            },
        )
        assert resp.status_code == 404

    async def test_invalid_steps_json(self, ac):
        """JSON inválido no campo steps retorna 422"""
        resp = await ac.post(
            "/pipeline?sync=true",
            data={"steps": "not valid json [[[", "text": "Teste"},
        )
        assert resp.status_code == 422

    async def test_empty_pipeline(self, ac):
        """Pipeline vazio retorna 422"""
        resp = await ac.post(
            "/pipeline?sync=true",
            data={"steps": "[]", "text": "Teste"},
        )
        assert resp.status_code == 422
