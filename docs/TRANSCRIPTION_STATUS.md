# Status da transcrição estruturada

Atualizado em 15/10/2026. Referência atual: **v9 — implementação local concluída; duas entrevistas novas processadas integralmente por upload/API, com validação estrutural e downloads aprovados**. A comparação da entrevista maior revelou pontos de qualidade textual e de participante ainda sem confirmação no áudio. O código permanece no commit `671df37`; áudios, referências Dovetail e rodadas privadas permanecem fora do Git. Não foi publicada uma release.

## Começar por aqui ao retomar

Este é o ponto de entrada da frente de transcrição. Ler este status, o [contrato técnico](TRANSCRIPTION_BENCHMARK.md) e, no checkout com os dados, `local-transcript-benchmark/CONTINUIDADE-2026-10-15.md` e `EXECUTION-STATUS.json`. O último pedido do usuário foi **fechar o contexto e fazer commit, sem continuar ajustando ou testando**. A integração está entregue; a qualidade global não foi estabelecida por um critério de aceite acordado. Não reabrir ensaios, modificar modelos ou pedir outra conferência humana automaticamente.

O usuário está cansado da sequência de iterações e delegou a condução técnica. Quer um fluxo simples de enviar o áudio e baixar os arquivos, com todo texto vinculado a participante. Um editor, um formulário obrigatório ou uma troca visual do rótulo “Sem falante” não atendem ao problema de atribuição. Revisões anteriores já confirmadas devem ser preservadas, sem pedir que ele ouça novamente os mesmos trechos.

## Último retorno: limite da comparação apresentada

O usuário abriu o relatório e considerou difícil comparar os resultados porque os tempos e recortes do Qualia e do Dovetail não coincidem. Percebeu que a apresentação se orientava pelos timestamps e disse faltar um parâmetro claro para julgar a qualidade. Considerou o resultado promissor, mas pediu encerrar esta etapa em vez de mexer novamente na comparação.

Precisão do registro: o cálculo lexical e a equivalência de participantes já usam conteúdo/sequência de palavras, não igualdade de timestamps. Porém, a apresentação mantém limites próprios dos CSVs, blocos de contexto diferentes e botões de escuta ancorados no resultado gerado. Quando há omissão, redação diferente ou correspondência ambígua, isso pode produzir comparações pouco claras. Não desconsiderar a objeção do usuário só porque o algoritmo não usa matching temporal.

**Os 6,7%/17,9% e as contagens de rótulos divergentes são resultados exploratórios, não uma nota de qualidade validada ou de superioridade frente ao Dovetail.** Não houve escuta integral nem critérios de precisão de texto/falante acordados. Se essa frente for reaberta, a primeira decisão é definir unidades de comparação por fala/conteúdo, contexto auditivo comum e critérios de aceite que tornem a avaliação útil. A comparação atual foi preservada, sem alteração nesta entrega de documentação.

## O que já funciona

Na tela **Transcribe → Local Transcription — speakers & exports**, o usuário envia um áudio e recebe texto com participantes, timestamps e downloads CSV/VTT/TXT, além do JSON de auditoria. O TXT reúne falas consecutivas da mesma voz em blocos. Participantes são estimados automaticamente; não há número fixo de dois, nem identificação nominal de pessoas. A geração não exige uma etapa de revisão humana.

O fluxo está integrado ao plugin, API e interface. A implementação usa large-v3 e Community-1 no ambiente principal, com alinhamento WhisperX no ambiente separado `.venv-align`. Dovetail é usado exclusivamente para comparar resultados depois da geração.

## O que mudou

1. **Reconhecimento:** instância nova por áudio e contexto textual entre segmentos desativado. Isso eliminou as séries extensas de repetição nos três áudios testados, sem deduplicar ou substituir texto por uma referência. Não constitui prova de ausência de repetição em qualquer gravação.
2. **Estrutura e entrega:** alinhamento por palavra, associação a participantes e exportação CSV/VTT/TXT/JSON. Adicionados o coordenador retomável e o adaptador de plugin/API/interface.
3. **Falantes:** preenchimento automático de lacunas; verificação acústica de turnos curtos em CPU; revisão por continuidade de segmentos parcialmente detectados em torno de ilhas de voz muito curtas. Cada decisão conserva origem e evidência. Inferência por contexto não é confirmação acústica.
4. **Última alteração, v9:** duas palavras da terceira gravação passaram de P3 para P2, conforme a confirmação humana. Primeira, segunda, demais atribuições e saudações ficaram iguais. A regra considera evidência temporal geral, sem frases, timestamps ou entrevistas codificados.

