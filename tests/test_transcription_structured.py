"""Plugin estruturado: validação e contrato sem inferência."""
from unittest.mock import patch

import pytest

from qualia.core import Document
from plugins.documents.transcription_structured import TranscriptionStructuredPlugin


def test_contract_and_automatic_speakers(tmp_path):
    plugin = TranscriptionStructuredPlugin()
    audio = tmp_path / 'sample.wav'
    audio.touch()
    doc = Document(id='test', content='', metadata={'file_path': str(audio)})
    expected = {key: {} for key in plugin.meta().provides}
    with patch('plugins.documents.transcription_structured.run_structured', return_value=expected) as worker:
        assert plugin.process(doc, {}, {}) == expected
    assert worker.call_args.kwargs == {'language': 'pt', 'device': 'mps', 'speech_boundaries': False, 'recover_speakers': False}
    assert plugin.meta().heavy is True
    assert 'num_speakers' not in plugin.meta().parameters


@pytest.mark.parametrize('config', [{'language': 'auto'}, {'device': 'cuda'}, {'num_speakers': 2}, {'model': 'tiny'}])
def test_reject_unsupported_config_before_worker(config):
    plugin = TranscriptionStructuredPlugin()
    with patch('plugins.documents.transcription_structured.run_structured') as worker:
        with pytest.raises(ValueError):
            plugin.process(Document(id='x', content=''), config, {})
        worker.assert_not_called()


def test_missing_upload():
    with pytest.raises(ValueError, match='arquivo'):
        TranscriptionStructuredPlugin().process(Document(id='x', content=''), {}, {})


def test_discovery_of_both_local_plugins_without_loading_models(tmp_path):
    from pathlib import Path
    import shutil
    from qualia.core import QualiaCore
    repo = Path(__file__).resolve().parents[1]
    folder = tmp_path / 'plugins'
    folder.mkdir()
    for name in ('transcription_local', 'transcription_structured'):
        (folder / name).mkdir()
        shutil.copyfile(repo / 'plugins/documents' / name / '__init__.py', folder / name / '__init__.py')
    core = QualiaCore(plugins_dir=folder, cache_dir=tmp_path / 'cache')
    assert set(core.registry) == {'transcription_local', 'transcription_structured'}
    assert not core.loader.loaded_plugins  # Ambos lazy, sem recursos nativos no startup.
