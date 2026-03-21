# Spec: transcription_local — Transcrição Local via whisper.cpp

**Data:** 2026-03-20
**Status:** Aprovado (design)
**Autor:** Marlon Lemes

## Contexto

O qualia-core já possui um plugin `transcription` que usa a API Groq Whisper. Este spec descreve um novo plugin independente (`transcription_local`) que roda transcrição **100% local** via whisper.cpp, otimizado para Apple Silicon.

### Motivação

- Eliminar dependência de API externa para transcrição
- Privacidade total — áudio não sai da máquina
- Sem custo por uso
- Sem limite de tamanho de arquivo (API Groq limita 25MB)
- Possibilidade de evoluir o plugin incrementalmente (diarization, fine-tuning, etc.)

### Decisão técnica: whisper.cpp vs PyTorch

| Critério | PyTorch (whisper) | whisper.cpp |
|----------|-------------------|-------------|
| Performance no M2 | Baseline | ~2-4x mais rápido |
| RAM (large-v3) | ~5GB | ~2-3GB (quantizado) |
| Otimização Apple Silicon | Parcial (MPS) | Nativa (Neural Engine + GPU) |
| Qualidade | Referência | Idêntica (mesmo modelo) |
| Binding Python | openai-whisper | pywhispercpp |

**Decisão:** whisper.cpp via `pywhispercpp`. Mesma qualidade, melhor performance, menor uso de RAM.

## Abordagem

**Plugin novo e independente** (Abordagem C do brainstorming). Não altera o plugin Groq existente.

Justificativa: filosofia do qualia-core — cada plugin é uma unidade isolada. Mesma interface (`provides`), backends independentes. O core descobre, o usuário escolhe qual usar. Amanhã pode ter `transcription_deepgram`, `transcription_assemblyai`, etc. É um workbench.

## Design

### Estrutura

```
plugins/documents/transcription_local/
└── __init__.py    # TranscriptionLocalPlugin (BaseDocumentPlugin)
```

### Metadata

```python
PluginMetadata(
    id="transcription_local",
    type=PluginType.DOCUMENT,
    name="Local Transcription (whisper.cpp)",
    description="Transcrição de áudio/vídeo via whisper.cpp, otimizado para Apple Silicon",
    version="0.1.0",
    provides=["transcription", "detected_language", "duration"],
    requires=[],
    heavy=True,  # roda async via JobManager (ver 2026-03-20-async-job-queue-design.md)
    parameters={
        "model": {
            "type": "str",
            "default": "large-v3",
            "options": ["tiny", "base", "small", "medium", "large-v3"],
        },
        "language": {
            "type": "str",
            "default": "auto",  # "auto" = omitir param no whisper.cpp (detecta nos primeiros 30s)
            "options": ["auto", "pt", "en", "es"],
        },
        "include_timestamps": {
            "type": "bool",
            "default": False,
        },
    },
)
```

### Carregamento

- **LAZY load** — sem `__init__` custom, instanciado no primeiro uso (mesmo padrão do plugin Groq)
- Guarded import do `pywhispercpp` (mesmo padrão do plugin Groq com `HAS_GROQ`)
- Modelo carregado no primeiro `_process_impl`, cacheado como atributo de instância (`self._model`)
- Download do modelo automático no primeiro uso (~3GB para large-v3, gerenciado pelo pywhispercpp, cache em disco)
- Justificativa: carregar 3GB no startup travaria a inicialização e consumiria RAM mesmo sem uso

### Fluxo de processamento

```
arquivo (via API ou CLI)
  → tempfile salvo pelo endpoint
  → path via document.metadata["file_path"]
  → whisper.cpp processa (ffmpeg decodifica qualquer formato)
  → retorna segmentos com texto + timestamps
  → monta resultado conforme parâmetros
```

### Formatos suportados

Tudo que o ffmpeg decodifica — sem whitelist artificial de extensões.

**Áudio:** mp3, wav, m4a, aac, ogg, flac, wma, opus, amr, aiff, caf
**Vídeo:** mp4, mkv, webm, avi, mov, wmv, flv, ts, 3gp
**Regra:** se o ffmpeg decodifica, o plugin transcreve. Erro do ffmpeg propagado com mensagem clara.

**Nota:** verificar na implementação se `pywhispercpp` traz ffmpeg embutido ou se é dependência de sistema separada (`brew install ffmpeg`).

### Limite de upload

