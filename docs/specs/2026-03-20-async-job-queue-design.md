# Spec: Async Job Queue — Processamento assíncrono para plugins pesados

**Data:** 2026-03-20
**Status:** Design aprovado
**Autor:** Marlon Lemes
**Prioridade:** Alta — pré-requisito para uso real de plugins de ML e transcrição local

## Contexto

O qualia-core executa plugins via `asyncio.to_thread` com timeout de 60s na camada API. Funciona para plugins leves (word frequency, sentiment), mas é insuficiente para:

- **Transcrição local** (whisper.cpp): áudio de 1h+ pode levar vários minutos
- **BERTopic / topic modeling**: minutos dependendo do corpus
- **Embeddings e clustering**: escala com volume de dados
- **Qualquer plugin de ML futuro**: tendência é processamento cada vez mais pesado

O timeout de 60s é imposto pelos route handlers (`asyncio.wait_for` em `analyze.py`, `process.py`, etc.). O engine (`engine.py`) é síncrono e não sabe de timeouts. A solução atua na camada API — um `JobManager` que envelopa chamadas ao engine e gerencia execução em background — com data models compartilhados acessíveis a ambas as camadas.

## Mudança em PluginMetadata

O campo `heavy: bool = False` será adicionado ao dataclass `PluginMetadata` em `qualia/core/interfaces.py`:

```python
@dataclass
class PluginMetadata:
    id: str
    name: str
    version: str
    type: PluginType
    description: str = ""
    # ... campos existentes omitidos (requires, can_use, accepts, etc.) ...
    heavy: bool = False  # novo — plugins pesados rodam async por default
```

Impacto:
- `GET /plugins` passa a incluir `heavy` na resposta (via `PluginInfo` schema em `schemas.py`)
- Plugins existentes não declaram `heavy` → default `False` → comportamento inalterado
- Plugins novos (transcrição local, BERTopic) declaram `heavy = True` na metadata

## Modelo do Job

```python
class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class JobType(str, Enum):
    single = "single"
    pipeline = "pipeline"

@dataclass
class JobStep:
    plugin_id: str
    status: JobStatus          # pending | running | completed | failed
    progress: float | None     # 0.0 a 1.0 (reservado para uso futuro)
    result: dict | None
    error: str | None

@dataclass
class Job:
    id: str                    # UUID
    type: JobType              # single | pipeline
    status: JobStatus          # pending | running | completed | failed | cancelled
    plugin_id: str             # plugin principal (single) ou primeiro plugin (pipeline)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: float            # 0.0 a 1.0 — progresso geral
    current_step: int          # 0-based, qual step está rodando (pipeline)
    total_steps: int           # total de steps (1 se single)
    steps: list[JobStep]       # vazio se single, populado se pipeline
    result: dict | None        # resultado final quando completed
    error: str | None          # mensagem de erro quando failed
    callback_url: str | None   # webhook opcional
    temp_files: list[str]      # paths de temp files associados (cleanup no final)
    ttl: int                   # segundos até expirar (default: 3600)
```

### Progresso — escopo v1

Na v1, o progresso é **step-level apenas**:
- Job single: progresso é 0.0 (pending/running) ou 1.0 (completed)
- Pipeline: progresso = steps_concluidos / total_steps (ex: 3 de 5 = 0.6)
- O campo `JobStep.progress` existe no modelo mas será `None` na v1

Progresso intra-plugin (ex: "transcrevendo... 35%") requer um mecanismo de callback que não existe hoje. Plugins não sabem que estão rodando async e não têm como reportar progresso. Isso será endereçado numa v2 — possivelmente via `progress_callback` no `ExecutionContext`. Na v1, o frontend mostra qual etapa está rodando, não a % interna.

### Armazenamento

- In-memory (dict protegido por `threading.Lock`) — sem dependência externa
- Jobs expiram após TTL configurável (default: 1h)
- Background task via `lifespan` do FastAPI (não `on_event`) a cada 5min remove jobs expirados e limpa temp files associados
- Backlog futuro: persistência em SQLite se necessário

### Temp files

