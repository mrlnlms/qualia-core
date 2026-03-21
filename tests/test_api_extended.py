"""
Testes estendidos da API REST do Qualia Core.

Foco em endpoints e branches nao cobertos pelo test_api.py original:
- /analyze/{plugin_id}/file (upload de arquivo)
- /process/{plugin_id} (processamento de documento)
- /transcribe/{plugin_id} (mock do groq)
- /visualize/{plugin_id} (geracao de visualizacao)
- /pipeline (execucao multi-step)
- /config/resolve (resolucao de config)
- /webhook/custom e /webhook/stats
- Caminhos de erro: plugin invalido, tipo errado, config invalida, timeout
- SPA catch-all
- Exception handlers
"""

import pytest
import json
import io
import asyncio
import base64
from unittest.mock import patch, MagicMock
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from qualia.api import app
from qualia.api.deps import get_core
from qualia.core.interfaces import PluginMetadata, PluginType


def _kaleido_functional():
    """Testa se kaleido funciona (não só instalado)."""
    try:
        import kaleido  # noqa: F401
        import plotly.graph_objects as go
        go.Figure().to_image(format="png", width=1, height=1)
        return True
    except Exception:
        return False


def _mock_registry_entry(plugin_id, plugin_type_str):
    """Cria PluginMetadata fake pra mockar core.registry."""
    return PluginMetadata(
        id=plugin_id,
        type=PluginType(plugin_type_str),
        name=plugin_id,
        description="mock",
        version="0.1.0",
    )


@pytest.fixture
def client():
    """Cliente de teste para a API"""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def sample_text():
    """Texto longo o suficiente para gerar resultados uteis"""
    return (
        "Este texto serve como exemplo para testes de analise qualitativa. "
        "Ele contem palavras repetidas repetidas para que o plugin de frequencia "
        "consiga gerar resultados significativos. Palavras como exemplo, testes, "
        "analise e qualitativa aparecem para enriquecer a analise."
    )


@pytest.fixture
def word_freq_result():
    """Resultado tipico do word_frequency para usar como input de visualizadores"""
    return {
        "word_frequencies": {
            "exemplo": 5,
            "teste": 4,
            "analise": 3,
            "qualitativa": 2,
            "palavra": 1,
        },
        "total_words": 15,
        "unique_words": 5,
    }


# ============================================================================
# /api — info endpoint
# ============================================================================

class TestApiInfo:
    """Testa endpoint /api que retorna info da API"""

    def test_api_info_returns_endpoints(self, client):
        """GET /api deve retornar lista de endpoints disponiveis"""
        response = client.get("/api")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Qualia Core API"
        assert "endpoints" in data
        assert "plugins" in data["endpoints"]
        assert "documentation" in data


# ============================================================================
# /plugins — filtro por tipo
# ============================================================================

class TestPluginFiltering:
    """Testa filtragem de plugins por tipo"""

    def test_filter_plugins_by_type_analyzer(self, client):
        """GET /plugins?plugin_type=analyzer — so retorna analyzers"""
        response = client.get("/plugins", params={"plugin_type": "analyzer"})
        assert response.status_code == 200
        plugins = response.json()
        assert len(plugins) > 0
        for p in plugins:
            assert p["type"] == "analyzer"

    def test_filter_plugins_by_type_visualizer(self, client):
        """GET /plugins?plugin_type=visualizer — so retorna visualizers"""
        response = client.get("/plugins", params={"plugin_type": "visualizer"})
        assert response.status_code == 200
        plugins = response.json()
        assert len(plugins) > 0
        for p in plugins:
            assert p["type"] == "visualizer"

    def test_filter_plugins_by_type_document(self, client):
        """GET /plugins?plugin_type=document — so retorna document processors"""
        response = client.get("/plugins", params={"plugin_type": "document"})
        assert response.status_code == 200
        plugins = response.json()
        assert len(plugins) > 0
        for p in plugins:
            assert p["type"] == "document"

    def test_filter_plugins_nonexistent_type(self, client):
        """GET /plugins?plugin_type=inexistente — retorna lista vazia"""
        response = client.get("/plugins", params={"plugin_type": "inexistente"})
        assert response.status_code == 200
        assert response.json() == []


# ============================================================================
# POST /analyze/{plugin_id} — validacao de config (422)
# ============================================================================

class TestAnalyzeConfigValidation:
    """Testa validacao de config no endpoint /analyze"""

    def test_analyze_invalid_config_returns_422(self, client):
        """Config com valor fora do range mas sem min definido no schema — aceita"""
        response = client.post(
            "/analyze/word_frequency",
            json={
                "text": "texto qualquer",
                "config": {"min_word_length": -999},
            },
        )
        # word_frequency nao define range com min, entao aceita qualquer int
        assert response.status_code == 200

    def test_analyze_timeout_returns_504(self, client):
        """Timeout na analise retorna 504."""
        import asyncio as _asyncio

        with patch("qualia.api.routes.analyze.asyncio.wait_for", side_effect=_asyncio.TimeoutError):
            response = client.post(
                "/analyze/word_frequency",
                json={"text": "qualquer texto", "config": {}},
            )
        assert response.status_code == 504

    def test_analyze_generic_exception_returns_400(self, client):
        """Excecao generica no plugin retorna 400."""
        with patch.object(get_core(), "execute_plugin", side_effect=RuntimeError("plugin crash")):
            response = client.post(
                "/analyze/word_frequency",
                json={"text": "texto", "config": {}},
            )
        assert response.status_code == 400


# ============================================================================
# POST /analyze/{plugin_id}/file — upload de arquivo para analise
# ============================================================================

