# plugins/documents/transcription_local/__init__.py
"""
Plugin de transcrição local via whisper.cpp.

Roda 100% local, otimizado para Apple Silicon.
Não depende de API externa — privacidade total, sem custo por uso.

Requer:
    - pip install qualia-core[transcription-local]
    - ffmpeg instalado (verificar se pywhispercpp já inclui)

Exemplo de uso via API:
    curl -X POST http://localhost:8000/transcribe/transcription_local \
      -F "file=@audio.mp3" \
      -F 'config={"model": "large-v3", "language": "pt"}'
"""

from pathlib import Path
from typing import Any, Dict

from qualia.core import BaseDocumentPlugin, PluginMetadata, PluginType, Document

# Importação guarded — plugin funciona sem pywhispercpp instalado
try:
    from pywhispercpp.model import Model as WhisperModel
    HAS_PYWHISPERCPP = True
except ImportError:
    WhisperModel = None
    HAS_PYWHISPERCPP = False


class TranscriptionLocalPlugin(BaseDocumentPlugin):
    """Transcreve áudio/vídeo localmente via whisper.cpp."""

    def meta(self) -> PluginMetadata:
        return PluginMetadata(
            id="transcription_local",
            type=PluginType.DOCUMENT,
            name="Local Transcription (whisper.cpp)",
            description="Transcrição de áudio/vídeo via whisper.cpp, otimizado para Apple Silicon",
            version="0.1.0",
            provides=["transcription", "detected_language", "duration"],
            requires=[],
            parameters={
                "model": {
                    "type": "str",
                    "description": "Modelo Whisper a usar",
                    "default": "large-v3",
                    "options": ["tiny", "base", "small", "medium", "large-v3"],
                },
                "language": {
                    "type": "str",
                    "description": "Idioma do áudio (auto para detecção automática)",
                    "default": "auto",
                    "options": ["auto", "pt", "en", "es"],
                },
                "include_timestamps": {
                    "type": "bool",
                    "description": "Incluir timestamps no texto transcrito",
                    "default": False,
                },
            },
        )

    def _process_impl(
        self, document: Document, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Transcreve o arquivo referenciado em document.metadata['file_path']."""

        # Validar file_path
        file_path = document.metadata.get("file_path")
        if not file_path:
            raise ValueError(
                "Nenhum arquivo fornecido. Use o endpoint /transcribe com upload de arquivo."
            )

        file_path = Path(file_path)
        if not file_path.exists():
            raise ValueError(f"Arquivo não encontrado: {file_path}")

        # Verificar dependência
        if not HAS_PYWHISPERCPP:
            raise ValueError(
                "pywhispercpp não instalado. Execute: pip install qualia-core[transcription-local]"
            )

        # Transcrição (implementação no próximo task)
        raise NotImplementedError("Transcrição pendente")
