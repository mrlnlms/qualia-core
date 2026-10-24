# Qualia Core — visão atual e retomada

Atualizado em **24/10/2026**, após revisão de código, documentação, Git e CI.
Referência funcional examinada: `16a48b2`. Este documento registra a visão geral
do projeto para um agente que começa sem contexto da conversa.

## Leitura inicial e precedência

1. Este documento: situação das frentes e pendências observadas.
2. [CLAUDE.md](../CLAUDE.md): comandos, convenções e decisões arquiteturais.
3. Código, testes e estado atual do Git/CI: confirmar antes de executar trabalho.
4. Para transcrição: [status específico](TRANSCRIPTION_STATUS.md), depois
   [contrato técnico](TRANSCRIPTION_BENCHMARK.md).

O [backlog](BACKLOG.md), o [estado técnico](TECHNICAL_STATE.md) e o
[mapa do ecossistema](ECOSYSTEM_MAP.md) preservam contexto importante de março.
Suas contagens, descrições de implementação e propostas não devem ser assumidas
como atuais. Código existente e encerramentos explícitos prevalecem sobre
checkboxes e planos históricos. Em caso de divergência, conferir a evidência
específica; não reabrir uma frente apenas porque um documento antigo a lista.

## Visão do projeto

O Qualia está numa fase de consolidação. É um motor local de análise por plugins,
com API REST, CLI e interface Svelte. A base de execução já tem discovery,
validação de configuração, dependências, cache e jobs assíncronos. O próximo
trabalho precisa consolidar integração, uso e reprodução em outros ambientes.

| Frente | Estado observado | Atividade que faz sentido |
| --- | --- | --- |
| Motor, API e plugins | Implementados; dez plugins concretos no código | Manutenção orientada por problemas demonstrados |
| Jobs assíncronos | Fila, concorrência, SSE, expiração e cancelamento de pendentes implementados | Conferir integração com os fluxos da interface |
| Transcrição estruturada | Upload, transcrição, participantes e downloads demonstrados | Avaliação de qualidade somente após definir critérios e retomar explicitamente a frente |
| Workflow e sessões | Construtor visual existente; sessões persistentes seguem como proposta | Consolidar execução, resultados e recuperação de trabalho |
| Instalação/distribuição | Transcrição estruturada depende do checkout e de dois ambientes preparados | Tornar a preparação reproduzível em outra máquina |
| Expansão de plugins/ecossistema | Catálogo de possibilidades documentado | Escolher um caso de uso antes de ampliar arquitetura |

Os dez plugins são: `word_frequency`, `sentiment_analyzer`,
`readability_analyzer`, `teams_cleaner`, `transcription`, `transcription_local`,
`transcription_structured`, `wordcloud_d3`, `frequency_chart_plotly` e
`sentiment_viz_plotly`. Contagem por implementações no código, não comprovação
de disponibilidade de todas as dependências em qualquer instalação.

## Pendências observadas em 24/10/2026

### 1. Saúde da versão publicada: CI com falha

