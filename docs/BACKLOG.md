# Backlog — Qualia Core

Última atualização: 2026-03-20

> Registro histórico consolidado até a data acima. Antes de planejar atividades,
> ler [PROJECT_STATUS.md](PROJECT_STATUS.md), revisado em 24/10/2026: há
> pendências atuais de CI e integração, o Workflow já existe e propostas de
> arquitetura abaixo não devem ser tratadas como decisões adotadas. A frase
> “Nenhum item pendente” refere-se ao encerramento de março.

## Pendente

Nenhum item pendente.

---

### ~~Code reviews Codex #8-#11 + stress tests (2026-03-20) — ~35 bugs, 95 testes novos~~ Concluído

4 rodadas Codex (#8 prompt estruturado, #9-#11 profundidade) + stress tests em duas frentes. 950 testes final.

**Fixes (seleção dos mais relevantes):**
- Cache: doc_id com hash, invalidação pós-restart (.cache_index.json), key canônica (set/Path/dict), set mistos sorted por str
- Upload: streaming pra tempfile (OOM), transcribe 25MB na borda (413)
- Plugins: word_frequency by_segment/by_speaker implementados, sentiment_viz filtra contagens no pie
- Engine: ConfigRegistry valida range/options, context propagado a analyzers e dependências, deps chegam a documents
- Pipeline: acumula dados pra visualizer (não só último), output_format canônico, encadeamento unificado via extract_chained_text()
- CLI: load_config valida dict, pipeline valida steps, config validate --plugin, process bloqueia transcription
- Loader: carrega plugins como pacote real (submodule_search_locations + sys.modules)
- Watch: estabilização de arquivo antes de processar (on_created e on_modified), output sem colisão
- Segurança: open_file() sem shell=True no Windows, clear_cache() usa cache_dir do core
- NLTK: warnings silenciados durante warm-up sem rede

**Stress tests (67 testes):**
- Cache concorrente (20 threads), config fuzzing (50 configs aleatórias), textos extremos (13 variantes)
- API sob carga (20 requests simultâneos), pipeline combos, sequências inválidas/quase-válidas
- Paridade core vs API, cache restart real, lazy loading concorrente, context+deps+cache, integração sem mock

**Mutation testing (tentativa):**
- mutmut 3.x/2.x incompatível com a estrutura do projeto (plugins/ top-level + bootstrap no import)
- Detalhes em `docs/TECHNICAL_STATE.md` seção "Mutation testing"

### ~~Hardening beta (2026-03-19/20) — reviews #3 a #7, ~30 commits~~ Concluído

Análise completa (4 agentes paralelos) + 4 code reviews Codex + fixes.

- README: Python >=3.13, status Beta v0.2.0, READMEs stale deletados
- .env.example limpo, frontend version alinhado, CORS configurável via env var
- Monitor: race conditions corrigidas (asyncio.Lock em active_streams e métricas)
- CacheManager.set() atômico (lock único cobre eviction + write + tracking)
- ConfigRegistry rejeita tipos desconhecidos
- Document stateful removido (dead code, decisão settled: Qualia é stateless)
- XSS wordcloud tooltip (.html→.text), provides valida dict vazio
- Pipeline: 404 antes de tipo, steps validados upfront (plugin_id obrigatório, config dict)
- Loader: lazy plugins sem __init__ via object.__new__()
- Upload: 500MB engine-level, streaming 64KB, tempfile preservado no timeout
- Config non-dict → 422 em analyze/transcribe/pipeline
- Último review Codex: zero achados funcionais

### ~~Code review completo #2 (2026-03-19) — 36 achados, 20 fixes~~ Concluído

Review ultrathink do projeto inteiro (core, API, CLI, frontend, plugins). 4 reviewers paralelos.

**Críticos (4):**
- [x] XSS no HTML export — `html.escape` em todas as interpolações
- [x] Cache file I/O sob lock — pickle fora do lock, forward mapping O(1), reverse index na reintegração
- [x] Loader duplicate ID check após mutação — movido para antes do store
- [x] `show_config` criava QualiaCore sem discover — usa `get_core()` singleton

**Importantes (14):**
- [x] Dead interfaces IFilter/IComposer removidas (enum, classes, imports, CLI choices)
- [x] `/analyze/file` sem `check_upload_size` — agora com limite 25MB
- [x] API examples stale deletados (plugins renomeados, endpoints inexistentes, bare excepts)
- [x] Visualize route tracking inconsistente — `validate_plugin_config` dentro do try/except
- [x] `output_format` sem validação — agora `Literal["html", "png", "svg"]`
- [x] API bind `0.0.0.0` → `127.0.0.1` (seguro para API local)
- [x] Batch `UnboundLocalError` — `output_file` inicializado antes do if
- [x] Pipeline CLI não encadeava texto entre steps — agora alinhado com API
- [x] Frontend API error `.message` undefined — normalizado com `.detail` do FastAPI
- [x] Frontend timer leak — `onDestroy` cleanup em 4 páginas
- [x] Versão `v0.1` no Layout → `v0.2.0-beta`
- [x] Sentiment viz fabricava dados — agora mostra "sem dados"
- [x] `_validate_range` sem bounds check — defensivo para range_spec malformado
- [x] `result or {}` no engine — `is not None` em vez de truthiness

**Sugestões (4):**
- [x] Unused imports removidos dos plugins
- [x] Stale migration comments removidos
- [x] Template provides comment corrigido
- [x] Engine result None check preciso

### ~~Code review completo (2026-03-19) — Onda 1: Crashes em runtime~~ Concluído

- [x] **CacheManager thread-safe** — `threading.Lock` em `get()`/`set()`/`invalidate()`/`clear()`/`stats()`. Risco de pickle documentado no docstring.
- [x] **`provides` violado — readability** — `longest_sentence`/`shortest_sentence` sempre incluídos (independente de detail_level).
- [x] **`provides` violado — sentiment** — `sentence_sentiments` default `[]` quando `analyze_sentences=false`.
- [x] **Pipeline CLI: render() args corrigidos** — Agora chama `render(data, config)` com 2 args, output_format=html, salva HTML se output_dir.
- [x] **Pipeline CLI: UTF-8 fallback** — try/except UnicodeDecodeError com fallback latin-1.
- [x] **SentimentAnalyzer NLTK thread-safe** — Download movido pro `__init__` (warm-up na main thread). `validate_config` override removido (base class cuida).
- [x] **Transcription raises exceptions** — Erros agora levantam ValueError/RuntimeError em vez de retornar dicts com status=error.
- [x] **Cache TTL bypass pós-restart** — Reintegração do disco movida para antes do check de TTL.

### ~~Code review completo (2026-03-19) — Onda 2: Contratos violados~~ Concluído

- [x] **Exit codes consistentes** — `raise SystemExit(1)` em todos os error paths de visualize, watch, inspect, export.
- [x] **pytest-timeout nas deps** — Adicionado `pytest-timeout>=2.2.0` ao extra `dev`.
- [x] **conftest.py seguro** — Removidos `cache/` e `.pytest_cache` de `_ARTIFACTS`.
- [x] **Docker healthcheck** — `urllib.request.urlopen` em vez de `requests`/`curl`.
- [x] **Pipeline API: 404** — Plugin inexistente mid-pipeline retorna 404 (era 400).
- [x] **Webhook validação** — `analyze_text` valida plugin existe e é analyzer (404/422). doc_id usa content hash.
- [x] **CORS** — Removido `allow_credentials=True` (stateless API).

### ~~Code review completo (2026-03-19) — Onda 3: Qualidade e consistência~~ Concluído

- [x] **Frontend Transcribe** — Filtra por `provides.includes('transcription')`.
- [x] **Analyze.svelte** — Default `'html'` em vez de `'png'`.
- [x] **Interactive show_config** — Usa `QualiaCore().registry` em vez de contagem manual.
- [x] **_choose_file_from_recent** — Indexação corrigida (`recent[idx-1]`).
- [x] **_kaleido_works() cache** — Resultado cacheado em `_kaleido_result` (class-level).
- [x] **import asyncio duplicado** — Removido em webhooks.py.
- [x] **Visualizer template** — Adicionado `output_format` ao meta().parameters.
- [x] **Document template** — provides mudado de `cleaned_document` para `processed_output`.
- [x] **config CLI tipos** — Suporta `bool`/`int` além de `boolean`/`integer`, e `str+options` como choice.
- [x] **Dead code formatters.py** — Removidos `Syntax` import e `format_info` function.
- [x] **Dead code workflow.js** — Removido primeiro BFS não utilizado em `wouldCreateCycle`.

### ~~Code review completo (2026-03-19) — Pendente (menor prioridade)~~ Concluído

- [x] **_validate_config extraído** — `_validate_and_convert()` helper compartilhado entre os 3 base plugins.
- [x] **Branches mortas FILTER/COMPOSER removidas** — Engine agora tem fallback `else: raise ValueError`. Tipos, interfaces e re-exports removidos completamente no code review #2.
- [x] **Dead code stateful removido** — `self.documents`, `self.pipelines`, `get_document()`, `save_pipeline()` removidos. `add_document()` cria doc efêmero.
- [x] **Plugin count >= 8 em testes** — 5 assertions atualizadas pra `>= 8`.
- [x] **CI com Python 3.13 + 3.14** — Matrix strategy com `allow-prereleases: true`.
- [x] **process.py passa context** — `ProcessRequest` agora tem campo `context`, passado ao `execute_plugin`.
- [x] **Duplicate fixtures removidas** — `client`/`sample_text` removidos de test_api.py e test_pragmatic.py (usam conftest).
- [x] **Test fixtures com Path absoluto** — `Path(__file__).parent.parent / "plugins"` em 6 test files.
- [x] **Pipeline API: valida tipo do plugin** — Steps com tipo não suportado (analyzer/document/visualizer) → 422.
- [x] **11 testes com assertions ambíguas** — Todos `assert status_code in [...]` substituídos por status code exato. Zero assertions ambíguas restantes.

### ~~Higiene de código (análise Codex — 2026-03-18)~~ Concluído

- [x] **Pipeline unificado** — CLI aceita `plugin_id` key (compat com `plugin`), usa último resultado pra visualizer (não busca `word_frequencies`). Alinhado com API.
- [x] **Arquivo .wrong sobrando** — Deletado (2026-03-19).
- [x] **print() em fallback de plugins** — Corrigido: spaCy cached no `__init__`, print→logger (2026-03-19).
- [x] **Blocos standalone em plugins** — Removidos dos 4 plugins (2026-03-19).
- [x] **Heurística eager/lazy** — `EAGER_LOAD = True` atributo explícito, fallback pra `__init__` detection (2026-03-19).
- [x] **Upload file size limit** — `check_upload_size()` em deps.py, 25MB limit, 413 em transcribe e pipeline (2026-03-19).

### ~~Compatibilidade Python 3.14~~ Concluído

- [x] **Testes async** — 37 métodos convertidos. CI matrix Python 3.13 + 3.14.

### ~~Consolidação pós-refactor~~ Concluído

- [x] **Coverage pipeline.py** — Testes de timeout step0 file+document e visualizer step (2026-03-19).
- [x] **base_plugins.py coverage** — 9 testes `_validate_and_convert`: int, float, bool (string e non-string), exclude, defaults, unknown params, invalid conversion (2026-03-19).

### ~~Pré-beta: Discovery observabilidade (C)~~ Concluído

- [x] **Severidade nos erros** — `_classify_error()` no loader: type (import_error, syntax_error, etc.) + severity (critical/warning). Campos incluídos no error dict.
- [x] **Classificação da causa** — Implementado no loader (fonte) e simplificado na CLI.
- [x] **CLI diagnóstico** — `qualia list --check` usa campos type/severity do loader.
- [x] **Endpoint `/plugins/health`** — Status individual por plugin (loaded/pending, eager/lazy), errors com severity. (2026-03-19)

### ~~Não atacar: Superfície pública documentada (D)~~ Concluído

~~Documentar quais interfaces são estáveis vs experimentais.~~ Implementado: seção Stability no TECHNICAL_STATE.md com classificação por endpoint, core API, plugin, CLI e frontend (2026-03-19).

---

## Roadmap

### Plugins (próxima fronteira)

A infra está pronta: DependencyResolver com ordenação topológica, cache LRU/TTL, loading eager/lazy, base classes thread-safe, múltiplos plugins com mesmo `provides` coexistem, extra `[ml]` disponível. Catálogo completo de candidatos em `docs/ECOSYSTEM_MAP.md`.

Cada plugin novo = criar pasta em `plugins/`, implementar `meta()` e `_analyze_impl()` (ou `_render_impl()` pra visualizers). Core descobre automaticamente. Template: `qualia create nome tipo` ou copiar de `plugins/_templates/`.

### Frontend

- Página de Workflow (pipeline builder visual) — quando plugins pesados chegarem, o Workflow é onde o pesquisador monta as transformações
- Sessões de análise (múltiplos plugins no mesmo documento, resultados acumulando)

### Novos tipos de plugin

Levantamento completo em `memory/project_plugin_types_brainstorm.md`. Checklist de criação em `memory/project_plugin_type_creation.md`.

- [ ] **Enricher** — Tipo novo. Transforma/enriquece dados estruturados sem analisar conteúdo textual. Interface: `_enrich_impl(self, data, config)`. Casos: validar CPF, normalizar telefone, detectar UF, derivar features temporais (is_weekend, hour, gap_hours). Mais simples dos 3 — começar por aqui.
- [ ] **StatAnalyzer** — Tipo novo. Recebe DataFrame/dados tabulares, roda análises quantitativas (chi-square, teste de hipótese, power analysis, correlação). Interface: `_analyze_impl(self, data: DataFrame, config, context)`. Requer evolução do core pra aceitar DataFrame como entrada (hoje é Document-centric). Análises simples que operam em resultados de outros plugins (via context) cabem no Analyzer atual sem mudanças.
- [ ] **Composer/Dashboard** — Tipo novo. Consome resultados de múltiplos analyzers + visualizers, monta visão consolidada (dashboard, relatório, PDF). Interface: `_compose_impl(self, results: Dict, config)`. Referência: `transcript-analyser-prototype/dash.pdf`. Mais complexo — depende de ter vários plugins funcionando.
- [ ] **CLI `qualia type create`** — Sistematizar criação/deleção de tipos em comando. Gera os ~8 arquivos automaticamente (interface, base class, engine elif, loader exclusion, template, rota API). Implementar quando o primeiro tipo novo for criado (validar com caso real).

**Nota:** ML não é tipo novo — é peso de dependência. Já resolvido pelo extra `[ml]` no pyproject.toml. Organização por pasta (`plugins/analyzers/ml/`).

### Ecossistema

- **qualia-coding** — evoluir PoC pra integração completa (hoje só word_frequency)
- **Consumers** — DeepVoC e Observatório consumindo Qualia via API
- **qualia-gsheets** — DataLab (sidebar Google Sheets pra preparação de dados)

---

## Parking lot

Nenhum item.

---

## Notas

### Coverage

950 testes (Python 3.13 + 3.14), ~96% coverage. 1 skip legítimo (PNG/SVG sem kaleido). Inclui 67 testes de stress (concorrência, fuzzing, textos extremos, paridade core/API, integração). 11 code reviews (3 Claude + 8 Codex), ~155 bugs corrigidos. Último review zerou.

---

## Concluído

### Sprint 2026-03-19 (limpeza, reorganização e discovery recursivo)

**Limpeza do repo:**
- [x] Root limpo: removidos artefatos (cache 903pkl, __pycache__, .coverage, output/, data/, .DS_Store)
- [x] Docs mortos movidos: configs/, DEPLOY.md, README_COMPLEMENTAR.md, KNOWN_ISSUES.md, .docx, session logs
- [x] `qualia init` simplificado — só cria plugins/ e cache/
- [x] `qualia visualize` sem -o gera em /tmp/qualia/ (não polui working directory)
- [x] Auto-cleanup de artefatos pós-teste (conftest.py pytest_sessionfinish)

**Plugin templates + CLI create:**
- [x] Templates copiáveis em `plugins/_templates/` (analyzer.py, visualizer.py, document.py)
- [x] Comando `qualia create <nome> <tipo>` — gera plugin a partir dos templates
- [x] Opção `--dir` — cria plugins em subpastas (`qualia create x analyzer --dir analyzers`)
- [x] `tools/` removido — templates e CLI são fonte única

**Discovery recursivo:**
- [x] PluginLoader.discover() com walk recursivo (rglob) — plugins em qualquer profundidade
- [x] Pastas com `_` no nome ignoradas automaticamente
- [x] Plugins organizados por tipo: analyzers/, documents/, visualizers/
- [x] 792 testes passando

### Sprint 2026-03-18 (sessão completa — coverage, refactor, ecossistema, identidade)

**Coverage gaps fechados:**
- [x] Testes de timeout 504, exception 400, encoding UTF-8/latin-1 nos endpoints
- [x] Config endpoints retornam 503 quando registry indisponível
- [x] Pipeline timeout mid-step, encadeamento não-texto
- [x] Transcribe domain error → 400
- [x] Process Document → content extraction
- [x] Health root sem frontend → API info
- [x] Engine dependency cycle + None result
- [x] Fix __main__.py quebrado + filtros de warnings

**Visualizer rendering refactor:**
- [x] BaseVisualizerPlugin._serialize() — duck-typing (plotly.Figure, matplotlib.Figure, HTML str)
- [x] Plugins renomeados: wordcloud_d3, frequency_chart_plotly, sentiment_viz_plotly
- [x] Rota /visualize simplificada (sem temp files, sem FileResponse)
- [x] Frontend default PNG → HTML
- [x] Template create_plugin.py atualizado
- [x] 13 arquivos de teste atualizados

**Ecosystem readiness:**
- [x] ECOSYSTEM_MAP.md — 5 projetos, ~30 plugins candidatos
- [x] Provides relaxado — múltiplos plugins com mesmo campo coexistem
- [x] Extra [ml] adicionado (PyTorch, transformers, sentence-transformers)

**Identidade:**
- [x] Repo renomeado qualia → qualia-core
- [x] README v3 — workbench local-first, conceito de transformação de dados
- [x] 776 testes passando

### Sprint 2026-03-18 (code review completo — 11 bugs corrigidos)

**Análise Codex (4 bugs):**
- [x] `plugins_dir` relativo ao pacote, não ao cwd (engine.py)
- [x] Pipeline encadeia `current_text` entre steps (pipeline.py)
- [x] Validação de config centralizada em todas as rotas (deps.py → `validate_plugin_config()`)
- [x] Checagem de tipo de plugin por rota (deps.py → `require_plugin_type()`)

**Code review interno (7 bugs):**
- [x] Interfaces alinhadas: IDocumentPlugin.process e IVisualizerPlugin.render (interfaces.py)
- [x] FileResponse temp file leak corrigido via BackgroundTask (visualize.py)
- [x] Timeout 60s em todos os paths do pipeline (pipeline.py)
- [x] DependencyResolver ValueError tratado no execute_plugin (engine.py)
- [x] Type conversion em BaseAnalyzerPlugin e BaseDocumentPlugin (base_plugins.py)
- [x] ConfigRegistry warning para tipo desconhecido (config.py)
- [x] Test always-passing corrigido (test_pragmatic.py)
- [x] 772 testes passando

### Sprint 2026-03-17 (saneamento)

- [x] Dividir `api/__init__.py` (694→111 linhas) em deps, schemas, routes/
- [x] Quebrar `core/__init__.py` (902→47 linhas) em 7 módulos
- [x] Integrar DependencyResolver no execute_plugin (field-name→plugin-id, detecção de ciclos)
- [x] Limpar dívidas técnicas (validate_config consistente, wizard stubs, TODOs)
- [x] Pipeline fail-fast com RuntimeError descritivo
- [x] Coverage de 42% → 90% (237→726 testes, todos módulos de produção acima de 90%)
- [x] Remover código morto (run_api.py, módulos vazios, protection morta)
- [x] Migrar setup.py → pyproject.toml
- [x] Organizar docs (mortos → docs/morto/)
- [x] CI com coverage no GitHub Actions
- [x] Dockerfile + docker-compose limpos
- [x] Makefile corrigido
- [x] Instalar pytest-timeout
- [x] Renomear venv → .venv
- [x] Eliminar requirements.txt (pyproject.toml fonte única)
- [x] Deletar nginx.conf corrompido + service nginx
- [x] Limpar root: mover ops/, scripts/, demos/, examples/, notebooks/ → docs/morto/

---

## Referência: Document stateful

O design original (jun/2025) era inspirado no spaCy — Document como hub central que acumula análises. Na prática, o Qualia é stateless (cada request cria Document efêmero, executa, descarta).

**Dead code confirmado:**
- `get_document()` — 0 chamadas em produção
- `get_analysis()` — 0 chamadas
- `add_variant()` / `get_variant()` — 0 chamadas
- `self.documents` dict — só cresce, nunca limpo
- `self.pipelines` / `save_pipeline()` — nunca usado

**Cenários futuros onde faria sentido:**
- Sessões de análise interativa no frontend
- Pipeline stateful (plugin B lê resultado do plugin A via doc)
- Consumers stateful (DeepVoC, Observatório)

**Hoje já coberto por:** CacheManager (resultados por doc_id+plugin_id+config) e DependencyResolver (deps automáticas).

**Arquivos envolvidos (não deletar sem decisão):**
- `qualia/core/models.py` — Document class (`_analyses`, `_variants`, `_cache`)
- `qualia/core/engine.py` — `self.documents`, `add_document()`, `get_document()`, `self.pipelines`, `save_pipeline()`
