# Status da transcrição estruturada

Atualizado em 15/10/2026. Referência atual: **v9 — implementação local concluída e validada nos três áudios existentes; pronta para validação em entrevistas novas**. Esse nome identifica a rodada de trabalho. O código, os testes e a documentação são preservados em um commit local de referência; áudios, referências Dovetail e rodadas privadas permanecem fora do Git. Não foi publicada uma release.

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
| Última execução | Somente exportação/validação; modelos de reconhecimento, vozes e alinhamento reutilizados por hash |
| Upload real com inferência completa | Realizado antes das revisões finais, em uma gravação de 23 minutos; 556,441 segundos naquele teste |

O teste real anterior comprova o caminho de upload/API/inferência/download daquela versão. A v9 foi exercitada com os intermediários existentes e testes de integração; **ainda não houve uma nova transcrição integral por upload com todas as políticas atuais**. As duas entrevistas novas poderão fornecer essa validação independente. Não usar diferenças contra o Dovetail como taxa de erro contra o áudio.

## Configuração de referência

As três saídas v9 aprovadas foram geradas com **português, MPS, large-v3, limites externos de fala ligados e revisão experimental de lacunas/trocas de falante ligada**. Na interface, são os dois interruptores experimentais. Pela API: `speech_boundaries=true` e `recover_speakers=true`; no CLI: `--speech-boundaries --refine-speakers`.

Essas duas opções permanecem **desligadas por padrão**. Portanto, um upload com parâmetros padrão não reproduz exatamente a configuração da rodada aprovada. Não promovemos automaticamente opções experimentais nem mudamos esses parâmetros neste registro de status. O limite externo de fala pode perder encerramentos baixos ou muito curtos; essa limitação já foi documentada.

Verificação acústica, preenchimento completo e continuidade de ilhas muito curtas são automáticos por padrão nas novas execuções estruturadas. O JSON guarda parâmetros e versões para distinguir cada execução.

## Limites e próximo passo

A v9 é a referência para os próximos testes. Vozes sobrepostas, respostas muito curtas, ruído, nomes e siglas ainda podem produzir erros de texto ou participante. A separação das saudações revisadas foi aceita; a identidade de todas as vozes desse trecho não foi confirmada e ficou fora da prioridade definida pelo usuário. O texto da última passagem questionada não foi reescrito sem confirmação do que foi dito.

O próximo passo é processar as duas entrevistas novas em pastas separadas, usando uma configuração registrada, sem reaproveitar transcrições dessas entrevistas nem usar Dovetail como entrada. Depois, comparar conteúdo e organização por participante com os CSVs originais do Dovetail. Alterar a referência somente se houver evidência de defeito ou regressão; preservar a v9 e os dados anteriores.

Nenhuma entrevista nova foi iniciada neste fechamento. Execução pesada continua dependendo da liberação da máquina pelo usuário. API e interface são locais; jobs de prévia têm TTL, e os arquivos permanentes da rodada ficam no benchmark privado.

Fontes locais: `local-transcript-benchmark/runs/2026-10-15-v9-microturn-continuity/README.md`, `final-verification.json`, `verification.json`, `python-tests.log`, `preview-jobs.json` e os manifestos/resultados por gravação. O teste integral anterior está em `runs/2026-10-15-api-real-v1/final-verification.json`. O benchmark está excluído do Git; o contrato técnico permanece em [TRANSCRIPTION_BENCHMARK.md](TRANSCRIPTION_BENCHMARK.md).