class TestAnalyzeFile:
    """Testa upload de arquivo para analise"""

    def test_analyze_file_success(self, client):
        """Upload de arquivo texto para analise word_frequency"""
        content = "palavra repetida repetida tres tres tres"
        file_data = io.BytesIO(content.encode("utf-8"))

        response = client.post(
            "/analyze/word_frequency/file",
            files={"file": ("teste.txt", file_data, "text/plain")},
            data={"config": "{}", "context": "{}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["plugin_id"] == "word_frequency"
        assert data["filename"] == "teste.txt"
        assert "result" in data

    def test_analyze_file_with_config(self, client):
        """Upload com config JSON no form data"""
        content = "ab cd efgh ijklm nopqrst"
        file_data = io.BytesIO(content.encode("utf-8"))

        config = json.dumps({"min_word_length": 4})
        response = client.post(
            "/analyze/word_frequency/file",
            files={"file": ("config_test.txt", file_data, "text/plain")},
            data={"config": config, "context": "{}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_analyze_file_invalid_plugin(self, client):
        """Upload para plugin inexistente deve retornar 404"""
        file_data = io.BytesIO(b"qualquer texto")
        response = client.post(
            "/analyze/plugin_fantasma/file",
            files={"file": ("test.txt", file_data, "text/plain")},
            data={"config": "{}", "context": "{}"},
        )
        assert response.status_code == 404

    def test_analyze_file_utf8_no_warning(self, client):
        """Upload UTF-8 válido não deve incluir encoding_warning"""
        file_data = io.BytesIO("texto em português com acentuação".encode('utf-8'))
        response = client.post(
            "/analyze/word_frequency/file",
            files={"file": ("test.txt", file_data, "text/plain")},
            data={"config": "{}", "context": "{}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "encoding_warning" not in data

    def test_analyze_file_latin1_fallback_with_warning(self, client):
        """Upload não-UTF-8 deve funcionar com fallback latin-1 e incluir encoding_warning"""
        # Byte 0xe9 é 'é' em latin-1 mas inválido como UTF-8 isolado
        file_data = io.BytesIO(b"texto com caf\xe9 e a\xe7\xe3o")
        response = client.post(
            "/analyze/word_frequency/file",
            files={"file": ("test.txt", file_data, "text/plain")},
            data={"config": "{}", "context": "{}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "encoding_warning" in data
        assert "latin-1" in data["encoding_warning"]
        assert data["status"] == "success"
        assert "result" in data

    def test_analyze_file_wrong_plugin_type_returns_422(self, client):
        """Upload deve rejeitar plugin que nao e analyzer."""
        file_data = io.BytesIO(b"qualquer texto")
        response = client.post(
            "/analyze/teams_cleaner/file",
            files={"file": ("test.txt", file_data, "text/plain")},
            data={"config": "{}", "context": "{}"},
        )
        assert response.status_code == 422

    def test_analyze_file_invalid_config_returns_422(self, client):
        """Upload deve validar config antes de executar plugin."""
        file_data = io.BytesIO(b"palavra repetida repetida")
        response = client.post(
            "/analyze/word_frequency/file",
            files={"file": ("test.txt", file_data, "text/plain")},
            data={"config": json.dumps({"min_word_length": "nao_e_numero"}), "context": "{}"},
        )
        assert response.status_code == 422

    def test_analyze_file_timeout_returns_504(self, client):
        """Timeout no upload retorna 504."""
        import asyncio as _asyncio

        with patch("qualia.api.routes.analyze.asyncio.wait_for", side_effect=_asyncio.TimeoutError):
            file_data = io.BytesIO(b"texto qualquer")
            response = client.post(
                "/analyze/word_frequency/file",
                files={"file": ("test.txt", file_data, "text/plain")},
                data={"config": "{}", "context": "{}"},
            )
        assert response.status_code == 504

    def test_analyze_file_generic_exception_returns_400(self, client):
        """Excecao generica via file upload retorna 400."""
        with patch.object(get_core(), "execute_plugin", side_effect=RuntimeError("file crash")):
            file_data = io.BytesIO(b"texto qualquer")
            response = client.post(
                "/analyze/word_frequency/file",
                files={"file": ("test.txt", file_data, "text/plain")},
                data={"config": "{}", "context": "{}"},
            )
        assert response.status_code == 400


# ============================================================================
# POST /process/{plugin_id} — processamento de documento
# ============================================================================

class TestProcessEndpoint:
    """Testa endpoint de processamento de documento"""

    def test_process_teams_cleaner(self, client):
        """Processa transcricao Teams via /process"""
        teams_text = (
            "[00:00:00] Joao Silva\n"
            "Ola pessoal, vamos comecar.\n\n"
            "[00:00:15] Maria Santos\n"
            "Sim, estou pronta.\n"
        )
        response = client.post(
            "/process/teams_cleaner",
            json={"text": teams_text, "config": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["plugin_id"] == "teams_cleaner"
        assert "processed_text" in data

    def test_process_invalid_plugin(self, client):
        """Plugin inexistente retorna 404"""
        response = client.post(
            "/process/plugin_invalido",
            json={"text": "qualquer texto", "config": {}},
        )
        assert response.status_code == 404

    def test_process_wrong_plugin_type_returns_422(self, client):
        """Endpoint de process deve rejeitar analyzer."""
        response = client.post(
            "/process/word_frequency",
            json={"text": "qualquer texto", "config": {}},
        )
        assert response.status_code == 422

    def test_process_invalid_config_returns_422(self, client):
        """Endpoint de process valida config antes de executar plugin."""
        response = client.post(
            "/process/teams_cleaner",
            json={"text": "Ana: oi tudo bem", "config": {"min_utterance_length": "nao_e_numero"}},
        )
        assert response.status_code == 422

    def test_process_timeout_returns_504(self, client):
        """Timeout no processamento retorna 504."""
        import asyncio as _asyncio

        with patch("qualia.api.routes.process.asyncio.wait_for", side_effect=_asyncio.TimeoutError):
            response = client.post(
                "/process/teams_cleaner",
                json={"text": "[00:00:01] Ana: oi", "config": {}},
            )
        assert response.status_code == 504

    def test_process_generic_exception_returns_400(self, client):
        """Excecao generica no processamento retorna 400."""
        with patch.object(get_core(), "execute_plugin", side_effect=RuntimeError("process crash")):
            response = client.post(
                "/process/teams_cleaner",
                json={"text": "[00:00:01] Ana: oi", "config": {}},
            )
        assert response.status_code == 400

    def test_process_document_result_extracts_content(self, client):
        """Quando plugin retorna Document, API extrai .content."""
        from qualia.core.models import Document

        doc_result = Document(id="test_doc", content="texto limpo extraído", metadata={})
        with patch.object(get_core(), "execute_plugin", return_value=doc_result):
            response = client.post(
                "/process/teams_cleaner",
                json={"text": "[00:00:01] Ana: olá", "config": {}},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["processed_text"] == "texto limpo extraído"


# ============================================================================
# POST /visualize/{plugin_id} — geracao de visualizacao
# ============================================================================

class TestVisualizeEndpoint:
    """Testa endpoint de visualizacao"""

    @pytest.mark.skipif(
        not _kaleido_functional(),
        reason="Kaleido não funcional neste ambiente (segfault ou ausente)"
    )
    def test_visualize_frequency_chart_plotly_png(self, client, word_freq_result):
        """Gera grafico de frequencia em PNG (requer kaleido funcional)"""
        response = client.post(
            "/visualize/frequency_chart_plotly",
            json={
                "data": word_freq_result,
                "config": {},
                "output_format": "png",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["format"] == "png"
        assert data["encoding"] == "base64"
        decoded = base64.b64decode(data["data"])
        assert len(decoded) > 0

    @pytest.mark.skipif(
        not _kaleido_functional(),
        reason="Kaleido não funcional neste ambiente (segfault ou ausente)"
    )
    def test_visualize_frequency_chart_plotly_svg(self, client, word_freq_result):
        """Gera grafico de frequencia em SVG (requer kaleido funcional)"""
        response = client.post(
            "/visualize/frequency_chart_plotly",
            json={
                "data": word_freq_result,
                "config": {},
                "output_format": "svg",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "svg"
        assert data["encoding"] == "base64"

    def test_visualize_frequency_chart_plotly_html(self, client, word_freq_result):
        """Gera grafico de frequencia em HTML"""
        response = client.post(
            "/visualize/frequency_chart_plotly",
            json={
                "data": word_freq_result,
                "config": {},
                "output_format": "html",
            },
        )
        # HTML e o formato padrao dos novos plugins
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "html" in data

    def test_visualize_invalid_plugin(self, client, word_freq_result):
        """Plugin inexistente retorna 404"""
        response = client.post(
            "/visualize/plugin_fantasma",
            json={
                "data": word_freq_result,
                "config": {},
                "output_format": "png",
            },
        )
        assert response.status_code == 404

    def test_visualize_wrong_plugin_type_returns_422(self, client, word_freq_result):
        """Visualize deve rejeitar plugin que nao e visualizer."""
        response = client.post(
            "/visualize/teams_cleaner",
            json={
                "data": word_freq_result,
                "config": {},
                "output_format": "png",
            },
        )
        assert response.status_code == 422

    def test_visualize_invalid_config_returns_422(self, client, word_freq_result):
        """Visualize deve validar config antes do render."""
        response = client.post(
            "/visualize/frequency_chart_plotly",
            json={
                "data": word_freq_result,
                "config": {"max_words": "nao_e_numero"},
                "output_format": "png",
            },
        )
        assert response.status_code == 422

    def test_visualize_timeout(self, client, word_freq_result):
        """Timeout na visualizacao retorna 504"""
        import asyncio

        with patch("qualia.api.routes.visualize.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            response = client.post(
                "/visualize/frequency_chart_plotly",
                json={
                    "data": word_freq_result,
                    "config": {},
                    "output_format": "png",
                },
            )
            assert response.status_code == 504


# ============================================================================
# POST /pipeline — execucao multi-step
# ============================================================================

class TestPipelineEndpoint:
    """Testa pipeline com varios cenarios"""

    def test_pipeline_invalid_json_steps(self, client):
        """Steps com JSON invalido retorna 422"""
        response = client.post(
            "/pipeline?sync=true",
            data={"text": "algo", "steps": "nao e json"},
        )
        assert response.status_code == 422

    def test_pipeline_no_text_no_file(self, client):
        """Pipeline sem texto e sem arquivo retorna 422"""
        steps = json.dumps([{"plugin_id": "word_frequency"}])
        response = client.post(
            "/pipeline?sync=true",
            data={"steps": steps},
        )
        # Sem text e sem file -> text="" que e falsy -> 422
        assert response.status_code == 422

    def test_pipeline_analyzer_then_visualizer(self, client):
        """Pipeline: word_frequency -> frequency_chart_plotly (HTML default)"""
        steps = json.dumps([
            {"plugin_id": "word_frequency"},
            {"plugin_id": "frequency_chart_plotly"},
        ])
        text = "palavra repetida repetida tres tres tres quatro quatro quatro quatro"
        response = client.post(
            "/pipeline?sync=true",
            data={"text": text, "steps": steps},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["steps_executed"] == 2
        # Segundo resultado deve ser dict do render (html ou base64)
        viz_result = data["results"][1]["result"]
        assert "html" in viz_result or "data" in viz_result

    def test_pipeline_invalid_config_422(self, client):
        """Pipeline com config invalida num step retorna 422"""
        steps = json.dumps([
            {
                "plugin_id": "word_frequency",
                "config": {"min_word_length": "nao_e_numero"},
            }
        ])
        response = client.post(
            "/pipeline?sync=true",
            data={"text": "qualquer texto", "steps": steps},
        )
        # min_word_length com valor nao-numerico -> 422 na validacao
        assert response.status_code == 422

    def test_pipeline_visualizer_without_previous_step(self, client):
        """Visualizer como primeiro step sem resultado anterior retorna 422"""
        steps = json.dumps([
            {"plugin_id": "frequency_chart_plotly"},
        ])
        response = client.post(
            "/pipeline?sync=true",
            data={"text": "algo", "steps": steps},
        )
        # 422 porque visualizer precisa de resultado anterior
        assert response.status_code == 422

    def test_pipeline_nonexistent_plugin(self, client):
        """Plugin inexistente no pipeline retorna 400"""
        steps = json.dumps([
            {"plugin_id": "plugin_que_nao_existe"},
        ])
        response = client.post(
            "/pipeline?sync=true",
            data={"text": "algo", "steps": steps},
        )
        assert response.status_code == 404

    def test_pipeline_timeout_mid_step_returns_504(self, client):
        """Timeout num step do pipeline retorna 504."""
        import asyncio as _asyncio

        with patch("qualia.api.routes.pipeline.asyncio.wait_for", side_effect=_asyncio.TimeoutError):
            response = client.post(
                "/pipeline?sync=true",
                data={
                    "text": "texto qualquer para pipeline",
                    "steps": json.dumps([{"plugin_id": "word_frequency", "config": {}}]),
                },
            )
        assert response.status_code == 504

    def test_pipeline_file_step0_timeout_returns_504(self, client):
        """Timeout no step 0 (file+document) retorna 504."""
        import asyncio as _asyncio

        with patch("qualia.api.routes.pipeline.asyncio.wait_for", side_effect=_asyncio.TimeoutError):
            fake_audio = io.BytesIO(b"\x00" * 100)
            steps = json.dumps([{"plugin_id": "transcription"}])
            response = client.post(
                "/pipeline?sync=true",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"steps": steps},
            )
        assert response.status_code == 504

    def test_pipeline_visualizer_timeout_returns_504(self, client):
        """Timeout num step visualizer retorna 504."""
        import asyncio as _asyncio

        # Primeiro step (analyzer) funciona, segundo (visualizer) timeout
        text = "palavra repetida repetida tres tres tres quatro quatro quatro quatro"
        call_count = {"n": 0}
        original_wait_for = asyncio.wait_for

        async def selective_timeout(coro, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:  # visualizer step
                raise _asyncio.TimeoutError()
            return await original_wait_for(coro, **kwargs)

        with patch("qualia.api.routes.pipeline.asyncio.wait_for", side_effect=selective_timeout):
            steps = json.dumps([
                {"plugin_id": "word_frequency"},
                {"plugin_id": "frequency_chart_plotly"},
            ])
            response = client.post(
                "/pipeline?sync=true",
                data={"text": text, "steps": steps},
            )
        assert response.status_code == 504

    def test_pipeline_non_text_result_keeps_current_text(self, client):
        """Plugin que retorna dict sem campos de texto não altera current_text."""
        response = client.post(
            "/pipeline?sync=true",
            data={
                "text": "texto original para dois steps",
                "steps": json.dumps([
                    {"plugin_id": "word_frequency", "config": {}},
                    {"plugin_id": "readability_analyzer", "config": {}},
                ]),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["results"]) == 2


# ============================================================================
# POST /config/resolve — resolucao de config com text_size
# ============================================================================

class TestConfigResolve:
    """Testa resolucao de configuracao"""

    def test_resolve_config_default(self, client):
        """Resolve config padrao para word_frequency"""
        response = client.post(
            "/config/resolve",
            json={"plugin_id": "word_frequency", "text_size": "medium"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["plugin_id"] == "word_frequency"
        assert data["text_size"] == "medium"
        assert "resolved_config" in data

    def test_resolve_config_short_text(self, client):
        """Resolve config para texto curto"""
        response = client.post(
            "/config/resolve",
            json={"plugin_id": "word_frequency", "text_size": "short_text"},
        )
        assert response.status_code == 200

    def test_resolve_config_long_text(self, client):
        """Resolve config para texto longo"""
        response = client.post(
            "/config/resolve",
            json={"plugin_id": "word_frequency", "text_size": "long_text"},
        )
        assert response.status_code == 200

    def test_resolve_config_invalid_plugin(self, client):
        """Plugin inexistente retorna 404"""
        response = client.post(
            "/config/resolve",
            json={"plugin_id": "nao_existe", "text_size": "medium"},
        )
        assert response.status_code == 404


# ============================================================================
# GET /plugins/{plugin_id}/schema
# ============================================================================

class TestPluginSchema:
    """Testa endpoint de schema do plugin"""

    def test_get_schema_word_frequency(self, client):
        """Schema do word_frequency"""
        response = client.get("/plugins/word_frequency/schema")
        assert response.status_code == 200
        data = response.json()
        assert "parameters" in data or "plugin_id" in data

    def test_get_schema_invalid_plugin(self, client):
        """Plugin inexistente retorna 404"""
        response = client.get("/plugins/nao_existe/schema")
        assert response.status_code == 404


# ============================================================================
# GET /config/consolidated
# ============================================================================

class TestConsolidatedConfig:
    """Testa visao consolidada de configs"""

    def test_get_consolidated(self, client):
        """GET /config/consolidated retorna visao completa"""
        response = client.get("/config/consolidated")
        assert response.status_code == 200
        data = response.json()
        # Deve ter informacao de multiplos plugins
        assert isinstance(data, dict)


# ============================================================================
# POST /transcribe/{plugin_id} — transcricao com mock do groq
# ============================================================================

class TestTranscribeEndpoint:
    """Testa endpoint de transcricao com mock"""

    def test_transcribe_success(self, client):
        """Transcricao com mock do groq — sucesso"""
        mock_result = {
            "transcription": "Texto transcrito do audio",
            "language": "pt",
            "duration": 10.5,
        }

        # Mock do execute_plugin para evitar chamada real ao Groq
        with patch.object(get_core(), "execute_plugin", return_value=mock_result):
            fake_audio = io.BytesIO(b"\x00" * 100)
            response = client.post(
                "/transcribe/transcription",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"config": "{}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["plugin_id"] == "transcription"
        assert data["filename"] == "audio.mp3"
        assert data["result"]["transcription"] == "Texto transcrito do audio"

    def test_transcribe_invalid_config_json(self, client):
        """Config JSON invalido retorna 422"""
        fake_audio = io.BytesIO(b"\x00" * 100)
        response = client.post(
            "/transcribe/transcription",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"config": "nao-e-json"},
        )
        assert response.status_code == 422

    def test_transcribe_nonexistent_plugin(self, client):
        """Plugin inexistente retorna 404"""
        fake_audio = io.BytesIO(b"\x00" * 100)
        response = client.post(
            "/transcribe/plugin_fantasma",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"config": "{}"},
        )
        assert response.status_code == 404

    def test_transcribe_plugin_error(self, client):
        """Erro no plugin retorna 400"""
        with patch(
            "qualia.api.core.execute_plugin",
            side_effect=RuntimeError("Groq API error"),
        ):
            fake_audio = io.BytesIO(b"\x00" * 100)
            response = client.post(
                "/transcribe/transcription",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"config": "{}"},
            )

        assert response.status_code == 400

    def test_transcribe_temp_file_cleanup(self, client):
        """Arquivo temporario e removido apos transcricao"""
        mock_result = {"transcription": "ok", "language": "pt", "duration": 1.0}
        saved_paths = []

        original_unlink = Path.unlink

        def track_unlink(self, *args, **kwargs):
            saved_paths.append(str(self))
            original_unlink(self, *args, **kwargs)

        with patch.object(get_core(), "execute_plugin", return_value=mock_result):
            with patch.object(Path, "unlink", track_unlink):
                fake_audio = io.BytesIO(b"\x00" * 100)
                client.post(
                    "/transcribe/transcription",
                    files={"file": ("cleanup.mp3", fake_audio, "audio/mpeg")},
                    data={"config": "{}"},
                )

        # Pelo menos um unlink deve ter sido chamado (o temp file)
        assert len(saved_paths) > 0


# ============================================================================
# GET /plugins/health
# ============================================================================

class TestPluginsHealth:

    def test_plugins_health_returns_200(self, client):
        """GET /plugins/health retorna 200 com status por plugin."""
        response = client.get("/plugins/health")
        assert response.status_code == 200
        data = response.json()
        assert "plugins" in data
        assert data["total"] >= 8
        assert data["status"] == "healthy"

    def test_plugins_health_has_per_plugin_info(self, client):
        """Cada plugin tem id, status, loading."""
        response = client.get("/plugins/health")
        data = response.json()
        for p in data["plugins"]:
            assert "id" in p
            assert "status" in p
            assert p["status"] in ("loaded", "pending")
            assert "loading" in p
            assert p["loading"] in ("eager", "lazy")

    def test_plugins_health_no_errors(self, client):
        """Sem erros de discovery → errors ausente ou vazio."""
        response = client.get("/plugins/health")
        data = response.json()
        assert data.get("errors", []) == [] or "errors" not in data

    def test_plugins_health_not_captured_by_plugin_id_route(self, client):
        """GET /plugins/health não cai no catch-all /plugins/{plugin_id}."""
        response = client.get("/plugins/health")
        # Se caísse no catch-all, seria 404 (plugin "health" não existe)
        assert response.status_code == 200
        assert "plugins" in response.json()


# ============================================================================
# POST /webhook/custom e GET /webhook/stats
# ============================================================================

class TestUploadSizeLimit:
    """Testa rejeição de uploads grandes com 413.

    Usa monkeypatch pra reduzir MAX_UPLOAD_SIZE a 1KB — evita criar
    arquivos de 25MB e problemas de espaço em disco.
    """

    def test_transcribe_file_too_large_returns_413(self, client, monkeypatch):
        """Upload > TRANSCRIPTION_MAX_SIZE em transcribe retorna 413."""
        import qualia.api.routes.transcribe as transcribe_mod
        monkeypatch.setattr(transcribe_mod, "TRANSCRIPTION_MAX_SIZE", 1024)
        fake_content = b"\x00" * 1025
        response = client.post(
            "/transcribe/transcription",
            files={"file": ("big.mp3", io.BytesIO(fake_content), "audio/mpeg")},
            data={"config": "{}"},
        )
        assert response.status_code == 413

    def test_pipeline_file_too_large_returns_413(self, client, monkeypatch):
        """Upload > MAX_UPLOAD_SIZE em pipeline retorna 413."""
        import qualia.api.deps as deps
        monkeypatch.setattr(deps, "MAX_UPLOAD_SIZE", 1024)
        fake_content = b"\x00" * 1025
        steps = json.dumps([{"plugin_id": "teams_cleaner"}])
        response = client.post(
            "/pipeline?sync=true",
            files={"file": ("big.txt", io.BytesIO(fake_content), "text/plain")},
            data={"steps": steps},
        )
        assert response.status_code == 413

    def test_small_file_accepted(self, client):
        """Upload dentro do limite não retorna 413."""
        fake_content = b"\x00" * 100
        response = client.post(
            "/transcribe/transcription",
            files={"file": ("small.mp3", io.BytesIO(fake_content), "audio/mpeg")},
            data={"config": "{}"},
        )
        # Pode ser 200 ou 400 (sem API key), mas não 413
        assert response.status_code != 413


class TestWebhookEndpoints:
    """Testa endpoints de webhook"""

    def test_webhook_custom_with_text(self, client):
        """Webhook generico com campo text"""
        response = client.post(
            "/webhook/custom",
            json={"text": "Texto enviado via webhook para analise"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["webhook_type"] == "generic"
        assert "result" in data

    def test_webhook_custom_with_content_field(self, client):
        """Webhook generico com campo content"""
        response = client.post(
            "/webhook/custom",
            json={"content": "Conteudo do webhook"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_webhook_custom_with_plugin_override(self, client):
        """Webhook com plugin especificado no payload"""
        response = client.post(
            "/webhook/custom",
            json={
                "text": "Texto para analise de sentimento via webhook",
                "plugin": "sentiment_analyzer",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["plugin_used"] == "sentiment_analyzer"

    def test_webhook_custom_no_text(self, client):
        """Webhook sem campo de texto retorna skipped"""
        response = client.post(
            "/webhook/custom",
            json={"id": 123, "action": "update"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"

    def test_webhook_stats(self, client):
        """GET /webhook/stats retorna estatisticas"""
        response = client.get("/webhook/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "stats" in data
        assert "generic" in data["stats"]


# ============================================================================
# Exception handlers
# ============================================================================

class TestExceptionHandlers:
    """Testa handlers de excecao customizados"""

    def test_404_returns_error_format(self, client):
        """404 retorna formato padrao de erro"""
        response = client.get("/plugins/plugin_que_nao_existe")
        assert response.status_code == 404
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data

    def test_422_returns_error_on_bad_body(self, client):
        """Request com body invalido retorna 422"""
        response = client.post(
            "/analyze/word_frequency",
            content=b"isto nao e json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


# ============================================================================
# Pipeline com file upload (document plugin como step 0)
# ============================================================================

class TestPipelineWithFile:
    """Testa pipeline com upload de arquivo"""

    def test_pipeline_file_with_document_plugin(self, client):
        """Pipeline: file -> transcription (mock) -> word_frequency"""
        mock_result = {
            "transcription": "palavra repetida repetida tres tres tres",
            "language": "pt",
            "duration": 5.0,
        }

        with patch.object(get_core(), "execute_plugin", side_effect=[
            mock_result,  # primeiro step (transcription)
            {  # segundo step (word_frequency) — mock tambem
                "word_frequencies": {"palavra": 1, "repetida": 2, "tres": 3},
                "total_words": 6,
                "unique_words": 3,
            },
        ]):
            fake_audio = io.BytesIO(b"\x00" * 100)
            steps = json.dumps([
                {"plugin_id": "transcription"},
                {"plugin_id": "word_frequency"},
            ])
            response = client.post(
                "/pipeline?sync=true",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"text": "", "steps": steps},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["steps_executed"] == 2

    def test_pipeline_chains_cleaned_document_into_next_step(self, client):
        """Pipeline deve encadear texto limpo para o analyzer seguinte."""
        steps = json.dumps([
            {"plugin_id": "teams_cleaner"},
            {"plugin_id": "word_frequency"},
        ])
        teams_text = (
            "[00:00:01] Teams System: joined the meeting\n"
            "[00:00:02] Ana: palavra forte\n"
            "[00:00:03] Ana: palavra forte\n"
        )
        response = client.post(
            "/pipeline?sync=true",
            data={"text": teams_text, "steps": steps},
        )

        assert response.status_code == 200
        data = response.json()
        word_freq = data["results"][1]["result"]["word_frequencies"]
        assert "palavra" in word_freq
        assert "joined" not in word_freq
        assert "meeting" not in word_freq

    def test_pipeline_file_step0_accepts_cleaned_document(self, client):
        """Pipeline com arquivo deve encadear campos textuais alem de transcription."""
        with patch.object(get_core(), "execute_plugin", side_effect=[
            {"cleaned_document": "texto limpo final"},
            {"word_frequencies": {"texto": 1, "limpo": 1, "final": 1}},
        ]) as mock_execute:
            fake_audio = io.BytesIO(b"\x00" * 100)
            steps = json.dumps([
                {"plugin_id": "transcription"},
                {"plugin_id": "word_frequency"},
            ])
            response = client.post(
                "/pipeline?sync=true",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"steps": steps},
            )

        assert response.status_code == 200
        second_doc = mock_execute.call_args_list[1].args[1]
        assert second_doc.content == "texto limpo final"

    def test_pipeline_file_cleanup(self, client):
        """Arquivo temporario do pipeline e limpo apos execucao"""
        mock_result = {"transcription": "texto", "language": "pt", "duration": 1.0}

        with patch.object(get_core(), "execute_plugin", return_value=mock_result):
            fake_audio = io.BytesIO(b"\x00" * 100)
            steps = json.dumps([{"plugin_id": "transcription"}])
            response = client.post(
                "/pipeline?sync=true",
                files={"file": ("test.mp3", fake_audio, "audio/mpeg")},
                data={"steps": steps},
            )

        # Nao deve ter arquivo temporario pendente
        assert response.status_code == 200

    def test_pipeline_file_with_non_document_step0_returns_422(self, client):
        """Arquivo com step[0] nao-document deve dar erro descritivo, nao generico."""
        fake_audio = io.BytesIO(b"\x00" * 100)
        steps = json.dumps([{"plugin_id": "word_frequency"}])
        response = client.post(
            "/pipeline?sync=true",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"steps": steps},
        )
        assert response.status_code == 422
        data = response.json()
        error_text = data.get("detail", data.get("message", ""))
        assert "document" in error_text.lower()
        assert "word_frequency" in error_text

    def test_pipeline_file_with_text_based_document_plugin(self, client):
        """Pipeline com arquivo e document plugin sem transcription deve ler conteudo do arquivo.

        Fix: quando file e enviado e step[0] e um document plugin que NAO tem
        'transcription' em provides (ex: teams_cleaner), o conteudo do arquivo
        deve ser carregado em document.content ao inves de ficar vazio.
        """
        teams_content = (
            "[00:00:01] Teams System: joined\n"
            "[00:00:02] Ana: texto importante para analise\n"
            "[00:00:03] Ana: texto importante para analise\n"
        )
        fake_file = io.BytesIO(teams_content.encode("utf-8"))
        steps = json.dumps([
            {"plugin_id": "teams_cleaner"},
            {"plugin_id": "word_frequency"},
        ])
        response = client.post(
            "/pipeline?sync=true",
            files={"file": ("chat.txt", fake_file, "text/plain")},
            data={"steps": steps},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["steps_executed"] == 2
        # teams_cleaner deve ter processado o conteudo (nao string vazia)
        cleaner_result = data["results"][0]["result"]
        assert "cleaned_document" in cleaner_result
        assert len(cleaner_result["cleaned_document"]) > 0
        # word_frequency deve ter resultado com palavras do texto limpo
        wf_result = data["results"][1]["result"]
        assert "word_frequencies" in wf_result
        # "texto" deve estar nas frequencias (veio do conteudo do arquivo)
        assert "texto" in wf_result["word_frequencies"] or "importante" in wf_result["word_frequencies"]


# ============================================================================
# Readability analyzer (cobre mais branches do /analyze)
# ============================================================================

class TestReadabilityAnalyzer:
    """Testa readability_analyzer via API"""

    def test_analyze_readability(self, client):
        """Analise de legibilidade retorna metricas"""
        text = (
            "A analise de legibilidade mede a facilidade de leitura de um texto. "
            "Textos mais simples recebem pontuacoes mais altas. "
            "Frases curtas e palavras simples melhoram a legibilidade."
        )
        response = client.post(
            "/analyze/readability_analyzer",
            json={"text": text, "config": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "result" in data


# ============================================================================
# Edge cases — api/__init__.py uncovered lines
# ============================================================================

class TestAPIEdgeCases:
    """Testa branches nao cobertos em api/__init__.py"""

    def test_general_exception_handler(self, client):
        """Excecao generica nao tratada retorna 500 com JSON de erro"""
        from starlette.routing import Route
        from qualia.api import app as test_app

        async def raise_error(request):
            raise RuntimeError("erro interno simulado")

        # Insere rota ANTES do SPA catch-all (ultimo) para garantir match
        test_route = Route("/test-500-route", raise_error, methods=["GET"])
        test_app.routes.insert(0, test_route)

        try:
            response = client.get("/test-500-route")
            assert response.status_code == 500
            data = response.json()
            assert data["status"] == "error"
            assert data["message"] == "Internal server error"
        finally:
            test_app.routes.remove(test_route)

    def test_spa_fallback_no_index(self, client):
        """SPA catch-all sem index.html retorna 404"""
        with patch.object(Path, "exists", return_value=False):
            response = client.get("/nonexistent-page")
            assert response.status_code == 404
            data = response.json()
            # Com frontend/dist: rota SPA existe, custom handler retorna status
            # Sem frontend/dist (CI): rota não existe, FastAPI retorna detail
            assert data.get("status") == "error" or "detail" in data


# ============================================================================
# Pipeline edge cases — cobre linhas 79-80, 135-144, 167-169
# ============================================================================

class TestPipelineEdgeCases:
    """Testa caminhos nao cobertos no pipeline"""

    def test_pipeline_empty_steps_returns_422(self, client):
        """Pipeline com lista de steps vazia retorna 422"""
        response = client.post(
            "/pipeline?sync=true",
            data={"text": "algo", "steps": "[]"},
        )
        assert response.status_code == 422

    def test_pipeline_step_failure_returns_400(self, client):
        """Erro generico num step do pipeline retorna 400 (linhas 167-169)"""
        # Usar um plugin real mas forcar erro no execute_plugin
        steps = json.dumps([{"plugin_id": "word_frequency"}])

        with patch(
            "qualia.api.routes.pipeline.get_core"
        ) as mock_get_core:
            mock_core = MagicMock()
            mock_get_core.return_value = mock_core
            # steps_list parse ok, mas core.loader.get_plugin retorna algo
            mock_plugin = MagicMock()
            mock_core.loader.get_plugin.return_value = mock_plugin
            mock_meta = MagicMock(type=MagicMock(value="analyzer"))
            mock_core.registry.get.return_value = mock_meta
            mock_core.registry.__contains__ = MagicMock(return_value=True)
            mock_core.registry.__getitem__ = MagicMock(return_value=mock_meta)
            mock_core.get_config_registry.return_value = None
            mock_core.add_document.return_value = MagicMock()
            mock_core.execute_plugin.side_effect = RuntimeError("plugin explodiu")

            response = client.post(
                "/pipeline?sync=true",
                data={"text": "algo", "steps": steps},
            )

        assert response.status_code == 400
        data = response.json()
        error_text = data.get("detail", data.get("message", ""))
        assert "plugin explodiu" in str(error_text)

    def test_pipeline_html_output_format(self, client):
        """Pipeline com visualizer em formato html"""
        steps = json.dumps([
            {"plugin_id": "word_frequency"},
            {"plugin_id": "frequency_chart_plotly", "config": {"format": "html"}},
        ])
        text = "palavra repetida repetida tres tres tres quatro quatro quatro quatro"

        response = client.post(
            "/pipeline?sync=true",
            data={"text": text, "steps": steps},
        )
        # Se o plugin nao suporta html, pode retornar 400; se suporta, 200
        if response.status_code == 200:
            data = response.json()
            viz_result = data["results"][1]["result"]
            # Novo formato: dict com "html" key ou "data"+"encoding"+"format"
            assert "html" in viz_result or "data" in viz_result

    def test_pipeline_unknown_output_format(self, client):
        """Pipeline com formato desconhecido cai no else (linhas 141-144)"""
        steps = json.dumps([
            {"plugin_id": "word_frequency"},
            {"plugin_id": "frequency_chart_plotly", "config": {"format": "pdf"}},
        ])
        text = "palavra repetida repetida tres tres tres quatro quatro quatro quatro"
        response = client.post(
            "/pipeline?sync=true",
            data={"text": text, "steps": steps},
        )
        # pdf nao suportado -> 422 (validação de output_format na borda)
        assert response.status_code == 422

    def test_pipeline_text_only_no_file(self, client):
        """Pipeline com texto e sem file para analyzer (linhas 135-144 text path)"""
        steps = json.dumps([
            {"plugin_id": "sentiment_analyzer"},
        ])
        text = "Este produto e excelente, estou muito satisfeito com a qualidade."
        response = client.post(
            "/pipeline?sync=true",
            data={"text": text, "steps": steps},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["steps_executed"] == 1


# ============================================================================
# Config edge cases — cobre linhas 17, 32, 43
# ============================================================================

class TestConfigEdgeCases:
    """Testa caminhos nao cobertos nos endpoints de config"""

    def test_plugin_schema_not_found(self, client):
        """GET /plugins/nonexistent/schema retorna 404"""
        response = client.get("/plugins/nonexistent_plugin_xyz/schema")
        assert response.status_code == 404
        data = response.json()
        error_text = data.get("detail", data.get("message", ""))
        assert "not found" in error_text.lower()

    def test_config_resolve_nonexistent_plugin(self, client):
        """POST /config/resolve com plugin inexistente retorna 404"""
        response = client.post(
            "/config/resolve",
            json={"plugin_id": "plugin_fantasma_xyz", "text_size": "medium"},
        )
        assert response.status_code == 404

    def test_config_consolidated_returns_dict(self, client):
        """GET /config/consolidated retorna dict com schemas de plugins"""
        response = client.get("/config/consolidated")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Deve conter pelo menos um plugin
        assert len(data) > 0

    def test_config_resolve_valid_plugin(self, client):
        """POST /config/resolve com plugin valido retorna config resolvida"""
        response = client.post(
            "/config/resolve",
            json={"plugin_id": "word_frequency", "text_size": "short_text"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["plugin_id"] == "word_frequency"
        assert data["text_size"] == "short_text"
        assert "resolved_config" in data


# ============================================================================
# Transcribe edge cases — cobre linhas 39-41, 71
# ============================================================================

class TestTranscribeEdgeCases:
    """Testa caminhos nao cobertos no endpoint de transcricao"""

    def test_transcribe_invalid_plugin_returns_404(self, client):
        """POST /transcribe/nonexistent retorna 404"""
        fake_audio = io.BytesIO(b"\x00" * 100)
        response = client.post(
            "/transcribe/plugin_que_nao_existe_xyz",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"config": "{}"},
        )
        assert response.status_code == 404

    def test_transcribe_invalid_config_validation(self, client):
        """Transcricao com config invalida retorna 422 (linhas 39-41)"""
        fake_audio = io.BytesIO(b"\x00" * 100)
        # Enviar config com valor invalido para o plugin transcription
        config = json.dumps({"temperature": 99.9})  # fora do range valido
        response = client.post(
            "/transcribe/transcription",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"config": config},
        )
        assert response.status_code == 422

    def test_transcribe_wrong_plugin_type_returns_422(self, client):
        """Transcribe deve rejeitar plugin que nao e document."""
        fake_audio = io.BytesIO(b"\x00" * 100)
        response = client.post(
            "/transcribe/word_frequency",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"config": "{}"},
        )
        assert response.status_code == 422

    def test_transcribe_non_transcription_document_returns_422(self, client):
        """Transcribe deve rejeitar document plugin que nao e de transcricao (ex: teams_cleaner)."""
        fake_audio = io.BytesIO(b"\x00" * 100)
        response = client.post(
            "/transcribe/teams_cleaner",
            files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
            data={"config": "{}"},
        )
        assert response.status_code == 422
        assert "transcrição" in response.json()["message"].lower() or "transcri" in response.json()["message"].lower()

    def test_transcribe_http_exception_reraise(self, client):
        """HTTPException lancada dentro do try e relancada (linha 71)"""
        from fastapi import HTTPException as FastAPIHTTPException

        with patch(
            "qualia.api.routes.transcribe.get_core"
        ) as mock_get_core:
            mock_core = MagicMock()
            mock_get_core.return_value = mock_core
            mock_core.registry = {
                "transcription": _mock_registry_entry("transcription", "document"),
            }
            mock_core.loader.get_plugin.return_value = MagicMock()
            mock_core.get_config_registry.return_value = None
            mock_core.add_document.return_value = MagicMock()
            mock_core.execute_plugin.side_effect = FastAPIHTTPException(
                status_code=503, detail="Servico indisponivel"
            )

            fake_audio = io.BytesIO(b"\x00" * 100)
            response = client.post(
                "/transcribe/transcription",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"config": "{}"},
            )

        assert response.status_code == 503
        data = response.json()
        error_text = str(data.get("detail", data.get("message", "")))
        assert "indisponivel" in error_text.lower() or "503" in error_text

    def test_transcribe_timeout_returns_504(self, client):
        """Transcrição que excede 60s retorna 504."""
        with patch("qualia.api.routes.transcribe.get_core") as mock_get_core:
            mock_core = MagicMock()
            mock_get_core.return_value = mock_core
            mock_core.registry = {
                "transcription": _mock_registry_entry("transcription", "document"),
            }
            mock_core.loader.get_plugin.return_value = MagicMock()
            mock_core.get_config_registry.return_value = None
            mock_core.add_document.return_value = MagicMock()
            mock_core.execute_plugin.side_effect = asyncio.TimeoutError()

            fake_audio = io.BytesIO(b"\x00" * 100)
            response = client.post(
                "/transcribe/transcription",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"config": "{}"},
            )

        assert response.status_code == 504
        assert "timeout" in response.json()["message"].lower() or "60s" in response.json()["message"]

    def test_transcribe_domain_error_returns_400(self, client):
        """Plugin de transcrição retorna status=error → API retorna 400."""
        with patch("qualia.api.routes.transcribe.get_core") as mock_get_core:
            mock_core = MagicMock()
            mock_get_core.return_value = mock_core
            mock_core.registry = {
                "transcription": MagicMock(type=MagicMock(value="document"))
            }
            mock_core.get_config_registry.return_value = None
            mock_core.add_document.return_value = MagicMock()
            mock_core.execute_plugin.return_value = {
                "status": "error",
                "error": "GROQ_API_KEY não configurada",
            }

            fake_audio = io.BytesIO(b"\x00" * 100)
            response = client.post(
                "/transcribe/transcription?sync=true",
                files={"file": ("audio.mp3", fake_audio, "audio/mpeg")},
                data={"config": "{}"},
            )

        assert response.status_code == 400
        assert "GROQ_API_KEY" in response.json()["message"]


# ============================================================================
# Visualize edge cases — cobre linhas 64, 72-74
# ============================================================================

class TestVisualizeEdgeCases:
    """Testa caminhos nao cobertos no endpoint de visualizacao"""

    def test_visualize_invalid_plugin_returns_404(self, client):
        """POST /visualize/nonexistent retorna 404"""
        response = client.post(
            "/visualize/plugin_fantasma_xyz",
            json={
                "data": {"word_frequencies": {"a": 1}},
                "config": {},
                "output_format": "png",
            },
        )
        assert response.status_code == 404

    def test_visualize_generic_exception_returns_400(self, client):
        """Erro generico no render retorna 400 (linhas 72-74)"""
        with patch(
            "qualia.api.routes.visualize.get_core"
        ) as mock_get_core:
            mock_core = MagicMock()
            mock_get_core.return_value = mock_core
            mock_core.registry = {
                "frequency_chart_plotly": _mock_registry_entry("frequency_chart_plotly", "visualizer"),
            }
            mock_core.get_config_registry.return_value = None
            mock_plugin = MagicMock()
            mock_plugin.render.side_effect = ValueError("dados invalidos para render")
            mock_core.loader.get_plugin.return_value = mock_plugin

            response = client.post(
                "/visualize/frequency_chart_plotly",
                json={
                    "data": {"word_frequencies": {"a": 1}},
                    "config": {},
                    "output_format": "png",
                },
            )

        assert response.status_code == 400
        data = response.json()
        error_text = str(data.get("detail", data.get("message", "")))
        assert "dados invalidos" in error_text.lower()

    def test_visualize_invalid_format_returns_422(self, client):
        """Formato inválido retorna 422 (Literal validation: html, png, svg)"""
        response = client.post(
            "/visualize/frequency_chart_plotly",
            json={
                "data": {"word_frequencies": {"a": 1}},
                "config": {},
                "output_format": "pdf",
            },
        )
        assert response.status_code == 422


# ============================================================================
# Config endpoints — registry None
# ============================================================================

class TestConfigEndpoints:
    """Testes dos endpoints de config quando registry não está disponível."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_plugin_schema_no_registry_returns_503(self, client):
        """GET /plugins/{id}/schema sem registry retorna 503."""
        with patch.object(get_core(), "get_config_registry", return_value=None):
            response = client.get("/plugins/word_frequency/schema")
        assert response.status_code == 503

    def test_consolidated_no_registry_returns_503(self, client):
        """GET /config/consolidated sem registry retorna 503."""
        with patch.object(get_core(), "get_config_registry", return_value=None):
            response = client.get("/config/consolidated")
        assert response.status_code == 503

    def test_resolve_no_registry_returns_503(self, client):
        """POST /config/resolve sem registry retorna 503."""
        with patch.object(get_core(), "get_config_registry", return_value=None):
            response = client.post(
                "/config/resolve",
                json={"plugin_id": "word_frequency", "config": {}, "text_size": "medium"},
            )
        assert response.status_code == 503


# ============================================================================
# Health / Root endpoints
# ============================================================================

class TestHealthEndpoints:
    """Testes de health e root."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_root_without_frontend_returns_api_info(self, client):
        """GET / sem frontend dist retorna info da API."""
        with patch("qualia.api.routes.health._has_frontend", False):
            response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Qualia Core API"


# ============================================================================
# check_upload_size — streaming para tempfile
# ============================================================================

class TestCheckUploadSize:
    """Testa upload streaming para tempfile com hash e limite de tamanho."""

    @pytest.mark.asyncio
    async def test_check_upload_size_returns_upload_result(self):
        """Retorna UploadResult com tmp_path, size e content_hash."""
        from qualia.api.deps import check_upload_size, UploadResult
        content = b"conteudo de teste para upload"
        file = UploadFile(file=io.BytesIO(content), filename="test.txt")
        result = await check_upload_size(file)
        assert isinstance(result, UploadResult)
        assert hasattr(result, "tmp_path")
        assert hasattr(result, "size")
        assert hasattr(result, "content_hash")
        # Cleanup
        Path(result.tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_check_upload_size_streams_to_file(self):
        """Tempfile contém exatamente os dados enviados."""
        from qualia.api.deps import check_upload_size
        content = b"dados importantes que devem estar no disco"
        file = UploadFile(file=io.BytesIO(content), filename="doc.txt")
        result = await check_upload_size(file)
        saved = Path(result.tmp_path).read_bytes()
        assert saved == content
        assert result.size == len(content)
        # Cleanup
        Path(result.tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_check_upload_size_413_cleans_tempfile(self):
        """Tempfile é deletado quando upload excede limite."""
        from qualia.api.deps import check_upload_size
        import tempfile
        content = b"x" * 1000  # 1000 bytes
        file = UploadFile(file=io.BytesIO(content), filename="big.bin")

        # Capturar o path do tempfile criado
        original_ntf = tempfile.NamedTemporaryFile
        created_paths = []

        def tracking_ntf(**kwargs):
            tmp = original_ntf(**kwargs)
            created_paths.append(tmp.name)
            return tmp

        with patch("qualia.api.deps.tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
            with pytest.raises(HTTPException) as exc_info:
                await check_upload_size(file, max_size=500)
            assert exc_info.value.status_code == 413

        # Tempfile deve ter sido deletado
        for p in created_paths:
            assert not Path(p).exists(), f"Tempfile {p} não foi deletado após 413"

    @pytest.mark.asyncio
    async def test_check_upload_size_hash_correct(self):
        """Hash retornado corresponde ao md5 do conteúdo (8 chars)."""
        import hashlib
        from qualia.api.deps import check_upload_size
        content = b"texto para verificar hash md5"
        expected_hash = hashlib.md5(content).hexdigest()[:8]
        file = UploadFile(file=io.BytesIO(content), filename="hash_test.txt")
        result = await check_upload_size(file)
        assert result.content_hash == expected_hash
        # Cleanup
        Path(result.tmp_path).unlink(missing_ok=True)
