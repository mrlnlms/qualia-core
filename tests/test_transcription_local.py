# tests/test_transcription_local.py
"""
Testes para o plugin de transcrição local via whisper.cpp.

Todos os testes são mockados — não requerem pywhispercpp instalado.
"""

from pathlib import Path

import pytest

from qualia.core import PluginType


@pytest.fixture
def plugin():
    from plugins.documents.transcription_local import TranscriptionLocalPlugin
    return TranscriptionLocalPlugin()


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
