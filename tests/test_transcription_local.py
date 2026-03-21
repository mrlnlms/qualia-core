# tests/test_transcription_local.py
"""
Testes para o plugin de transcrição local via whisper.cpp.

Todos os testes são mockados — não requerem pywhispercpp instalado.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from qualia.core import PluginType


@pytest.fixture
def plugin():
    from plugins.documents.transcription_local import TranscriptionLocalPlugin
    return TranscriptionLocalPlugin()


@pytest.fixture
def temp_audio():
    """Cria arquivo temporário simulando um áudio."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"\x00" * 1024)  # 1KB fake audio
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def doc_with_file(temp_audio):
    """Document com file_path no metadata."""
    from qualia.core import Document
    doc = Document(id="test_audio", content="")
    doc.metadata["file_path"] = temp_audio
    return doc


class TestMeta:
    def test_meta_id(self, plugin):
        assert plugin.meta().id == "transcription_local"

    def test_meta_type(self, plugin):
        assert plugin.meta().type == PluginType.DOCUMENT

    def test_meta_provides(self, plugin):
        provides = plugin.meta().provides
        assert "transcription" in provides
        assert "detected_language" in provides
        assert "duration" in provides

    def test_meta_version(self, plugin):
        assert plugin.meta().version == "0.1.0"

    def test_meta_no_requires(self, plugin):
        assert plugin.meta().requires == []

    def test_meta_parameters_model(self, plugin):
        params = plugin.meta().parameters
        assert "model" in params
        model = params["model"]
        assert model["default"] == "large-v3"
        assert "tiny" in model["options"]
        assert "large-v3" in model["options"]

    def test_meta_parameters_language(self, plugin):
        params = plugin.meta().parameters
        assert "language" in params
        lang = params["language"]
        assert lang["default"] == "auto"
        assert "pt" in lang["options"]

    def test_meta_parameters_include_timestamps(self, plugin):
        params = plugin.meta().parameters
        assert "include_timestamps" in params
        ts = params["include_timestamps"]
        assert ts["default"] is False
        assert ts["type"] == "bool"


# ============================================================================
# Validações de entrada
# ============================================================================

class TestValidation:
    def test_no_file_path(self, plugin):
        """Sem file_path no metadata → ValueError."""
        from qualia.core import Document
        doc = Document(id="no_file", content="")
        with pytest.raises(ValueError, match="arquivo"):
            plugin._process_impl(doc, {}, {})

    def test_file_not_found(self, plugin):
        """Arquivo não existe → ValueError."""
        from qualia.core import Document
        doc = Document(id="missing", content="")
        doc.metadata["file_path"] = "/tmp/inexistente_abc123.mp3"
        with pytest.raises(ValueError, match="não encontrado"):
            plugin._process_impl(doc, {}, {})

    def test_pywhispercpp_not_installed(self, plugin, doc_with_file):
        """pywhispercpp não instalado → ValueError."""
        import plugins.documents.transcription_local as mod
        original = mod.HAS_PYWHISPERCPP
        try:
            mod.HAS_PYWHISPERCPP = False
            with pytest.raises(ValueError, match="pywhispercpp|transcription-local"):
                plugin._process_impl(doc_with_file, {}, {})
        finally:
            mod.HAS_PYWHISPERCPP = original


# ============================================================================
# Transcrição com sucesso (mockada)
# ============================================================================