As alterações se concentram no caminho de transcrição: plugin local, novo plugin estruturado, módulos de transcrição, scripts de execução/validação, tela de transcrição, testes e documentação. O worktree também contém alterações anteriores e arquivos de outros trabalhos; não atribuir todo o `git status` a esta implementação. Modelos e ambientes existentes foram preservados durante a última correção.

## O que foi comprovado

| Verificação | Evidência atual |
|---|---|
| Três gravações existentes | 9.519 palavras; contagem automática 2/2/3; nenhum trecho sem participante |
| Integridade na v9 | Texto e tempos preservados em relação à v8 |
| Regressão de falantes | Quatro revisões acústicas anteriores e 16 palavras de alvos anteriormente confirmados preservados |
| Testes Python selecionados | 156 passaram; quatro testes legados de descoberta ampla não foram executados |
| Tela e arquivos da v9 | Navegador real verificou os três resultados e os quatro downloads de cada um |
| Reexportação v9 dos três originais | Somente exportação/validação; modelos de reconhecimento, vozes e alinhamento reutilizados por hash |
| Upload completo anterior à v9 | Uma gravação de 23 minutos; 556,441 segundos naquele teste |
| Últimas execuções, com políticas finais v9 | Dois novos uploads completos, seis etapas por áudio, sem reutilização de resultados |

O teste real anterior comprova o caminho daquela versão. A validação independente da v9 foi concluída com dois uploads reais, sem reutilização de resultados, atravessando as seis etapas atuais e preservando intermediários. O adaptador original foi executado com um hook de teste que apenas copiava seus arquivos temporários antes da limpeza; o hook foi retirado após o teste. Não usar diferenças contra o Dovetail como taxa de erro contra o áudio.

| Entrevista nova | Áudio | Processamento com pausas | Palavras | Participantes | Divergência textual relativa ao Dovetail |
|---|---:|---:|---:|---:|---:|
| terceirooo.m4a | 9min26s | 4min54s | 1.056 | 2 | 6,7% |
| quartooo.m4a | 32min31s | 12min49s | 3.705 | 2 | 17,9% |

Nas duas: zero trechos sem participante, zero sinais dos detectores de repetição extensa, CSV/VTT/TXT/JSON e downloads reais aprovados. Uma palavra da entrevista curta não recebeu tempo individual; permaneceu no texto e usou o intervalo nativo no VTT, com auditoria. Na comparação por conteúdo e equivalência individual dos rótulos, 12 e 81 palavras respectivamente divergiram de participante em relação ao Dovetail; isso não confirma quem está correto. Não houve corte das bordas de nenhum dos dois áudios, embora a opção estivesse ligada.

A entrevista maior tem diferenças candidatas a escuta localizada: em torno de 14 minutos há texto pouco coerente no Qualia e ausência de texto correspondente em boa parte da referência; perto de 17 minutos há uma conversa sobre problemas de conexão que aparece só no Qualia nesse bloco. A resposta “Eu sou supervisor administrativo da equipe de regulação”, perto de 46 segundos, tem participante diferente entre os sistemas. Esses pontos foram localizados automaticamente e lidos pelo agente, sem confirmação auditiva conclusiva; as diferenças de recorte da apresentação também precisam ser consideradas. Não foram corrigidos nem usados para ajustar regras ao teste. Evidência em `local-transcript-benchmark/runs/2026-10-15-new-interviews-v1/`.

## Histórico necessário para entender a referência

| Rodada | O que explica o estado atual |
|---|---|
| v1/v2 | Repetição extensa já no ASR contínuo; não era um defeito criado pelo alinhamento/exportação. v2 não demonstrou melhora de atribuição. |
| Ensaios do decoder/v3 | Controles de contexto textual, callback e janelas independentes. Política mantida: large-v3, instância nova por áudio, `no_context=true`, `n_max_text_ctx=0`. Séries extensas deixaram de ocorrer nas amostras testadas. |
| v4 | Experimento de limites externos de fala removeu repetição residual no encerramento; uma fala curta também se perdeu. Opção permanece experimental e desligada por padrão. |
| v5/v6 | Recuperação de lacunas e revisão de ilhas de falante. Retornos humanos localizaram erros pequenos dentro da mesma frase; evidências e correções confirmadas foram preservadas. |
| v7 | Completude de rótulos passou a ser automática. Demonstrou cobertura, sem provar que todas as identidades estavam certas. Proposta de editor obrigatório foi retirada. |
| v8 | Comparação acústica direta de turnos e contexto nativo em CPU. Quatro turnos/dez palavras revistos nos três áudios, incluindo “Tá bom” em P2. |
| v9 | Regra geral de continuidade para segmento parcialmente detectado corrigiu duas palavras adicionais em P2. Implementação preservada no commit `671df37`. |
| Duas entrevistas novas | Upload/inferência/download atuais aprovados; resultados com dois participantes em cada áudio, sem campos vazios ou sinais de repetição extensa. Comparação exploratória revelou diferenças e foi considerada difícil de conferir pelo usuário. |

