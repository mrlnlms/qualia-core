"""Contrato do adaptador; workers são substituídos, sem carregar modelos."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qualia.transcription import service


def write_result(out):
    data = {
        'result.json': {'status': 'completed', 'validation': {'status': 'passed'},
                        'quality_audit': {'internal_repetitions': [], 'repeated_segment_runs': []}},
        'transcript.transcription.json': {'audio_duration_seconds': 42.5},
        'transcript.rows.json': [{'speaker': 'Participant 3', 'start': None, 'end': None, 'text': 'Olá'}],
        'transcript.assigned-words.json': [{'speaker': 'Participant 3', 'word': 'Olá', 'start': None}],
        'transcript.review.json': [{'word': 'Olá', 'flags': ['unaligned']}],
        'manifest.json': {'model': 'large-v3', 'language': 'pt', 'inputs': [{'audio': '/private/tmp/input.wav'}]},
        'execution.json': {'source_sha256': 'audio-digest', 'code': {'decoder.py': 'code-digest'},
                           'completed': {}, 'preflight': {}},
    }
    for name, value in data.items():
        (out / name).write_text(json.dumps(value), encoding='utf-8')
    for suffix, content in {'csv': 'Speaker,Start Time,End Time,Text\r\nParticipant 3,,,Olá\r\n',
                            'vtt': 'WEBVTT\n\n', 'txt': 'Participant 3\nOlá\n'}.items():
        (out / f'transcript.{suffix}').write_bytes(content.encode('utf-8'))


def test_command_result_and_cleanup(tmp_path, monkeypatch):
    audio = tmp_path / 'interview with spaces.wav'
    audio.write_bytes(b'fake')
    seen = {}

    def run(command, **kwargs):
        seen['command'] = command
        out = Path(command[command.index('--output') + 1])
        seen['out'] = out
        assert kwargs.get('shell', False) is False
        assert command[command.index('--audio') + 1] == str(audio)
        write_result(out)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service.subprocess, 'run', run)
    result = service.run_structured(audio, speech_boundaries=True, recover_speakers=True)
    assert '--speech-boundaries' in seen['command']
    assert '--refine-speakers' in seen['command']
    assert '--main-python' in seen['command'] and '--align-python' in seen['command']
    assert not seen['out'].exists()
    assert result['duration'] == 42.5
    assert result['transcription'] == 'Participant 3\nOlá\n'
    assert set(result['exports']) == {'csv', 'vtt', 'txt'}
    assert result['exports']['csv']['content'].endswith('Olá\r\n')
    assert result['review'][0]['flags'] == ['unaligned']
    assert result['segments'][0]['start'] is None
    assert result['provenance']['source_sha256'] == 'audio-digest'
    assert '/private/tmp' not in json.dumps(result)


@pytest.mark.parametrize('failure', ['exit', 'validation', 'missing'])
def test_failure_never_returns_partial_success(tmp_path, monkeypatch, failure):
    audio = tmp_path / 'audio.wav'
    audio.touch()
    outputs = []

    def run(command, **kwargs):
        out = Path(command[command.index('--output') + 1])
        outputs.append(out)
        if failure != 'missing':
            write_result(out)
        if failure == 'validation':
            (out / 'result.json').write_text('{"status":"completed","validation":{"status":"failed"}}')
        return SimpleNamespace(returncode=1 if failure == 'exit' else 0)

    monkeypatch.setattr(service.subprocess, 'run', run)
    with pytest.raises(RuntimeError):
        service.run_structured(audio)
    assert not outputs[0].exists()


def test_invalid_options_do_not_start_worker(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        pytest.fail('worker não deve iniciar')
    monkeypatch.setattr(service.subprocess, 'run', forbidden)
    with pytest.raises(ValueError):
        service.run_structured(tmp_path / 'missing.wav')
    audio = tmp_path / 'audio.wav'
    audio.touch()
    with pytest.raises(ValueError):
        service.run_structured(audio, language='auto')