class TestTranscription:
    """Testes com pywhispercpp mockado."""

    @pytest.fixture(autouse=True)
    def _enable_pywhispercpp(self):
        """Habilita HAS_PYWHISPERCPP para todos os testes desta classe."""
        import plugins.documents.transcription_local as mod
        original = mod.HAS_PYWHISPERCPP
        mod.HAS_PYWHISPERCPP = True
        yield
        mod.HAS_PYWHISPERCPP = original

    def _make_mock_model(self, segments):
        """Cria mock do WhisperModel que retorna segmentos configurados."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = segments
        return mock_model

    def _make_segment(self, t0, t1, text):
        """Cria mock de um segmento whisper.cpp.

        t0 e t1 são centésimos de segundo (ex: 0, 1500 = 0s a 15s).
        """
        seg = MagicMock()
        seg.t0 = t0
        seg.t1 = t1
        seg.text = text
        return seg

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_successful_transcription(self, mock_model_cls, plugin, doc_with_file):
        """Transcrição com sucesso retorna texto e metadados."""
        segments = [
            self._make_segment(0, 500, " Olá, isto é um teste."),
            self._make_segment(500, 1000, " Segunda frase aqui."),
        ]
        mock_model = self._make_mock_model(segments)
        mock_model_cls.return_value = mock_model

        result = plugin._process_impl(doc_with_file, {
            "model": "large-v3",
            "language": "pt",
            "include_timestamps": False,
        }, {})

        assert result["status"] == "completed"
        assert "Olá" in result["transcription"]
        assert "Segunda frase" in result["transcription"]
        assert result["error"] is None
        assert "duration" in result

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_transcription_with_timestamps(self, mock_model_cls, plugin, doc_with_file):
        """include_timestamps=True adiciona marcadores de tempo."""
        segments = [
            self._make_segment(0, 1500, " Primeiro segmento."),
            self._make_segment(1500, 8300, " Segundo segmento."),
        ]
        mock_model = self._make_mock_model(segments)
        mock_model_cls.return_value = mock_model

        result = plugin._process_impl(doc_with_file, {
            "model": "tiny",
            "language": "auto",
            "include_timestamps": True,
        }, {})

        assert "[00:00:00]" in result["transcription"]
        assert "[00:00:15]" in result["transcription"]
        assert "Primeiro segmento" in result["transcription"]

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_auto_language_omits_param(self, mock_model_cls, plugin, doc_with_file):
        """language=auto não passa language para o modelo."""
        mock_model = self._make_mock_model([])
        mock_model_cls.return_value = mock_model

        plugin._process_impl(doc_with_file, {
            "model": "tiny",
            "language": "auto",
            "include_timestamps": False,
        }, {})

        call_kwargs = mock_model.transcribe.call_args
        assert "language" not in (call_kwargs.kwargs if call_kwargs.kwargs else {})

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_specific_language_passed(self, mock_model_cls, plugin, doc_with_file):
        """language=pt é passado para o modelo."""
        mock_model = self._make_mock_model([])
        mock_model_cls.return_value = mock_model

        plugin._process_impl(doc_with_file, {
            "model": "tiny",
            "language": "pt",
            "include_timestamps": False,
        }, {})

        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs.kwargs.get("language") == "pt"

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_model_cached_between_calls(self, mock_model_cls, plugin, doc_with_file):
        """Modelo é carregado uma vez e cacheado."""
        mock_model = self._make_mock_model([])
        mock_model_cls.return_value = mock_model

        plugin._process_impl(doc_with_file, {
            "model": "tiny",
            "language": "auto",
            "include_timestamps": False,
        }, {})
        plugin._process_impl(doc_with_file, {
            "model": "tiny",
            "language": "auto",
            "include_timestamps": False,
        }, {})

        assert mock_model_cls.call_count == 1

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_model_reloaded_on_change(self, mock_model_cls, plugin, doc_with_file):
        """Trocar modelo força reload."""
        mock_model = self._make_mock_model([])
        mock_model_cls.return_value = mock_model

        plugin._process_impl(doc_with_file, {
            "model": "tiny",
            "language": "auto",
            "include_timestamps": False,
        }, {})
        plugin._process_impl(doc_with_file, {
            "model": "base",
            "language": "auto",
            "include_timestamps": False,
        }, {})

        assert mock_model_cls.call_count == 2

    @patch("plugins.documents.transcription_local.WhisperModel")
    def test_transcription_error(self, mock_model_cls, plugin, doc_with_file):
        """Erro no whisper.cpp → RuntimeError."""
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("Failed to decode audio")
        mock_model_cls.return_value = mock_model

        with pytest.raises(RuntimeError, match="Failed to decode"):
            plugin._process_impl(doc_with_file, {
                "model": "tiny",
                "language": "auto",
                "include_timestamps": False,
            }, {})


# ============================================================================
# Validação de config (herdada do BaseDocumentPlugin)
# ============================================================================

class TestConfigValidation:
    def test_valid_config(self, plugin):
        ok, err = plugin.validate_config({
            "model": "tiny",
            "language": "pt",
            "include_timestamps": True,
        })
        assert ok is True
        assert err is None

    def test_unknown_param_rejected(self, plugin):
        ok, err = plugin.validate_config({"unknown_param": "value"})
        assert ok is False
        assert "desconhecido" in err

    def test_empty_config_uses_defaults(self, plugin):
        ok, err = plugin.validate_config({})
        assert ok is True


# ============================================================================
# Integração com o Core
# ============================================================================

class TestCoreIntegration:
    def test_plugin_discovered_by_core(self):
        """Plugin é descoberto pelo QualiaCore."""
        from qualia.core import QualiaCore
        core = QualiaCore()
        core.discover_plugins()
        assert "transcription_local" in core.registry

    def test_registry_has_schema(self):
        """ConfigurationRegistry normaliza o schema do plugin."""
        from qualia.core import QualiaCore
        core = QualiaCore()
        core.discover_plugins()
        registry = core.get_config_registry()
        schema = registry.get_plugin_schema("transcription_local")
        assert schema is not None
        assert "model" in schema["parameters"]
        assert "language" in schema["parameters"]
        assert "include_timestamps" in schema["parameters"]

    def test_same_provides_as_groq(self):
        """Mesmo contrato de provides que o plugin Groq."""
        from plugins.documents.transcription import TranscriptionPlugin
        groq_provides = set(TranscriptionPlugin().meta().provides)
        from plugins.documents.transcription_local import TranscriptionLocalPlugin
        local_provides = set(TranscriptionLocalPlugin().meta().provides)
        assert groq_provides == local_provides
