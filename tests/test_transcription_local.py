# tests/test_transcription_local.py
"""
Testes para o plugin de transcrição local via whisper.cpp.

Todos os testes são mockados — não requerem pywhispercpp instalado.
"""

import tempfile
from pathlib import Path

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
