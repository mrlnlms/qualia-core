# Qualia Core

Workbench de análise local-first, extensível por plugins. Recebe texto, áudio ou vídeo via API REST, devolve JSON. Cada análise é um plugin independente e configurável — sentimento, frequência, clustering, transcrição, visualização.

Plugin é qualquer biblioteca de análise adicionada ao engine. Existem três tipos:

- **Documents** recebem texto e devolvem texto transformado — limpeza de transcrições, parsing de chat, normalização. Libs comuns: regex, BeautifulSoup, spaCy
- **Analyzers** recebem texto e devolvem dados — frequência de palavras, sentimento, clustering, topic modeling, testes estatísticos. Libs comuns: NLTK, TextBlob, scikit-learn, sentence-transformers, scipy
- **Visualizers** recebem dados e devolvem gráficos — barras, dashboards, redes, dendrogramas, heatmaps. Libs comuns: plotly, matplotlib, D3.js

O engine descobre plugins automaticamente — adicionar é criar uma pasta, remover é deletar. O projeto já vem com 8 plugins instalados (ver tabela abaixo). Não usa algum? Deleta a pasta e pronto.

## Por que

As mesmas análises aparecem em todo projeto de pesquisa, mas sempre reimplementadas do zero. Qualia centraliza: instala o plugin uma vez, qualquer projeto consome via API. Os dados não saem da máquina.

O trabalho do pesquisador é, no fundo, transformar dados — texto vira código, código vira frequência, frequência vira cluster, cluster vira perfil narrativo. Cada passo é uma decisão interpretativa. Qualia torna essas transformações explícitas, configuráveis e reutilizáveis.

Cada plugin declara seus parâmetros e o engine expõe automaticamente — na API, na CLI e no frontend. Quem consome escolhe: quantos clusters, qual modelo, qual threshold. Não é uma caixa preta — é uma ferramenta configurável que o pesquisador adapta pro seu contexto.

## Plugins

| Plugin | Tipo | O que faz |
|--------|------|-----------|
| `word_frequency` | Analyzer | Frequência de palavras, stopwords, termos principais |
| `sentiment_analyzer` | Analyzer | Sentimento do texto (positivo/negativo/neutro) via TextBlob |
| `readability_analyzer` | Analyzer | Legibilidade (score 0-100, nível de dificuldade) |
| `teams_cleaner` | Document | Limpa transcrições do Teams/Zoom (timestamps, speakers) |
| `transcription` | Document | Transcreve áudio/vídeo via Groq Whisper (mp3, mp4, opus, wav) |
| `wordcloud_d3` | Visualizer | Nuvem de palavras interativa (D3.js) |
| `frequency_chart_plotly` | Visualizer | Gráficos de frequência (bar, line, area) com Plotly |
| `sentiment_viz_plotly` | Visualizer | Dashboard, gauge, timeline e distribuição de sentimento |

Novos plugins são descobertos automaticamente — basta criar uma pasta em `plugins/` com um `__init__.py`.

Múltiplos plugins podem fazer o mesmo tipo de análise (ex: dois sentiment analyzers com abordagens diferentes). O consumer escolhe qual usar.

## Quick Start

Python 3.13+. Tudo roda local — sem conta, sem cloud.

```bash
git clone https://github.com/mrlnlms/qualia-core.git
cd qualia && python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
python -m uvicorn qualia.api:app --port 8000
```

Swagger em http://localhost:8000/docs — interface onde você testa todos os endpoints pelo navegador.

**Analisar texto:**
```bash
curl -X POST http://localhost:8000/analyze/word_frequency \
  -H "Content-Type: application/json" \
  -d '{"text": "seu texto aqui", "config": {}}'
```

**Transcrever áudio/vídeo:**
```bash
curl -X POST http://localhost:8000/transcribe/transcription \
  -F "file=@audio.mp4" \
  -F 'config={"language": "pt"}'
```

**Endpoints principais:**
- `GET /plugins` — lista plugins disponíveis
- `POST /analyze/{plugin_id}` — executa análise em texto
- `POST /process/{plugin_id}` — processa documento
- `POST /transcribe/{plugin_id}` — transcreve áudio/vídeo
- `POST /visualize/{plugin_id}` — gera visualização
- `POST /pipeline` — executa sequência de plugins
- `GET /config/consolidated` — schemas de todos os plugins (para consumers)

## CLI

