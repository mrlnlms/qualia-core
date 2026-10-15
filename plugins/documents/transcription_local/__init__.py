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
from qualia.transcription.decoder import decoder_params

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
            heavy=True,
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

    def _get_model(self, model_name: str):
        """Instância por gravação, sem estado textual/amostragem de outra chamada."""
        return WhisperModel(model_name, params_sampling_strategy=0, n_threads=4,
                            print_progress=False, print_realtime=False,
                            redirect_whispercpp_logs_to=None, **decoder_params())

    @staticmethod
    def _format_timestamp(centiseconds: int) -> str:
        """Converte centésimos de segundo para formato HH:MM:SS."""
        total_seconds = centiseconds // 100
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"

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

        # Configuração
        model_name = config.get("model", "large-v3")
        language = config.get("language", "auto")
        include_timestamps = config.get("include_timestamps", False)

        # Montar kwargs do transcribe
        transcribe_kwargs: Dict[str, Any] = {}
        if language != "auto":
            transcribe_kwargs["language"] = language

        # Transcrever
        try:
            model = self._get_model(model_name)

            # Detectar idioma antes de transcrever (quando language=auto)
            if language == "auto":
                (detected_lang, _prob), _all_probs = model.auto_detect_language(str(file_path))
                detected_language = detected_lang
            else:
                detected_language = language

            segments = model.transcribe(str(file_path), **transcribe_kwargs)

            # Montar texto
            if include_timestamps:
                lines = []
                for seg in segments:
                    timestamp = self._format_timestamp(seg.t0)
                    lines.append(f"{timestamp} {seg.text.strip()}")
                transcription = "\n".join(lines)
            else:
                transcription = " ".join(seg.text.strip() for seg in segments)

            # Duração a partir do último segmento
            duration = segments[-1].t1 / 100.0 if segments else 0.0

            return {
                "transcription": transcription,
                "detected_language": detected_language,
                "duration": duration,
                "status": "completed",
                "error": None,
            }

        except Exception as e:
            raise RuntimeError(f"Erro na transcrição: {str(e)}") from e