O [run 40103065546](https://github.com/mrlnlms/qualia-core/actions/runs/40103065546),
do commit `16a48b2`, falhou em Python 3.13 e 3.14. O run anterior da `main`,
em `2e92de9`, passou.

Os logs registram falhas em pelo menos dois testes com expectativas anteriores
à chegada de `transcription_structured`:

- `tests/test_core.py::TestQualiaCore::test_plugin_discovery`: espera um conjunto
  de nove plugins que não inclui o novo plugin estruturado.
- `tests/test_plugin_heavy_field.py::TestPluginInfoHeavy::test_plugin_info_includes_heavy`:
  considera apenas `transcription_local` como pesado, mas o estruturado também
  declara `heavy=True`.

Atividade sugerida: investigar essas expectativas, corrigir o contrato dos testes
conforme o comportamento pretendido e conferir a suíte completa/CI. Não foi
afirmado que esses sejam os únicos problemas. Nenhuma correção foi feita na revisão.

### 2. Integração Workflow/Pipeline com os jobs

Evidência estática:

- `qualia/frontend/src/lib/api.js`: `executePipeline()` usa `request('/pipeline')`
  diretamente; não acompanha o job com `executeWithJobSupport()`.
- `qualia/api/routes/pipeline.py`: pode responder HTTP 202 com `job_id` e URLs
  de acompanhamento; pipeline é assíncrono por padrão no caminho correspondente.
- `qualia/frontend/src/pages/Workflow.svelte`: espera `result.results` e marca
  os nós restantes como concluídos ao retornar a chamada.
- `qualia/frontend/src/pages/Pipeline.svelte` usa o mesmo cliente de pipeline.

Isso indica risco de sinalizar conclusão sem receber os resultados finais.
Ainda precisa ser reproduzido no navegador; não foi declarado um teste de UI
real nesta revisão. A transcrição já usa o acompanhamento de jobs, então não
generalizar essa lacuna para todos os fluxos assíncronos.

### 3. Documentação e mapa de atividades desatualizados

- README e estado técnico ainda descrevem oito plugins e contagens antigas de testes.
- O roadmap lista criação do Workflow, mas `Workflow.svelte`, componentes e lógica
  do grafo já existem. A atividade atual é consolidar o fluxo, não recriá-lo.
- As propostas de Enricher, StatAnalyzer e Composer conflitam com a decisão
  vigente de manter três tipos de plugin em `CLAUDE.md`. São ideias históricas,
  não autorização para alterar a arquitetura.
- As migrações de DeepVoC, Observatório, whats-le e transcript-analyser são
  possibilidades documentadas. A revisão não auditou esses outros repositórios
  nem comprovou a situação atual de suas integrações.

Atividade sugerida: reconciliar as fontes e distinguir entregue, pendente,
proposta e encerrado. Este status é o ponto de entrada; não reescreve todo o histórico.

### 4. Preparação reproduzível da transcrição estruturada

O [README do plugin](../plugins/documents/transcription_structured/README.md)
explicita que ele requer o checkout com scripts, ffmpeg, modelos e dois ambientes.
`qualia/transcription/service.py` seleciona `.venv/bin/python` e
`local-transcript-benchmark/.venv-align/bin/python`.

O código publicado não inclui os ambientes nem os modelos. Instalar somente o
wheel não reproduz esse adaptador. Tornar a instalação reproduzível é uma frente
distinta de melhorar o algoritmo; não exige publicar o benchmark privado.

## Transcrição: entregue e encerrada no limite documentado

A referência funcional é v9, implementada em `671df37` e documentada em `0781bc9`.
Duas entrevistas novas passaram por upload/API, etapas completas, validação
estrutural e downloads. Isso demonstra integração; não estabelece precisão global
de texto ou de identificação de participantes.

A comparação com Dovetail foi considerada difícil de julgar pelas diferenças de
recortes/tempos. As divergências lexicais não são acurácia contra o áudio.
Uma retomada deve começar por critérios de aceite e unidades de comparação,
preservando as revisões já confirmadas. Não iniciar inferência, trocar modelos,
retomar escutas ou promover opções experimentais automaticamente.

Detalhes e configuração efetivamente testada estão no status específico. Um
upload com parâmetros padrão não equivale automaticamente à configuração das
rodadas aprovadas. A execução pesada depende de nova liberação da máquina.

## Ordem sugerida e escopo autorizado

Ordem técnica sugerida na revisão: **CI → integração Workflow/jobs → documentação
e instalação reproduzível → próxima funcionalidade escolhida por uso real**.

Essa ordem é uma recomendação, não um plano de implementação aprovado. O pedido
atual foi preservar a visão e facilitar a retomada por outro agente. Não foram
autorizadas correções funcionais ou novas rodadas de modelos por este registro.

## Git, privacidade e validação

Em 24/10/2026, os commits locais foram publicados e a branch de transcrição foi
integrada por fast-forward na `main`, até `16a48b2`. O worktree ficou limpo;
nenhum commit de branches locais ficou ausente das refs remotas. Revalidar isso
na próxima sessão, pois branches e commits mudam.

Ficam fora do Git: benchmark, áudios, referências e revisões Dovetail, resultados
por entrevista, ambientes, modelos, `.env`, configurações locais e rascunhos
aposentados. As exclusões relevantes estão no `.gitignore`. Não usar `git add -f`
para incluir dados privados ou restaurar materiais aposentados sem pedido.

Validações recentes, sem equivaler a uma suíte completa aprovada:

- Bloco assíncrono em `2e92de9`: 224 testes Python selecionados passaram.
- Transcrição em `16a48b2`: 158 testes Python passaram, dois foram excluídos;
  nove testes Node passaram.
- CI completo de `16a48b2`: falhou, conforme a pendência acima.
- Revisão das atividades: leitura de código/docs/logs; nenhuma nova inferência
  ou reprodução visual de Workflow/Pipeline.

No checkout com dados, a continuidade privada está em
`local-transcript-benchmark/CONTINUIDADE-2026-10-15.md` e `EXECUTION-STATUS.json`.
Esses registros preservam contexto de outubro e podem conter descrições antigas
do Git. Um clone limpo não os recebe; a visão geral deste documento é independente
desses arquivos privados e da memória pessoal do agente.