Endpoints de upload (`/transcribe`, `/analyze/.../file`) criam temp files. No fluxo sync, o route handler limpa após execução. No fluxo async:
- O `Job` registra paths dos temp files em `temp_files: list[str]`
- Cleanup acontece quando o job completa, falha, é cancelado, ou expira
- O `JobManager` é responsável pela limpeza (não o route handler)
- Fallback: SO limpa via tmpwatch (alinhado com decisão settled #9)

## Roteamento sync vs async

### Regras

| Cenário | Comportamento |
|---------|--------------|
| Plugin leve, request normal | Sync (como hoje) |
| Plugin leve, `?async=true` | Async (útil para input grande) |
| Plugin pesado (`heavy: true`), request normal | Async automático |
| Plugin pesado, `?sync=true` | Sync (consumer assume risco de timeout) |
| Pipeline, request normal | Async por default |
| Pipeline, `?sync=true` | Sync (consumer assume risco de timeout) |

### Como funciona

- Plugin declara `heavy: true` em `PluginMetadata` (campo opcional, default `False`)
- Request para plugin heavy → API cria Job via `JobManager`, retorna 202 + job ID
- Request para plugin leve → executa sync como hoje, retorna 200 + resultado
- Pipeline → async por default (soma de steps pode ultrapassar 60s)
- Consumer pode forçar sync com query param `?sync=true` — assume risco do timeout de 60s
- Consumer pode forçar async com query param `?async=true` — útil para plugins leves com input grande

### Backward compatibility

**Nenhum plugin existente será marcado como `heavy: true`.** Todos os plugins atuais são leves. O campo `heavy` entra com default `False`, então:
- Consumers existentes (CodeMarker, DeepVoC, Observatório) não são afetados
- Comportamento muda apenas quando um plugin *novo* declara `heavy: true`
- Consumer que não trata 202 pode usar `?sync=true` como escape hatch temporário
- Pipeline ganha async, mas como é feature nova (workflow builder), não há consumer legado

### Query params nos endpoints

Os query params `sync` e `async` são adicionados como parâmetros opcionais do FastAPI, independentes do body/form:

```python
# Exemplo para analyze.py
@router.post("/{plugin_id}")
async def analyze(
    plugin_id: str,
    request: AnalyzeRequest,
    sync: bool = Query(False, alias="sync"),
    async_mode: bool = Query(False, alias="async"),
):
```

Para endpoints multipart (`/transcribe`, `/analyze/.../file`), query params funcionam normalmente com `Form` + `File` — FastAPI trata query params separadamente do body.

### Impacto nos plugins existentes

**Nenhum.** Plugins não mudam. A camada API envelopa a chamada ao engine num Job quando necessário. O plugin nem sabe que está rodando async. `_analyze_impl`, `_process_impl`, `_render_impl` continuam iguais.

## Execução e limites

### Concorrência

- Máximo 1 job pesado rodando simultaneamente (v1)
- Motivo: no M2 8GB, dois modelos grandes (~2-3GB cada) causam OOM
- Configurável via `QUALIA_MAX_CONCURRENT_HEAVY_JOBS=1` (env var)
- Jobs excedentes ficam em `pending` na fila, iniciam quando o slot liberar

### Pipeline

- Steps rodam em sequência (como hoje)
- Resultado de um step alimenta o próximo (chaining de texto pela API, via `extract_chained_text`)
- Se um step falha, pipeline inteiro falha (fail-fast)
- Progresso geral = steps_concluidos / total_steps

### Cancelamento

- Jobs `pending` → podem ser cancelados (removidos da fila)
- Jobs `running` → não canceláveis (threads Python não são interrompíveis)
- Jobs `completed`/`failed` → nada a cancelar

## Acompanhamento do job

Três canais complementares:

### SSE (tempo real) — canal primário

- Endpoint `GET /jobs/{job_id}/stream`
- Conexão aberta que recebe eventos conforme o job progride
- Padrão: `asyncio.Queue` + heartbeat (1s), como o Monitor usa
- **Diferença do Monitor:** Monitor tem broadcast global (uma mensagem → todos os clients). Jobs usam roteamento per-job: `dict[job_id, set[asyncio.Queue]]` — cada conexão SSE recebe apenas eventos do job que está assistindo
- Eventos:
  ```
  event: status
  data: {"status": "running", "progress": 0.0, "current_step": 0, "total_steps": 5}

  event: step
  data: {"step": 1, "total_steps": 5, "step_plugin": "sentiment", "step_status": "completed"}

  event: step
  data: {"step": 2, "total_steps": 5, "step_plugin": "transcription_local", "step_status": "running"}

  event: completed
  data: {"status": "completed", "result": {...}}
  ```

### Polling (fallback)

- `GET /jobs/{job_id}` — retorna estado atual completo
- Frontend usa se conexão SSE cair
- Intervalo sugerido: 3 segundos
- Útil para consumers simples (scripts, curl)

### Webhook (notificação)

- Consumer envia `callback_url` opcional ao criar o job
- Quando job termina (completed ou failed), Qualia faz POST no URL com o resultado
- Retry: 2 tentativas com delay crescente (1s, 5s)
- Best-effort — sem garantia de entrega. Polling/SSE são os canais confiáveis
- Payload do webhook (single):
  ```json
  {
    "job_id": "uuid",
    "type": "single",
    "status": "completed",
    "plugin_id": "sentiment",
    "result": {"sentiment_score": 0.85, "sentiment_label": "positive"},
    "completed_at": "2026-03-20T14:30:00Z"
  }
  ```
- Payload do webhook (pipeline):
  ```json
  {
    "job_id": "uuid",
    "type": "pipeline",
    "status": "completed",
    "steps_executed": 3,
    "results": [
      {"plugin_id": "transcription_local", "result": {"transcription": "..."}},
      {"plugin_id": "sentiment", "result": {"sentiment_score": 0.85}},
      {"plugin_id": "wordcloud", "result": {"html": "..."}}
    ],
    "completed_at": "2026-03-20T14:30:00Z"
  }
  ```

## Endpoints

### Novos

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/jobs` | GET | Lista jobs ativos (filtro por status, plugin) |
| `/jobs/{job_id}` | GET | Status + resultado do job |
| `/jobs/{job_id}/stream` | GET | SSE — acompanhamento em tempo real |
| `/jobs/{job_id}` | DELETE | Cancela job pendente |

### Erros dos endpoints novos

| Endpoint | Código | Cenário |
|----------|--------|---------|
| `GET /jobs/{job_id}` | 404 | Job não encontrado ou expirado |
| `GET /jobs/{job_id}/stream` | 404 | Job não encontrado ou expirado |
| `DELETE /jobs/{job_id}` | 404 | Job não encontrado |
| `DELETE /jobs/{job_id}` | 409 | Job já running ou finalizado |

### Endpoints existentes modificados

`POST /analyze/{id}`, `POST /process/{id}`, `POST /transcribe/{id}`, `POST /visualize/{id}`:
- Plugin leve sem parâmetro: sync como hoje (sem mudança)
- Plugin pesado sem parâmetro: retorna 202 + job ID
- `?sync=true`: força sync (assume risco de timeout)
- `?async=true`: força async (útil para plugin leve com input grande)

`POST /pipeline`:
- Sem parâmetro: retorna 202 + job ID (async por default)
- `?sync=true`: força sync (assume risco de timeout)

### Resposta async (202)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "status_url": "/jobs/550e8400-e29b-41d4-a716-446655440000",
  "stream_url": "/jobs/550e8400-e29b-41d4-a716-446655440000/stream"
}
```

## Impacto no frontend

### Camada de abstração

Um helper `executePlugin()` centraliza a lógica:
- Recebe resultado direto (200) → retorna normalmente
- Recebe job ID (202) → abre SSE, acompanha progresso, retorna quando completa
- Resto do frontend usa o helper sem saber se é sync ou async

### UI de progresso

- Etapa atual quando é pipeline: "Etapa 2 de 5: transcrevendo..."
- Status textual: "Na fila...", "Processando...", "Concluído"
- Onde hoje tem spinner genérico, passa a mostrar etapa atual
- Barra de progresso granular (%) virá na v2, quando plugins puderem reportar progresso

### Workflow builder

- Pipeline executado → recebe job → mostra progresso por etapa
- Etapa falha → marca em vermelho com mensagem de erro

### Página de jobs (opcional v1)

- Lista jobs em andamento e recentes
- Cancelar jobs pendentes
- Ver resultado de jobs completos
- Não obrigatória na v1

## Arquitetura — onde o código vive

| Componente | Arquivo | Responsabilidade |
|-----------|---------|-----------------|
| Job data models | `qualia/core/jobs.py` (novo) | Job, JobStatus, JobType, JobStep (dataclasses) |
| JobManager | `qualia/api/jobs.py` (novo) | Orquestração: fila, execução, concorrência, SSE, cleanup, webhook |
| Job routes | `qualia/api/routes/jobs.py` (novo) | Endpoints /jobs |
| Roteamento | Endpoints existentes em `qualia/api/routes/` | Lógica sync/async nos handlers |
| PluginMetadata | `qualia/core/interfaces.py` (modificado) | Campo `heavy: bool = False` |
| PluginInfo schema | `qualia/api/schemas.py` (modificado) | Campo `heavy` na resposta da API |
| Cleanup task | `qualia/api/__init__.py` (modificado) | Adicionar `lifespan` context manager (não existe hoje) para registrar cleanup periódico |
| Frontend helper | `qualia/frontend/src/lib/api.ts` ou similar | executePlugin() wrapper |

**Separação de responsabilidades:**
- `qualia/core/jobs.py` — apenas data models (Job, enums, dataclasses). Sem lógica de execução. Core permanece síncrono.
- `qualia/api/jobs.py` — `JobManager` com toda a lógica async: criação de jobs, fila, execução via `asyncio.to_thread`, concorrência, SSE pub/sub, cleanup de temp files, webhook dispatch. Vive na camada API porque é fundamentalmente async e depende de FastAPI/asyncio.

## Testes

### Job lifecycle
- Criar job → status pending
- Job inicia → status running
- Job completa → status completed + resultado
- Job falha → status failed + erro

### Roteamento
- Plugin leve → sync (200)
- Plugin pesado → async (202 + job ID)
- Plugin pesado + `?sync=true` → sync (200)
- Plugin leve + `?async=true` → async (202 + job ID)
- Pipeline → async (202)
- Pipeline + `?sync=true` → sync (200)

### Fila e limites
- 1 job rodando + outro chega → pending
- Primeiro termina → segundo inicia
- Cancelar pending → sucesso
- Cancelar running → 409

### Progresso
- Pipeline 5 etapas, step 3 rodando → progresso = 0.4
- SSE entrega eventos de step

### TTL e limpeza
- Job expira após TTL → 404 no GET
- Cleanup remove expirados + temp files

### Temp files
- Job async com upload → temp file registrado no job
- Job completa → temp file removido
- Job expira → temp file removido

### Webhook
- Job completa → POST no callback_url com payload correto
- Pipeline completa → payload inclui results[] com todos os steps
- callback_url fora do ar → retry 2x, depois desiste
- Job acessível via polling independente do webhook

### SSE
- Abrir stream → recebe eventos do job correto
- Dois clients no mesmo job → ambos recebem
- Client no job A não recebe eventos do job B

### Regressão
- Endpoints existentes sem parâmetro async → comportamento idêntico ao atual
- Testes existentes continuam passando
- Nenhum plugin existente retorna 202 (todos são `heavy: false`)

## Decisões de design

1. **In-memory, não banco.** Qualia é local-first. Jobs são efêmeros. SQLite é backlog.
2. **1 job pesado simultâneo.** Limite de memória real no hardware target (M2 8GB).
3. **Pipeline async por default.** Soma de steps pode ultrapassar 60s. Consumer pode forçar sync.
4. **Webhook best-effort.** Sem fila de retry persistente. Consumer tem polling/SSE como canais confiáveis.
5. **Threads, não processos.** Reutiliza `asyncio.to_thread` existente. Multiprocessing é complexidade que não se justifica na v1.
6. **Running não cancela.** Limitação do Python, não escolha de design. Documentar claramente.
7. **Progresso step-level na v1.** Sem progresso intra-plugin. Mecanismo de callback será v2.
8. **JobManager na API, models no core.** Engine permanece síncrono. Orquestração async vive na camada API.
9. **Backward compatible.** Nenhum plugin existente é `heavy`. Consumers atuais não são afetados.
