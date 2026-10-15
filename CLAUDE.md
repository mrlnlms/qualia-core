# Qualia Core — CLAUDE.md

Motor de análise qualitativa. API REST local stateless — recebe texto/áudio/vídeo, devolve JSON. Qualia não sabe o que os dados significam; quem interpreta é o consumer.

## Retomada da transcrição estruturada

Antes de continuar essa frente, ler `docs/TRANSCRIPTION_STATUS.md`, depois `docs/TRANSCRIPTION_BENCHMARK.md`. No checkout com os dados privados, ler também `local-transcript-benchmark/CONTINUIDADE-2026-10-15.md` e `EXECUTION-STATUS.json`. A implementação de referência é a v9, no commit `671df37`; os dois áudios novos já foram processados integralmente. O usuário pediu encerrar com documentação/commit, sem novos ajustes ou execuções. A apresentação da comparação com Dovetail foi considerada difícil de conferir por diferenças de timestamps; o critério de qualidade permanece inconclusivo. Não retomar modelos/testes automaticamente: aguardar novo pedido e liberação da máquina para trabalho pesado. `local-transcript-benchmark/` é privado e está excluído deste checkout via `.git/info/exclude`; os arquivos dessa pasta não acompanham o Git.

## Comandos essenciais

```bash
# Ativar venv
source .venv/bin/activate

# Rodar API
python -m uvicorn qualia.api:app --port 8000

# Testes
pytest tests/ -v

# Testes com coverage
pytest tests/ --cov=qualia --cov-report=term-missing

# Frontend dev (porta 5173, proxy → 8000)
make frontend-dev

# Frontend build (gera dist/ servido pelo FastAPI)
make frontend-build
```

## Arquitetura

```
qualia/
  core/             # Engine — descoberta de plugins, dependências, cache, execução
    __init__.py     # Fachada de re-exports
    interfaces.py   # PluginType, PluginMetadata, IPlugin e variantes
    models.py       # Document, ExecutionContext, PipelineStep, PipelineConfig
    base_plugins.py # BaseAnalyzerPlugin, BaseVisualizerPlugin, BaseDocumentPlugin
    engine.py       # QualiaCore — orquestrador principal
    loader.py       # PluginLoader (auto-descoberta eager/lazy)
    cache.py        # CacheManager (LRU + TTL)
    resolver.py     # DependencyResolver (ordenação topológica)
    config.py       # ConfigurationRegistry (normalização, validação, calibração)
  cli/
    commands/     # Comandos Click (analyze, batch, export, watch, etc.)
    interactive/  # Menu interativo
      handlers.py   # Fachada de orquestração (delega pra actions/services)
      actions.py    # Lógica de execução (analyze, visualize, pipeline)
      services.py   # Settings e sistema (cache, config, deps, open file)
      menu.py       # Menu principal + navegação
      wizards.py    # PipelineWizard
      utils.py      # Helpers (choose_plugin, configure_parameters)
  api/            # FastAPI — REST API
    __init__.py   # Bootstrap: app, CORS, routers, SPA
    deps.py       # Dependências compartilhadas (get_core, track, validate_plugin_config, require_plugin_type)
    schemas.py    # Modelos Pydantic (request/response)
    routes/       # Endpoints por domínio (analyze, process, visualize, pipeline, etc.)
    monitor.py    # Métricas + SSE stream
    templates/    # monitor.html (dashboard HTML/CSS/JS)
    webhooks.py   # Webhook genérico
  frontend/       # Svelte 5 + Vite (Home, Analyze, Transcribe, Monitor, Workflow)
plugins/          # Cada plugin em sua pasta, auto-descoberto pelo core
tests/            # pytest — rodar `pytest tests/ -v` pra contagem e status
```

## Plugins

Tipos: `BaseAnalyzerPlugin`, `BaseDocumentPlugin`, `BaseVisualizerPlugin`.

O core descobre plugins automaticamente em qualquer profundidade dentro de `plugins/` — basta ter `__init__.py` que exporte a classe. Organize como quiser (flat, por tipo, por domínio). Pastas cujo nome começa com `_` são ignoradas (ex: `_templates`). Sem registro manual.

**Existentes:** descobertos automaticamente. Ver `GET /plugins` ou `ls plugins/`.

**Provides (contrato):** analyzers e documents declaram `provides=["campo1", "campo2"]` — campos que o resultado DEVE conter. Engine valida com ValueError (contrato enforced). Múltiplos plugins podem declarar o mesmo campo (ex: dois sentiment analyzers com `provides=["sentiment_score"]`) — o consumer escolhe qual rodar. Resolução automática de dependências só funciona quando há provider único; com múltiplos, o consumer deve escolher explicitamente via pipeline. Visualizers não declaram provides.

**Validação de config:** base plugins rejeitam parâmetros desconhecidos (alinhado com API/ConfigRegistry). Config inválida → ValueError no core, 422 na API.

