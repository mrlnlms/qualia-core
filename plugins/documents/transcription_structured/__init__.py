"""Áudio → falantes automáticos e CSV/VTT/TXT pelo coordenador local."""
from pathlib import Path

from qualia.core import BaseDocumentPlugin, PluginMetadata, PluginType
from qualia.transcription.service import run_structured


class TranscriptionStructuredPlugin(BaseDocumentPlugin):
    """Nenhum modelo é carregado no startup nem compartilhado entre gravações."""

    def meta(self):
        return PluginMetadata(
            id='transcription_structured', type=PluginType.DOCUMENT,
            name='Local Transcription — speakers & exports', version='0.1.0',
            description='Transcrição local large-v3 com falantes automáticos e downloads CSV, VTT e TXT.',
            provides=['transcription', 'detected_language', 'duration', 'exports',
                      'segments', 'words', 'review', 'quality_audit', 'provenance'],
            requires=[], heavy=True,
            parameters={
                'language': {'type': 'str', 'default': 'pt', 'options': ['pt', 'en', 'es'],
                             'description': 'Idioma da gravação. Política avaliada em português.'},
                'device': {'type': 'str', 'default': 'mps', 'options': ['mps', 'cpu'],
                           'description': 'Dispositivo para falantes e alinhamento (mps: Apple Silicon).'},
                'speech_boundaries': {'type': 'bool', 'default': False,
                                      'description': 'Experimental: limitar sobras externas sem voz detectada. Pode perder falas breves ou baixas.'},
                'recover_speakers': {'type': 'bool', 'default': False,
                                     'description': 'Experimental: revisar lacunas e trocas curtas de falante. Atribuições inferidas ficam marcadas para revisão.'},
            },
        )

    def _process_impl(self, document, config, context):
        audio = document.metadata.get('file_path')
        if not audio or not Path(audio).is_file():
            raise ValueError('Nenhum arquivo válido fornecido. Use upload em /transcribe.')
        return run_structured(audio, language=config['language'], device=config['device'],
                              speech_boundaries=config['speech_boundaries'], recover_speakers=config['recover_speakers'])