```bash
qualia list                                          # plugins disponíveis
qualia analyze texto.txt -p word_frequency           # analisar texto
qualia analyze texto.txt -p sentiment_analyzer -P language=pt  # com parâmetros
qualia process transcricao.txt -p teams_cleaner      # processar documento
qualia visualize resultado.json -p frequency_chart_plotly  # gerar visualização
qualia menu                                          # menu interativo (navegação por setas)
```

## Crie seu próprio plugin

Gerar a estrutura:

```bash
qualia create meu_analyzer analyzer
```

Cria `plugins/meu_analyzer/__init__.py` com a estrutura completa — procure por `TODO` no código gerado. Tipos disponíveis: `analyzer`, `visualizer`, `document`. Ou copie manualmente de `plugins/_templates/`.

O plugin mínimo:

```python
from qualia.core import BaseAnalyzerPlugin, PluginMetadata, PluginType, Document

class MeuAnalyzer(BaseAnalyzerPlugin):
    def meta(self):
        return PluginMetadata(
            id="meu_analyzer",
            name="Meu Analyzer",
            type=PluginType.ANALYZER,
            version="1.0.0",
            description="Detecta padrões no texto",
            provides=["patterns"],
            requires=[],
            parameters={
                "threshold": {"type": "float", "default": 0.5, "description": "Limiar de detecção"},
                "language": {"type": "str", "default": "pt", "options": ["pt", "en", "es"]},
            },
        )

    def _analyze_impl(self, document, config, context):
        text = document.content
        threshold = config["threshold"]
        # sua lógica aqui
        return {"patterns": [...]}
```

Os parâmetros declarados em `parameters` aparecem automaticamente:
- Na **API**: `GET /config/consolidated` retorna o schema completo. `POST /analyze/meu_analyzer` valida o config contra o schema
- Na **CLI**: `qualia analyze texto.txt -p meu_analyzer -P threshold=0.8`
- No **frontend**: formulário dinâmico gerado a partir do schema — dropdowns pra options, sliders pra ranges

Três tipos de plugin: `BaseAnalyzerPlugin` (texto → dados), `BaseDocumentPlugin` (texto → texto limpo), `BaseVisualizerPlugin` (dados → figura). Visualizers retornam o objeto de figura (plotly.Figure, matplotlib.Figure ou HTML) — o BaseClass serializa pro formato que o consumer pediu.

Se o plugin usa modelos pesados (transformers, spaCy), carregue no `__init__` — o método de análise roda em worker threads.

## Instale só o que precisa

```bash
pip install -e "."                # core mínimo
pip install -e ".[api]"           # + FastAPI, uvicorn
pip install -e ".[nlp]"           # + TextBlob, NLTK, langdetect
pip install -e ".[ml]"            # + PyTorch, transformers, sentence-transformers, scikit-learn, umap-learn
pip install -e ".[viz]"           # + plotly, matplotlib, kaleido
pip install -e ".[transcription]" # + Groq Whisper (requer GROQ_API_KEY no .env — chave gratuita em console.groq.com)
pip install -e ".[all]"           # tudo acima
```

## Arquitetura

```
plugins/  →  core (discovery, deps, cache)  →  API REST  →  consumers
                                               CLI
                                               frontend
```

O core é agnóstico de propósito — descobre plugins, resolve dependências entre eles (ordenação topológica), gerencia cache, e executa. Ele não sabe o que é sentimento, frequência ou transcrição. Toda a inteligência fica nos plugins.

Consumers (scripts, notebooks, plugins do Obsidian, frontend web) escolhem quais plugins rodar e interpretam os resultados. O Qualia processa — quem dá significado é quem consome.

## Stack

- **Core:** Python 3.13+
- **API:** FastAPI, Uvicorn, Pydantic
- **CLI:** Click, Rich
- **NLP:** TextBlob, NLTK, langdetect
- **ML:** PyTorch, transformers, sentence-transformers (extra `[ml]`)
- **Visualização:** Plotly, D3.js, Matplotlib
- **Transcrição:** Groq Whisper API
- **Frontend:** Svelte 5, Vite
- **Infra:** Docker, SSE para monitoramento, GitHub Actions CI

## Ecossistema Qualia

Qualia Core é o motor. Outros projetos consomem a API:

- **[qualia-coding](https://github.com/mrlnlms/qualia-coding)** — plugin Obsidian pra codificação qualitativa cross-media

## Status

API REST + CLI + frontend web (Svelte, dark theme). CI via GitHub Actions com coverage.

**Estágio atual:** Beta (v0.2.0-beta), com API + CLI + frontend. A visão atual,
as evidências de validação e as pendências estão em
[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md). Agentes devem começar por
[AGENTS.md](AGENTS.md).

MIT