**Thread-safety:** plugins são singletons — `__init__` roda na main thread, `_analyze_impl`/`_process_impl`/`_render_impl` rodam em worker threads via `asyncio.to_thread`. Carregar modelos, corpora e recursos pesados sempre no `__init__`, nunca no método de execução. Templates: `plugins/_templates/` ou `qualia create`.

## ConfigurationRegistry (`qualia/core/config.py`)

- Normaliza schemas dos plugins (integer→int, string→str, boolean→bool)
- Valida configs: tipo, range, options
- Calibra parâmetros por tamanho de texto (`text_size_adjustments`)
- Cascata: default → text_size adjustments
- `get_consolidated_view()` — snapshot único para consumers

**Sem perfis de domínio.** Perfis são responsabilidade do consumer.

**Loading:** plugins com `__init__` próprio carregam no startup (eager, thread-safe). Os demais carregam no primeiro uso (lazy). Detecção automática via `'__init__' in cls.__dict__`. Ver `docs/TECHNICAL_STATE.md`.

## API endpoints principais

- `GET /plugins` — lista plugins
- `POST /analyze/{plugin_id}` — análise de texto (404 plugin, 422 config/tipo, 504 timeout 60s)
- `POST /process/{plugin_id}` — processamento de documento (404 plugin, 422 config/tipo, 504 timeout 60s)
- `POST /transcribe/{plugin_id}` — transcreve áudio/vídeo (multipart, 422 config/tipo)
- `POST /visualize/{plugin_id}` — gera visualização (422 config/tipo, 504 timeout 60s)
- `POST /pipeline` — executa sequência de plugins (encadeia texto entre steps)
- `GET /config/consolidated` — todos os schemas + rules
- `GET /cache/stats` — estatísticas do cache (size, hits, misses, evictions)
- `POST /webhook/custom` — webhook genérico (extrai texto, analisa)

## Convenções

- **Commits:** mensagens descritivas em português, sem Co-Authored-By
- **API:** doc_id inclui hash do conteúdo (evita colisão de cache)
- **Python:** venv em `./.venv/`
- **Secrets:** `.env` no `.gitignore`, `.env.example` commitado como template
- **Load env:** `python-dotenv` com `load_dotenv()` no topo de `qualia/api/__init__.py`
- **Frontend:** operações async sempre com loading/progress feedback visual
- **README:** tom honesto e acessível, sem hype
- **Pipeline:** fail-fast — core levanta RuntimeError, API traduz pra HTTPException (422 validação, 504 timeout, 400 erro genérico)
- **Packaging:** `pyproject.toml` (não tem mais setup.py). Extras: `api`, `viz`, `nlp`, `ml` (PyTorch, transformers, sentence-transformers), `transcription`, `export` (pandas, openpyxl), `dev`, `all`
- **Diagnóstico:** `qualia list --check` mostra saúde dos plugins (eager/lazy, erros de discovery com classificação e sugestão de fix)
- **Estabilidade:** interfaces classificadas como stable/experimental em `docs/TECHNICAL_STATE.md` seção Stability
- **Docs mortos:** ficam em `docs/morto/` (ignorado pelo git), docs ativos em `docs/`

## Decisões arquiteturais (settled — não reabrir)

1. **Stateless.** Document é efêmero — sem `_analyses`, `_variants`, `_cache`. Dead code stateful foi removido. Se encontrar referências, são resíduos a limpar.
2. **Sem perfis de domínio.** ConfigurationRegistry normaliza/valida/calibra, mas perfis são do consumer.
3. **Pipeline chaining adiado.** `execute_pipeline()` no engine passa o documento original pra todos os steps. A API faz chaining de texto. Unificar quando houver caso de uso real.
4. **CORS configurável.** `CORS_ALLOWED_ORIGINS` env var, default `*`. Em produção o operador restringe.
5. **Três tipos de plugin, ponto.** ANALYZER, DOCUMENT, VISUALIZER. IFilterPlugin e IComposerPlugin foram removidos. Não reintroduzir.
6. **ConfigRegistry rejeita tipos desconhecidos.** `_validate_type` retorna erro para tipos fora do mapa (int, float, bool, str, list, dict).
7. **API bind 127.0.0.1.** Docker usa 0.0.0.0 no CMD. O `__main__.py` usa 127.0.0.1. Intencional.
8. **Upload 500MB engine-level.** Plugins com limites menores (ex: Groq 25MB) tratam internamente. Engine não se acopla a provider.
9. **Tempfile no timeout não é deletado.** Thread órfã de `asyncio.to_thread` pode estar lendo. SO limpa via tmpwatch.
10. **Visualizers geram HTML com scripts.** By design — D3, Plotly precisam de JS. Iframe sandbox restringe. API local-first, user controla plugins.

## Ecossistema

- **Qualia Engine** (este repo) — API REST, motor agnóstico
- **qualia-coding** (plugin Obsidian) — codificação qualitativa cross-media, consome Qualia
- **Consumers** (DeepVoC, Observatório) — pipelines de domínio que chamam o Qualia
