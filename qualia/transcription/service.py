"""Adaptador stateless do coordenador para plugins; importar não carrega modelos.

Requer o checkout com scripts e os dois ambientes preparados. A execução real
é pesada; todos os workers são lançados somente por run_structured().
"""
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[2]
MIME = {'csv': 'text/csv;charset=utf-8', 'vtt': 'text/vtt;charset=utf-8',
        'txt': 'text/plain;charset=utf-8'}


def _read(out, name):
    return json.loads((out / name).read_text(encoding='utf-8'))


def collect_result(out):
    """Lê apenas uma rodada concluída/validada; nunca devolve caminhos temporários."""
    receipt = _read(out, 'result.json')
    if receipt.get('status') != 'completed' or receipt.get('validation', {}).get('status') != 'passed':
        raise RuntimeError('A transcrição estruturada não passou na validação.')
    transcript = _read(out, 'transcript.transcription.json')
    config = _read(out, 'manifest.json')
    state = _read(out, 'execution.json')
    exports = {
        suffix: {'filename': f'transcript.{suffix}', 'media_type': mime,
                 'content': (out / f'transcript.{suffix}').read_bytes().decode('utf-8')}
        for suffix, mime in MIME.items()
    }
    return {
        'transcription': exports['txt']['content'],
        'detected_language': config['language'],
        'duration': transcript['audio_duration_seconds'],
        'status': 'completed', 'error': None,
        'exports': exports,
        'segments': _read(out, 'transcript.rows.json'),
        'words': _read(out, 'transcript.assigned-words.json'),
        'review': _read(out, 'transcript.review.json'),
        'quality_audit': receipt['quality_audit'],
        'provenance': {
            'source_sha256': state['source_sha256'],
            'configuration': {k: v for k, v in config.items() if k not in ('inputs', 'output')},
            'code': state['code'],
            'adapter_code': {
                name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
                for name in ('qualia/transcription/service.py',
                             'plugins/documents/transcription_structured/__init__.py')
            },
            'artifacts': {stage: entry['outputs'] for stage, entry in state['completed'].items()},
            'environments': state.get('preflight', {}),
            'validation': receipt['validation'],
            'human_audio_review': 'not_performed',
            'reused_stages': receipt.get('reused_stages', []),
        },
    }


def run_structured(audio, *, language='pt', device='mps', speech_boundaries=False, recover_speakers=False):
    """Executa a mesma política do CLI, com WhisperX em interpretador separado.

    Arquivos intermediários são temporários. O JSON retornado contém texto,
    palavras, revisão e proveniência para o consumer guardar junto aos exports.
    Para checkpoints persistentes/retomada entre sessões, usar o CLI diretamente.
    """
    audio = Path(audio).absolute()
    if not audio.is_file():
        raise ValueError('Nenhum arquivo de áudio válido fornecido.')
    if (language not in ('pt', 'en', 'es') or device not in ('mps', 'cpu')
            or type(speech_boundaries) is not bool or type(recover_speakers) is not bool):
        raise ValueError('Idioma/dispositivo/proteção de bordas inválidos.')
    with tempfile.TemporaryDirectory(prefix='qualia-transcript-') as folder:
        out = Path(folder)
        # O coordenador exige pasta vazia; log fica fora dela.
        work = out / 'run'
        work.mkdir()
        command = [str(REPO / '.venv/bin/python'), str(REPO / 'scripts/transcribe_structured.py'),
                   '--audio', str(audio), '--output', str(work), '--language', language,
                   '--device', device, '--main-python', str(REPO / '.venv/bin/python'),
                   '--align-python', str(REPO / 'local-transcript-benchmark/.venv-align/bin/python')]
        if speech_boundaries:
            command.append('--speech-boundaries')
        if recover_speakers:
            command.append('--refine-speakers')
        try:
            with (out / 'coordinator.log').open('w', encoding='utf-8') as log:
                completed = subprocess.run(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=False)
            if completed.returncode:
                raise RuntimeError('Transcrição estruturada falhou. Confira os ambientes e modelos pelo comando local.')
            return collect_result(work)
        except (OSError, ValueError, KeyError) as error:
            raise RuntimeError('Não foi possível executar ou ler a transcrição estruturada. Confira o checkout e os dois ambientes.') from error