A rota `/transcribe` atual tem `TRANSCRIPTION_MAX_SIZE = 25MB` (hardcoded para o Groq). Para o plugin local, esse limite não faz sentido — o engine-level é 500MB (decisão arquitetural #8). A implementação deve ajustar a rota para usar o limite do engine (500MB) ou torná-lo configurável por plugin. O plugin local não impõe limite próprio — o limite é a RAM da máquina.

### Output

```python
{
    "transcription": "texto transcrito...",       # sempre presente (provides)
    "detected_language": "pt",                     # sempre presente (provides)
    "duration": 142.5,                             # sempre presente (provides, segundos)
    "status": "completed",                         # convenção da rota /transcribe
    "error": None,                                 # convenção da rota /transcribe
}
```

**Nota sobre `status` e `error`:** Esses campos não estão em `provides` (o engine não os valida), mas a rota `/transcribe` checa `result.get("status") == "error"` para detectar falhas de domínio. O plugin DEVE retornar `status: "completed"` ou `status: "error"` + `error: "mensagem"` para que a rota funcione corretamente.

Quando `include_timestamps=True`, o campo `transcription` inclui marcadores:

```
[00:00:00] Primeiro segmento do áudio...
[00:00:15] Segundo segmento...
[00:01:23] Terceiro segmento...
```

Quando `include_timestamps=False`, texto corrido concatenado.

### Tratamento de erros

| Cenário | Comportamento |
|---------|--------------|
| `pywhispercpp` não instalado | Plugin carrega, `_process_impl` retorna erro: `pip install qualia-core[transcription-local]` |
| ffmpeg ausente (se necessário) | Erro com instrução: `brew install ffmpeg` |
| Arquivo corrompido / formato inválido | Erro do ffmpeg propagado com path do arquivo |
| Modelo não baixado | Download automático no primeiro `_process_impl`, log informando progresso |
| RAM insuficiente | Erro do whisper.cpp propagado, mensagem sugerindo modelo menor |
| Arquivo longo (horas) | Funciona — sem limite artificial. Ver seção de timeout abaixo |

### Processamento longo e Job Queue

Este plugin declara `heavy=True` na metadata. Com a job queue async do core (ver `2026-03-20-async-job-queue-design.md`):

- Requests para este plugin são roteados automaticamente para o `JobManager`
- Endpoint retorna `202 Accepted` + job ID + status/stream URLs
- Consumer acompanha via SSE (`/jobs/{id}/stream`), polling (`/jobs/{id}`), ou webhook
- Plugin continua síncrono internamente — `_process_impl` não muda. O core envelopa a chamada num Job
- Consumer pode forçar sync com `?sync=true` (assume risco do timeout de 60s)
- Limite de 1 job pesado simultâneo (M2 8GB — configurável via `QUALIA_MAX_CONCURRENT_HEAVY_JOBS`)

### Dependências

**Python (via pyproject.toml):**
```toml
transcription-local = ["pywhispercpp"]
```

Instalação: `pip install qualia-core[transcription-local]`

Separado do extra `[transcription]` existente (Groq).

**Sistema (se necessário):**
- ffmpeg — `brew install ffmpeg` (verificar se pywhispercpp já embute)

**Modelo:**
- Download automático (~3GB para large-v3, uma vez, fica em cache)

### Testes

- **Unit:** mock do pywhispercpp, valida montagem do resultado, parâmetros, erros
- **Contrato:** `provides` bate com retorno (padrão do qualia-core)
- **Integração (manual, local):** arquivo real → transcrição real. Não entra no CI.

### Como testar manualmente

**1. Rodar os testes automatizados (não precisa de pywhispercpp):**

```bash
source .venv/bin/activate
pytest tests/test_transcription_local.py -v
```

Esperado: 24 testes passando, 98% coverage. Tudo mockado.

**2. Verificar que o plugin é descoberto pelo core:**

```bash
python -c "
from qualia.core import QualiaCore
core = QualiaCore()
core.discover_plugins()
p = core.registry['transcription_local']
m = p.meta()
print(f'{m.id} v{m.version} — provides: {m.provides}')
print(f'Params: {list(m.parameters.keys())}')
"
```

Esperado: `transcription_local v0.1.0 — provides: ['transcription', 'detected_language', 'duration']`

**3. Verificar via API (sem pywhispercpp — deve dar erro claro):**

```bash
python -m uvicorn qualia.api:app --port 8000 &
# Em outro terminal:
curl -s http://localhost:8000/plugins | python -m json.tool | grep transcription_local
```

Esperado: plugin aparece na lista com seus parâmetros.

```bash
curl -X POST http://localhost:8000/transcribe/transcription_local \
  -F "file=@algum_audio.mp3" \
  -F 'config={"model":"tiny","language":"pt"}'
```

Esperado: erro 422 com mensagem `pywhispercpp não instalado`.

**4. Teste real com transcrição (requer instalação):**

```bash
pip install pywhispercpp
# Primeiro uso baixa o modelo (~75MB para tiny, ~3GB para large-v3)

curl -X POST http://localhost:8000/transcribe/transcription_local \
  -F "file=@audio_curto.mp3" \
  -F 'config={"model":"tiny","language":"pt","include_timestamps":true}'
```

Esperado: JSON com `status: "completed"`, campo `transcription` com texto e timestamps `[HH:MM:SS]`.

**5. Checklist de validação:**

- [ ] `pytest tests/test_transcription_local.py -v` — 24 passed
- [ ] Plugin aparece em `GET /plugins`
- [ ] Sem pywhispercpp: erro claro com instrução de instalação
- [ ] Com pywhispercpp + modelo tiny: transcreve áudio curto (<30s)
- [ ] `include_timestamps=true` gera marcadores `[HH:MM:SS]`
- [ ] `include_timestamps=false` gera texto corrido
- [ ] `language=auto` detecta idioma (retorna "auto" por limitação do binding)
- [ ] Segundo request com mesmo modelo reutiliza cache (sem reload)
- [ ] Trocar modelo entre requests força reload

## Backlog (fora desse spec)

- [ ] Speaker diarization (quem falou o quê)
- [ ] Exportação pra SRT/VTT como formato de arquivo
- [ ] Suporte a modelos fine-tunados
- [ ] Batch processing (múltiplos arquivos)
- [ ] Progress callback (percentual de conclusão)
- [ ] Pre-warm endpoint (carregar modelo em background sem bloquear startup)