## Configuração de referência

As três saídas v9 aprovadas foram geradas com **português, MPS, large-v3, limites externos de fala ligados e revisão experimental de lacunas/trocas de falante ligada**. Na interface, são os dois interruptores experimentais. Pela API: `speech_boundaries=true` e `recover_speakers=true`; no CLI: `--speech-boundaries --refine-speakers`.

Essas duas opções permanecem **desligadas por padrão**. Portanto, um upload com parâmetros padrão não reproduz exatamente a configuração da rodada aprovada. Não promovemos automaticamente opções experimentais nem mudamos esses parâmetros neste registro de status. O limite externo de fala pode perder encerramentos baixos ou muito curtos; essa limitação já foi documentada.

Verificação acústica, preenchimento completo e continuidade de ilhas muito curtas são automáticos por padrão nas novas execuções estruturadas. O JSON guarda parâmetros e versões para distinguir cada execução.

## Limites e próximo passo

A v9 é a referência para os próximos testes. Vozes sobrepostas, respostas muito curtas, ruído, nomes e siglas ainda podem produzir erros de texto ou participante. A separação das saudações revisadas foi aceita; a identidade de todas as vozes desse trecho não foi confirmada e ficou fora da prioridade definida pelo usuário. O texto da última passagem questionada não foi reescrito sem confirmação do que foi dito.

As duas entrevistas novas já foram processadas e comparadas em pastas separadas. **Não há próxima execução autorizada.** Uma retomada de qualidade deve começar pela discussão dos critérios de avaliação e da correspondência de conteúdo apresentada ao usuário, antes de solicitar novas escutas ou rodar outro modelo. A integração final está validada; não há revisão auditiva integral nem garantia de precisão de todos os participantes/textos. Alterar a referência somente com evidência de defeito ou regressão e preservar os resultados anteriores.

As duas execuções autorizadas terminaram e os modelos encerraram. Execução pesada adicional depende de nova liberação da máquina pelo usuário. API e interface são locais; jobs de prévia têm TTL, e os arquivos permanentes da rodada ficam no benchmark privado.

Fontes locais: `local-transcript-benchmark/runs/2026-10-15-v9-microturn-continuity/README.md`, `final-verification.json`, `verification.json`, `python-tests.log`, `preview-jobs.json` e os manifestos/resultados por gravação. O teste integral anterior está em `runs/2026-10-15-api-real-v1/final-verification.json`. O benchmark está excluído do Git; o contrato técnico permanece em [TRANSCRIPTION_BENCHMARK.md](TRANSCRIPTION_BENCHMARK.md).

## Links e arquivos de continuidade

- [Relatório das entrevistas novas com players](http://127.0.0.1:8000/speaker-review-v6/new-interviews-v1/index.html).
- [Resultado da entrevista de 9min26s](http://127.0.0.1:5173/?job=1d9b0027-10ae-4301-832c-407112c31c6f#/transcribe/transcription_structured).
- [Resultado da entrevista de 32min31s](http://127.0.0.1:5173/?job=0e5f86b8-03af-455d-8072-4d0d6b016a63#/transcribe/transcription_structured).
- Pasta permanente: `local-transcript-benchmark/runs/2026-10-15-new-interviews-v1/`. Contém `index.html`, `README.md`, `final-verification.json`, `comparison-summary.json`, `text-comparison/`, `speaker-content-comparison/` e as pastas `new-terceiro/` e `new-quarto/` com os intermediários/exports.
- Configuração congelada anterior aos testes: `local-transcript-benchmark/STATUS-ATUAL-v9.json`. Seu campo de validação pendente descreve aquele instante; consultar `EXECUTION-STATUS.json` para o estado mais recente.
- Índice privado para a próxima sessão: `local-transcript-benchmark/CONTINUIDADE-2026-10-15.md`. A pasta é excluída via `.git/info/exclude`; um clone do repositório não traz os áudios, ambientes, modelos, relatórios ou esse índice privado.

Os links HTTP exigem os servidores locais ativos. Jobs podem expirar pelo TTL; isso não apaga os exports permanentes. O relatório estático com players independe do job para mostrar suas comparações. O launcher local usado ao encerrar é `local-transcript-benchmark/serve-preview-new-interviews-v1.py`; ele restaura jobs salvos com seus timestamps originais e não renova o TTL. Caso expirem, republicar os resultados concluídos a partir dos arquivos, com novos jobs/links, sem inferência. Não enviar os áudios novamente só para abrir um resultado.
