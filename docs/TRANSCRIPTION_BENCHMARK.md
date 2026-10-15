# Transcrição estruturada e benchmark local

O Qualia possui transcrição local via whisper.cpp, transcrição via Groq e um plugin estruturado integrado à API/interface. As seções de rodadas e ensaios abaixo registram a evolução histórica; o contrato atual está descrito a seguir.

Status consolidado, configuração aprovada e limites de validação: [TRANSCRIPTION_STATUS.md](TRANSCRIPTION_STATUS.md). Referência atual: v9, validada por dois novos uploads integrais com as políticas finais. A comparação da gravação maior trouxe achados de qualidade ainda sem confirmação no áudio; aprovação estrutural não equivale a precisão integral.

Encerramento solicitado pelo usuário em 15/10/2026: documentação e commit, sem novos ajustes/testes. A apresentação da comparação foi considerada difícil por diferenças de timestamps e de recorte. Embora os cálculos recentes usem sequência de palavras, a correspondência exibida e os percentuais não constituem um parâmetro de qualidade aprovado. Ler a ressalva e os links no status antes de propor outra rodada.

## Entrega automática com participantes completos

Antes da associação de palavras e do preenchimento de lacunas, novas execuções estruturadas incluem uma etapa `verify` de verificação acústica (`voice_verification_policy`). Ela usa o embedding já instalado do Community-1 em CPU com duas threads, em processo próprio. Não retranscreve nem executa novamente o clustering da diarização. WhisperX continua no ambiente isolado.

A revisão considera turnos isolados de 0,4–2 s, com pelo menos 0,25 s de pausa em cada lado e sem outra voz simultânea. Compara a voz do turno e a voz do segmento nativo correspondente contra três amostras disjuntas de cada voz detectada, retiradas de regiões longas sem concorrência. Uma mudança exige concordância das duas medições, similaridade mínima 0,1, margem mínima 0,05 e ganho de 0,1 sobre o rótulo anterior. Esses limites são hipóteses experimentais, não probabilidades calibradas. Referências inconsistentes ou insuficientes impedem revisão. Não há texto/Dovetail como característica de classificação.

As vozes originais continuam em `transcript.diarization.json`; as decisões, scores e vozes revistas ficam em `transcript.voice.json`. A exportação usa a voz revista antes de associar palavras. O JSON de palavras também conserva a atribuição anterior à revisão acústica. O validador confere fontes, política, candidatos elegíveis e suporte das mudanças. A etapa usa somente pesos locais, sem download automático. Na retomada, seu resultado só é reutilizado com hashes e política compatíveis.

Na rodada v8, essa regra reviu quatro turnos e dez palavras nos três áudios, incluindo a resposta inteira “Tá bom” em P2. Os trechos previamente confirmados foram preservados. A concordância de participante com o Dovetail melhorou nesses dez pontos ao comparar pelo conteúdo, sem matching de timestamps. Isso não valida toda divergência remanescente nem estabelece precisão geral. A v7 demonstrava apenas cobertura de rótulos; a v8 acrescenta suporte acústico para essas revisões.

A revisão humana posterior confirmou um erro residual de atribuição na terceira amostra: uma fala curta rotulada como P3 pertence à mesma pessoa P2 das falas vizinhas. A v9 corrige esse caso pela passagem geral de continuidade descrita abaixo, sem novos modelos. A separação das saudações foi aceita e preservada; a identidade completa das vozes não foi confirmada. O retorno humano é evidência de avaliação, sem alimentar o classificador ou criar uma exceção por gravação.

Novas execuções de `transcribe_structured.py` e do plugin estruturado usam `speaker_completion_policy={"version":1}` por padrão. Cada palavra recebe um participante sem exigir intervenção ou configuração adicional. A contagem vem das vozes detectadas, sem fixar dois falantes. Quando a atribuição acústica deixa uma lacuna, `completion.py` escolhe uma hipótese usando consenso de palavras do mesmo segmento, sobreposição da voz no intervalo nativo, continuidade dos vizinhos ou região de voz mais próxima. Sem nenhuma voz detectada, registra um participante provisório.

A passagem não usa Dovetail, termos, entrevistas ou timestamps especiais. Preserva integralmente texto, ordem, tempos e rótulos já atribuídos. As decisões por contexto conservam origem/método/evidência e flags; não se apresentam como reconhecimento acústico confirmado. A validação reproduz as decisões e exige zero rótulos vazios na entrega, além da integridade textual e temporal. Manifestos históricos sem essa política conservam sua semântica.

Após o preenchimento, novas execuções incluem `speaker_microturn_policy={"version":1}`. `microturn.py` pode rever um segmento parcialmente detectado quando uma lacuna herdou, por consenso do segmento, o rótulo de uma ilha de voz menor que 0,4 segundo. Exige até três palavras, apoio direto na ilha, a mesma voz em turnos adjacentes de pelo menos 2 segundos, pausas de até 1,5 segundo dos dois lados e ausência de voz simultânea. O intervalo nativo de 0,4–3 segundos deve cobrir metade da ilha e conter ao menos 0,05 segundo da voz dos vizinhos. Respostas curtas totalmente detectadas ficam intactas.

Essa revisão é inferência temporal, com método `subsecond_voice_continuity`, flag `speaker_inferred` e `speaker_microturn_evidence.acoustically_verified=false`. Os campos `speaker_before_microturn`/`raw_speaker_before_microturn` e `assignment_before_microturn` preservam a decisão anterior, além da origem e evidência do preenchimento. O validador reproduz a regra e confere relatório e evidência. Na v9, apenas duas palavras da terceira mudaram para P2; primeira, segunda, saudações, quatro revisões acústicas anteriores e 16 palavras previamente confirmadas foram preservadas. Passaram 156 testes selecionados e os downloads reais dos três resultados. Os modelos da v8 foram reutilizados por hash; só exportação/validação foram executadas. Esse conjunto limitado não demonstra acurácia universal de continuidade.

CSV/TXT incluem todas as palavras com participante. VTT usa os tempos alinhados e, para palavras sem tempo individual, o intervalo nativo existente quando válido. A auditoria distingue esses cues por `native_segment_timing`; não são tempos de palavra recuperados por alinhamento. Sem qualquer intervalo disponível, a palavra permanece no CSV/TXT/JSON.

Rodada privada `2026-10-15-v7-complete-speakers-v2`: reexportação dos três intermediários verificados, com workers restritos a export/validate. Zero modelos novos, zero rótulos vazios, mesmas palavras/tempos e rótulos anteriores preservados. O preenchimento mede cobertura de atribuição, não acurácia de identidade. O fluxo de uso continua enviar/transcrever/baixar; nenhuma etapa de edição humana é exigida para gerar os arquivos.

## Fluxo

Áudio → texto Whisper com segmentos → alinhamento de palavras → intervalos de vozes → associação por sobreposição → agrupamento → CSV/VTT.

Os intervalos de vozes são independentes da transcrição e podem ser produzidos antes do alinhamento. Cada etapa pesada deve executar em processo separado para liberar memória. Resultados de etapas concluídas ficam em JSON; o alinhamento tem checkpoint por segmento.

`qualia.transcription.segments` contém utilidades sem dependências de modelos:

- `assign_words(words, turns, regular_turns=None)`: preserva palavras, atribui maior sobreposição de voz e marca ausência/empate/ambiguidade.
- `group_words(words, max_gap=1.5)`: cria blocos na ordem textual e quebra na mudança de voz, pausa ou tempo desconhecido.
- `export_rows(rows, csv_path, vtt_path, vtt_rows=None)`: CSV UTF-8 com `Speaker,Start Time,End Time,Text`; VTT somente para intervalos válidos.

`subtitle_rows(words)` usa alvos de 84 caracteres e 6 segundos, com quebra na voz ou pausa. Uma palavra indivisível pode exceder o alvo.

Falante desconhecido fica vazio. Palavras sem alinhamento continuam no CSV com tempos vazios e nos JSON de revisão, sem tempos proporcionais inventados. VTT não pode representar palavras sem intervalo válido. Tempos formatados em milissegundos são representação, não promessa de precisão em milissegundos.

## Runner

`scripts/transcript_benchmark.py` recebe `--manifest PATH --stage transcribe|diarize|align|export|compare`.

Manifesto de exemplo para qualquer gravação:

```json
{
  "output": "runs/experiment-01",
  "language": "pt",
  "model": "large-v3",
  "device": "mps",
  "num_speakers": null,
  "max_gap": 1.5,
  "inputs": [
    {"id": "sample-a", "audio": "audio.m4a", "reference": "reference.csv"}
  ]
}
```

Caminhos são relativos ao manifesto. `reference` é opcional; só `compare` acessa referências. `num_speakers: null` omite o parâmetro do Community-1, que estima a contagem. Um inteiro é uma opção explícita para gravações com número conhecido. Identificadores são locais por gravação, sem identidade pessoal ou papel deduzido.

`reuse_transcription` pode apontar para um JSON nativo existente, com fonte/modelo/idioma e hash de origem conferidos. `baseline` pode apontar para segmentos associados de uma rodada anterior, para comparação nos mesmos intervalos de palavras.

Configuração e hashes de áudios ficam em `config-and-sources.json`. Mudanças exigem outra pasta de rodada. Não reutilizar resultados antigos como se tivessem parâmetros novos.

## Ambientes

Transcrição, diarização, exportação e comparação usam a `.venv` do projeto. A fase de alinhamento usa um ambiente separado com WhisperX 3.8.6, pois seus requisitos de PyTorch 2.8/Transformers 4.x diferem do ambiente existente. Não instalar WhisperX diretamente na `.venv` sem avaliar essa mudança.

O alinhador WhisperX usa um modelo por idioma; português usa `jonatasgrosman/wav2vec2-large-xlsr-53-portuguese`. O runner usa apenas alinhamento, mantendo o texto da transcrição whisper.cpp. Timestamps ausentes não são interpolados (`interpolate_method='ignore'`).

Community-1 é baixado com `HF_TOKEN` do `.env`, após aceitar o acesso no Hugging Face. Inferência usa cache offline; telemetria do pyannote é desabilitada no runner. MPS é usado quando configurado e testado; `cpu` é uma alternativa explícita.

## Avaliação

Os exports de referência não determinam contagem, palavras, falantes ou regras de agrupamento. Matching de identificadores na comparação é um-para-um; vozes extras são reportadas, não colapsadas para melhorar o índice.

Concordância temporal por palavra usa apenas palavras com intervalo válido intersectando a referência. Deve acompanhar cobertura, palavras sem tempo/voz, contagem de falantes e resultados por falante. Não é DER, avaliação textual ou precisão contra áudio humano revisado.

Comparações entre rodadas com granularidades distintas usam os mesmos intervalos de palavras para reduzir efeito de denominadores diferentes. Mesmo assim, cobertura não alinhada permanece uma limitação a reportar.

Fontes privadas e artefatos de entrevistas ficam na pasta local excluída do Git. A documentação de processo, manifestos, resultados e limitações permanecem junto das amostras. A integração ao produto deve ocorrer depois da avaliação dessas etapas gerais.

Referências técnicas: [Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1), [alinhamento WhisperX](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py).

## Repetições no reconhecimento nativo

`repeated_segment_runs(segments, min_run=5)` registra séries de segmentos com texto idêntico consecutivo. O detector é um sinal de revisão, não uma prova de erro e não remove texto. Repetições longas no stream podem comprometer toda a análise posterior, mesmo quando o alinhador encontra tempos para as palavras. Alinhamento forçado não confirma que o texto foi falado nem recupera conteúdo perdido.

A fase seguinte deve isolar parâmetros de contexto, callback e execução segmentada com o mesmo modelo, mantendo versões e a mesma política para novas gravações. O resultado de um recorte isolado não basta para declarar corrigida a execução longa.

## Ensaios controlados do decoder

`scripts/transcript_decoder_experiment.py --manifest PATH` apenas descreve a matriz; não abre áudio nem carrega modelos. Inferência exige `--execute`. `--variant ID` e `--case ID` restringem a execução. Cada combinação roda em processo separado, com modelo novo por chamada, evitando herança de callback/contexto. Modelos e NumPy só são importados no worker.

O manifesto declara `model`, `language`, `output`, `inputs` e `variants`. Cada variante define `id`, `callback`, `chunk_seconds` (zero significa áudio completo) e `decoder` (`no_context`/`n_max_text_ctx`). Janelas contíguas incluem a cauda; não há deduplicação. Cortes nas fronteiras exigem revisão contra o áudio. São registrados parâmetros efetivos, retorno/callback, journals por janela, tempos inválidos e séries repetidas. Ausência de repetição não comprova recuperação textual.

A execução registra hashes de fontes/configuração/código e cópias dos fontes do runner. Retomada mantém resultados concluídos; áudio interrompido é refeito, preservando o journal anterior. Mudanças exigem outra versão. `--select ID --target-manifest PATH`, após revisão explícita, prepara uma candidata para o runner de alinhamento/exportação e reutiliza apenas diarização automática com hash de origem conferido. Não há escolha automática baseada nas referências. O alinhamento continua exclusivamente no ambiente isolado.

O dry-run e os testes sintéticos verificam preparação e isolamento, sem comprovar qualidade do reconhecimento. A seleção deve considerar os ensaios reais da rodada e registrar suas limitações.

## Política de decodificação contínua

`qualia.transcription.decoder.decode_segments` carrega uma instância nova por áudio e usa `no_context=true, n_max_text_ctx=0` por padrão. Isso desativa o histórico textual dentro da chamada, preservando integralmente texto e tempos nativos. Não há deduplicação, correções por gravação ou prompts de referência. A política foi ensaiada com large-v3/pt nas três amostras locais; outros modelos/idiomas ainda não estão validados. O plugin/API/frontend continuam fora desta integração.

O runner aceita `decoder_params` no manifesto, limitado a essas duas opções. A estratégia continua greedy com fallback de temperatura nativo; os ensaios registram os valores efetivos. Uma transcrição reutilizada deve comprovar fonte, modelo, idioma e política. `reuse_transcription_sha256` fixa o artefato candidato. Arquivo declarado e ausente causa erro, sem nova inferência implícita. Cache legado sem evidência da política é recusado; seus arquivos históricos permanecem intactos.

`scripts/validate_transcript_benchmark.py --manifest PATH` verifica a proveniência e a estrutura dos exports sem carregar modelos: CSV preserva palavras sem alinhamento com tempos vazios; VTT preserva palavras com intervalos válidos. O relatório diferencia verificações estruturais de precisão textual e de falantes, que requerem revisão humana.

## Execução em um comando

`scripts/transcribe_structured.py` coordena as etapas existentes, sem depender de arquivos de referência. A entrega inicial é de linha de comando; não integra o plugin/API/frontend.

```sh
.venv/bin/python scripts/transcribe_structured.py \
  --audio "/caminho/gravação.m4a" \
  --output "/caminho/rodadas/gravação-001"
```

O diretório de saída deve ser novo ou vazio. São usados large-v3, português, MPS, contagem automática de vozes e a política sem histórico textual. `--language pt|en|es` e `--device mps|cpu` são opções explícitas; a evidência atual da política é large-v3/pt. Cada etapa roda em processo separado, na ordem transcrição, diarização, alinhamento, exportação e validação. O alinhamento usa `local-transcript-benchmark/.venv-align/bin/python`; as demais etapas usam `.venv/bin/python`. Caminhos alternativos podem ser declarados com `--main-python` e `--align-python`; o pré-check recusa o mesmo ambiente para ambos. Nenhuma dependência é instalada automaticamente.

A saída inclui `transcript.csv`, `transcript.vtt`, `RESULTADO.md`, `result.json`, manifesto, estado das tentativas, JSONs intermediários, logs e cópia dos fontes utilizados. A conclusão indica validação estrutural; revisão humana de texto/falantes continua necessária. IDs de participantes são locais à gravação. Os nomes dos arquivos de saída são estáveis, independentemente do nome do áudio.

Para inspecionar o plano sem criar arquivos, executar subprocessos ou carregar modelos, acrescente `--dry-run` ao comando de criação. Essa opção confere o arquivo e calcula seu hash; não comprova disponibilidade dos modelos nem desempenho.

```sh
# Consultar a etapa e as tentativas registradas, sem carregar modelos.
.venv/bin/python scripts/transcribe_structured.py --status --output "/caminho/rodadas/gravação-001"

# Pedir pausa em outro terminal. A chamada atual termina antes da pausa.
.venv/bin/python scripts/transcribe_structured.py --pause --output "/caminho/rodadas/gravação-001"

# Retomar explicitamente uma rodada criada pelo comando.
.venv/bin/python scripts/transcribe_structured.py --resume --output "/caminho/rodadas/gravação-001"
```

Há dez segundos entre etapas por padrão, configuráveis com `--between-stages-seconds`. `--pause-after transcribe|diarize|align|export` encerra a execução antes da etapa seguinte. A pausa não é imediata durante reconhecimento/diarização; se precisar interromper, Ctrl+C ou SIGTERM encerra o grupo do worker, preservando arquivos e logs. A etapa interrompida poderá ser refeita; o alinhamento aproveita seu checkpoint compatível. Não usar SIGKILL como pausa cooperativa. Um lock impede dois coordenadores na mesma rodada; o worker herda o lock para também proteger contra a morte abrupta do coordenador enquanto ainda está ativo. Essa proteção é local à pasta; não iniciar rodadas pesadas diferentes em paralelo nesta máquina.

Na retomada, hashes do áudio, manifesto, código/snapshot e artefatos concluídos são reconferidos. Mudança exige uma nova pasta, sem sobrescrever o histórico. O estado registra interpretadores, resultados do pré-check, tentativas e hashes; os logs de uma nova tentativa são acrescentados. Somente etapas concluídas e verificadas são puladas. O ambiente atual é consultado novamente antes das etapas pendentes, mas hashes de pesos e todas as dependências transitivas não são fixados automaticamente pelo coordenador; mantenha o ambiente e o cache de modelos estáveis durante a rodada.

`--reuse-from /pasta/de/intermediarios` permite aproveitar explicitamente o conjunto de transcrição, diarização e alinhamento de uma única gravação encontrada pelo hash da fonte. Exige correspondência de nome da fonte, modelo, idioma, política, dispositivo, opções automáticas de vozes e hash da transcrição no alinhamento. As cópias são verificadas antes de pular as três etapas. Não é uma importação de CSV/Dovetail. Exportação e validação são executadas de novo na pasta nova. A opção é útil para mudanças de empacotamento; não demonstra inferência nova.

Validação desta entrega: 114 testes selecionados, incluindo 22 de coordenação; demonstração em três gravações existentes com ASR/vozes/alinhamento reutilizados e exportação/validação reais. Pausa após exportação e retomada foram exercitadas no comando real. Nenhuma nova inferência foi necessária, pois as funções de reconhecimento, diarização e alinhamento permaneceram inalteradas.

## Auditoria de repetição interna e proteção experimental nas bordas

A revisão humana da v3 identificou uma sequência repetida dentro de um único segmento, sobre ausência de fala/teclado no encerramento de uma amostra. O detector de séries entre segmentos não cobre esse caso. `qualia.transcription.audit.internal_repetitions` agora sinaliza ciclos de palavras dentro de segmentos (padrão: pelo menos cinco repetições de unidades de uma a oito palavras), sem alterar texto. Repetição intencional também pode ser sinalizada; é um pedido de revisão, não prova de erro. Os exports registram essa auditoria e o comando gera `quality-audit.json`, com aviso quando há sinais. Zero sinais não comprova ausência de alucinação.

Uma opção experimental evita enviar ao reconhecedor sobras externas longas sem voz detectada:

```sh
.venv/bin/python scripts/transcribe_structured.py \
  --audio "/caminho/gravação.m4a" \
  --output "/caminho/rodadas/gravação-002" \
  --speech-boundaries
```

Esse modo executa diarização antes da transcrição. Usa a união externa dos intervalos regulares de todas as vozes, mantendo cinco segundos de margem. Cada borda só é reduzida se a sobra após a margem for de pelo menos dez segundos. Pausas internas não são removidas. Sem nenhuma atividade de voz detectada, mantém o áudio inteiro; não assume que a ausência de detecção prove silêncio. Parâmetros estão em `speech_boundary_policy`; o JSON de transcrição registra limites em amostras, taxa, duração original e hash da diarização. Os timestamps permanecem relativos ao arquivo original, inclusive quando há corte inicial. Não há deduplicação ou eliminação de frases reconhecidas como forma de correção.

A opção fica desligada por padrão. Vozes baixas ou muito breves podem não aparecer na detecção; margens reduzem esse risco, mas não o eliminam. O modo não soluciona alucinações em pausas internas. Modelo e política textual continuam large-v3/pt com `no_context=true, n_max_text_ctx=0`.

Com `--reuse-from`, se esse modo exigir outros limites de áudio, somente a diarização compatível é importada; transcrição e alinhamento ficam pendentes. O `--dry-run` mostra isso antes da execução. Um cache de áudio recortado não pode ser reutilizado como se representasse reconhecimento do áudio inteiro. Um cache de áudio inteiro pode ser reaproveitado se a política não alterar as amostras de entrada. Alterações de código exigem nova pasta; snapshots de rodadas anteriores continuam preservados.

Evidência local de 2026-10-15: dois recortes de ausência de fala reproduziram alucinação, inclusive sob limiares nativos mais rígidos (alternativa rejeitada). Um recorte de encerramento com limites de voz e uma única passagem completa da terceira gravação foram testados. Na passagem completa, a sequência repetida desapareceu e os primeiros 481 segmentos ficaram idênticos à v3. Duas despedidas finais mudaram ligeiramente de tempo e um “Tchau” curto da v3 deixou de aparecer, mesmo estando dentro do áudio retido. Essa diferença de reconhecimento requer conferência; a candidata não foi promovida automaticamente. Nas duas primeiras gravações, o modo não altera nenhuma amostra de entrada e os CSV/VTT permanecem iguais. Esse conjunto não demonstra qualidade geral em outras gravações ou idiomas.

## Comparação lexical com Dovetail

`scripts/compare_transcript_text.py --manifest PATH --output NOVA_PASTA` compara a coluna `Text` dos CSVs gerados e de referência, sem carregar modelos. Referências são lidas somente nessa avaliação. Não altera a transcrição, contagem de vozes ou exports. O relatório anterior de `compare` continua medindo concordância temporal de falantes; seus percentuais não são acurácia textual.

A avaliação lexical usa Levenshtein mínimo exato por palavra: WER = (substituições + exclusões + inserções) / palavras da referência. A normalização ignora pontuação e caixa, preservando acentos, números e palavras de preenchimento. Os números não avaliam equivalência semântica. Por exemplo, uma quantia escrita por extenso pode divergir lexicalmente da mesma quantia em algarismos. A referência Dovetail pode conter erros ou edições; não interpretar 1-WER como acurácia validada contra áudio humano. Esta métrica também não avalia quem falou cada palavra.

A saída inclui resumo, JSON de método/proveniência, CSV/JSON com todos os blocos divergentes e HTML lado a lado com contexto. Os tempos apontam para blocos dos CSVs, não para precisão por palavra nas diferenças. A implementação usa biblioteca padrão, memória compacta e execução com baixa prioridade quando disponível; não instala dependências.

## TXT para leitura

O runner e o comando único agora também geram `<id>.txt` / `transcript.txt` em UTF-8. Falas consecutivas do mesmo participante identificado são unidas, mesmo com pausas. Cada bloco tem o identificador numa linha e o texto abaixo; mudanças de participante e blocos sem atribuição mantêm a separação e a ordem da conversa. Sem timestamps, resumo ou reescrita. Palavras sem alinhamento e sem atribuição continuam presentes; o rótulo ausente aparece como “Sem falante”.

`qualia.transcription.segments.export_text` parte dos blocos do CSV e consolida somente as falas consecutivas da mesma voz identificada, preservando todas as palavras. O coordenador inclui TXT entre os artefatos necessários da etapa de exportação e registra seu hash. O validador confere texto/rótulos quando o TXT está presente, mantendo leitura de rodadas legadas sem esse formato. Os exports históricos não são sobrescritos para acrescentar o formato; gerar em pasta nova. A entrega do comando local passa a ser CSV/VTT/TXT; a integração ao plugin/API/frontend é uma etapa própria.

## Motivo do ambiente WhisperX separado

O WhisperX 3.8.6 instalado declara `torch~=2.8.0`, `torchaudio~=2.8.0` e, neste macOS, `torchcodec>=0.6.0,<0.8.0`. O ambiente principal possui torch/torchaudio 2.10.0 e torchcodec 0.10.0. Instalar tudo junto exigiria alterar dependências usadas pelo Qualia. A `.venv-align` evita isso. O coordenador chama seu Python automaticamente só na etapa de alinhamento; a pessoa que usa o comando não precisa alternar ambientes manualmente. Os demais componentes continuam na `.venv` principal.

## Integração ao catálogo, API e frontend — 2026-10-15

O plugin DOCUMENT `transcription_structured` acrescenta o coordenador ao catálogo, separado de `transcription_local`. Parâmetros: idioma explícito pt/en/es, dispositivo mps/cpu e `speech_boundaries=false` por padrão. Modelo large-v3, contagem automática, sem Dovetail como entrada. A opção de limites externos continua experimental; a revisão final do encerramento v4 foi recebida com texto confere e falantes não avaliável. Não pedir essa revisão novamente nem interpretar o retorno como validação geral da política.

Upload em `POST /transcribe/transcription_structured` usa o JobManager existente e retorna 202. Nenhuma nova rota é necessária: conclusão/resultado por `/jobs/{id}` e SSE. A tela Transcribe agora aguarda jobs para todos os transcritores, trata conclusão rápida/cancelamento/fallback e mantém o mesmo envelope de resultado de respostas síncronas. Mostra espera/execução e tempo decorrido, sem percentual fictício das etapas internas. Para o plugin estruturado, oferece CSV/VTT/TXT e JSON de auditoria como downloads UTF-8, preservando inclusive CRLF do CSV.

O adaptador `qualia/transcription/service.py` invoca o comando em subprocesso com interpretadores explícitos separados, sem shell e sem carregar modelos no processo do plugin. Retorna os três conteúdos, blocos/palavras/revisão, sinais de repetição e proveniência: hash de fonte, configuração, código do coordenador/adaptador, artefatos e validação. Duração refere-se ao arquivo original. O idioma retornado é o configurado. Falhas de execução/validação não retornam sucesso parcial.

Intermediários/logs do adaptador são temporários e removidos ao terminar; os downloads e o JSON devem ser guardados pelo consumer. Cache e TTL de jobs existentes não substituem arquivo permanente. Checkpoints/logs persistentes e pausa/retomada continuam no CLI. Não foi acrescentado editor de palavras/falantes na tela nem cancelamento de worker já em execução. Requer checkout com `scripts/` e os ambientes preparados; não representa suporte independente a instalação somente pelo wheel.

O plugin simples também passa a criar instância nova por gravação e usar `no_context=true, n_max_text_ctx=0`; não mantém modelo nativo compartilhado no singleton. Isso acrescenta carregamento por gravação e evita reuso de estado entre chamadas. A evidência de qualidade da política permanece large-v3/pt.

Referência do contrato/uso: [plugin estruturado](../plugins/documents/transcription_structured/README.md). Evidências privadas em `local-transcript-benchmark/runs/2026-10-15-integration-v1/`: reexportação/validação reais e empacotamento das três gravações a partir de intermediários verificados, sem inferência; CSV/VTT iguais à v4, TXT igual aos textos de leitura v2. Testes de upload/core/jobs usam workers substituídos. Upload com inferência real e interação visual no navegador ainda precisam de validação; aguardar liberação explícita da máquina antes de carregar modelos.

A revisão comparativa humana recebeu os 12 casos: preferências Qualia 7, Dovetail 4, ambas com erro 1. A amostra dirigida não estima acurácia global e não é base para substituir frases automaticamente. Há oportunidades futuras de melhorar siglas/negações e fronteiras de voz por ensaios gerais controlados; nenhuma melhoria adicional de reconhecimento foi demonstrada nesta integração.

### Teste real de integração recebido — 2026-10-15

O usuário liberou a máquina para um teste real. A segunda gravação completa (1.388,905 s) foi enviada por multipart via Vite à API, com large-v3/pt, contagem automática, contexto textual zero e proteção experimental de bordas desligada. ASR, diarização e alinhamento foram recalculados, sem `--reuse-from`. Upload retornou 202 e job concluiu após 556,441 s. API de prévia usa o app normal com catálogo restrito aos transcritores em runtime, evitando warm-up de outros analisadores; não representa teste de todos os plugins do catálogo.

Saída: 2.882 palavras, dois rótulos de falantes, 96 linhas CSV, 278 cues VTT, zero palavras sem tempo e 12 sem falante, preservadas. Os 440 segmentos nativos são exatamente iguais à v4 dessa gravação. Os detectores não sinalizaram repetições; isso não é nova validação humana nem prova de ausência de outros erros. CSV ficou idêntico à v4, com validação estrutural aprovada e hashes de downloads iguais aos registrados pelo coordenador.

A tela pode reabrir um job por `?job=<id>` antes do hash, sem outro upload ou inferência. Testes Node passaram de sete para nove, cobrindo a reabertura e rejeição de job de outro plugin. O proxy `/jobs` foi acrescentado ao Vite. A tela local agora permite 500 MB, alinhada ao engine; Groq continua com 25 MB.

Chrome headless com perfil temporário isolado confirmou texto/participantes visíveis, limite de upload e cliques nos downloads CSV/VTT/TXT/JSON. Conteúdos baixados conferem com os dados da API. Screenshot inspecionado pelo agente. A primeira verificação de DOM falhou ao procurar texto em outerHTML de textarea; essa propriedade não serializa o valor aplicado pelo Svelte. A segunda conferiu textarea.value e arquivos reais; não foi erro da transcrição/interface.

Resultados, downloads, evidências de runtime e capturas preservados separadamente em `local-transcript-benchmark/runs/2026-10-15-api-real-v1/`. Nenhuma dependência instalada/alterada; WhisperX permaneceu isolado. Modelos terminaram antes da verificação do navegador. Só uma gravação foi recalculada pela API nesta validação; as outras duas possuem a evidência prévia de benchmark e reempacotamento, sem alegar três uploads frescos. API e interface permanecem servidas para conferência do usuário.

## Recuperação experimental de falantes — v5

`qualia/transcription/speakers.py` opera sobre a atribuição original de `assign_words`, sem modelos, referência ou conteúdo textual como regra. Ativar explicitamente `--recover-speakers` no comando ou `recover_speakers=true` no plugin estruturado. Padrão false. A política é registrada em `speaker_recovery_policy` no manifesto e no resumo de exportação.

Só são elegíveis grupos consecutivos sem voz por falta de sobreposição, com tempos válidos e ordenados, sem empate/concorrência. Os intervalos exclusivos mais próximos de ambos os lados precisam indicar a mesma voz, sem empates entre candidatos. Há duas regras:

- `near_voice_boundary`: grupo de até 1,5 s, a até 0,15 s de uma borda, sem outra voz regular no grupo e margem de 0,15 s.
- `same_voice_bridge`: grupo de até 3 s, palavras originais vizinhas da mesma voz concordante, pausas de até 1,5 s às duas palavras e nenhuma outra voz regular em todo o contexto entre elas.

Esses limites são hipóteses experimentais, não precisão temporal garantida nem probabilidade de confiança. O limite de pausa acompanha o agrupamento de 1,5 s já usado; a ponte admite um trecho curto de até duas vezes esse intervalo. Não houve busca de parâmetros para zerar desconhecidos por entrevista. As decisões usam a atribuição de entrada, sem propagação dos rótulos recém-inferidos. Texto, tempos e rótulos já atribuídos permanecem intactos. A regra não corrige atribuições anteriores incorretas nem recupera fala perdida.

As palavras recebem `speaker_original`, `raw_speaker_original`, `assignment_method` e, quando inferidas, `speaker_recovery_evidence` e flag `speaker_inferred`. A ausência original de sobreposição continua marcada; inferências permanecem na revisão. CSV/VTT/TXT usam o participante sugerido; JSON preserva a distinção e a tela mostra a quantidade inferida. O validador reproduz a política e verifica origem, métodos, evidência, contagem, tempos e preservação dos rótulos diretos. Código do novo módulo também entra no snapshot/hash do coordenador; não retomar rodadas antigas com código diferente.

Rodada separada: `local-transcript-benchmark/runs/2026-10-15-v5-speakers/`. ASR/vozes/alinhamento v4 foram reutilizados com verificação; guard permitiu somente export/validate. Nenhum modelo/dependência adicional. O modo de limites externos foi declarado explicitamente para compatibilidade com os intermediários v4; nas duas primeiras gravações não muda amostras de áudio. Isso não promove nenhuma das duas opções experimentais.

| Áudio | Palavras sem falante antes → depois | Blocos antes → depois | Palavras inferidas |
|---|---:|---:|---:|
| primeira | 4 → 3 | 3 → 2 | 1 |
| segunda | 12 → 1 | 6 → 1 | 11 |
| terceira | 9 → 3 | 8 → 2 | 6 |

Restam quatro palavras sem tempo, uma palavra com intervalo de mais de nove segundos e duas em trocas de voz. Redução de 25 para sete é cobertura de atribuição, não acurácia comprovada. A avaliação dos 12 trechos novos (74,25 s somados) está preparada em `review/`, com áudio original, proposta e JSON de resposta. Revisão humana pendente; não preencher respostas automaticamente com resultados técnicos.

132 testes Python selecionados passaram, com os mesmos quatro testes legados de discovery amplo excluídos; nove testes Node passaram e build passou. Chrome isolado confirmou resultado, aviso de 11 rótulos inferidos na segunda e quatro downloads idênticos aos dados. A página de revisão teve reprodução/seek e download de formulário vazio testados; o download de teste fica separado de retornos humanos. Capturas foram inspecionadas. API de prévia foi reiniciada sem jobs ativos, preservando o job anterior e publicando os três derivados com origem explícita de reexportação. Nenhum novo upload pesado foi feito.

## Refinamento de ilhas e proteção de respostas curtas — candidata v6

Após a revisão humana v5, a conversa explícita consolida para como P1, sem pedir nova conferência desse ponto. Foram observados erros originais em que/consumo e uma inferência rejeitada em Tá. Esses casos são evidência de desenvolvimento, não teste independente de acurácia.

`qualia/transcription/refinement.py` aplica uma passagem a partir das atribuições originais. Uma ilha de uma única palavra de até 0,75 s só pode mudar se os dois lados concordarem numa outra voz, houver três palavras originais limpas por lado em até seis segundos e o alinhamento registrar apoio à alternativa de pelo menos 0,05 s e 15% da sobreposição total. Concorrência simultânea real, outra voz adicional nos scores, ausência de âncoras ou apoio exclusivo à voz minoritária impedem mudança. O corredor entre vizinhos precisa caber em três segundos; lacunas dentro dele podem usar a mesma reconciliação. Não há propagação iterativa de rótulos corrigidos como novas âncoras.

Respostas nativas curtas (até três palavras/até dois segundos) com pausa externa de pelo menos 1,5 s e maioria da duração das palavras sem atribuição ficam protegidas contra preenchimento por continuidade. Isso retira a inferência de Tá, mas não adivinha quem falou nem reclassifica automaticamente bom. A verificação contra alvos já corretos levou a exigir maioria de duração ausente, para não abandonar palavras curtas legítimas em segmentos parcialmente detectados. Esses parâmetros são hipóteses experimentais, não probabilidades calibradas.

Ativação: `--refine-speakers`, incluindo recuperação; `--recover-speakers` conserva a regra v5 para comparação. O parâmetro existente `recover_speakers=true` do plugin passa a usar a candidata v6, continuando false por padrão; nenhum novo controle foi acrescentado à tela. A política completa fica em `speaker_refinement_policy`, o código entra no snapshot, e `speaker_refinement_evidence` explica cada revisão. `speaker_original` mantém o resultado direto inicial. Evidências da recuperação v5 podem coexistir como etapa anterior, com o método final em `assignment_method`; a reconciliação explícita registra a decisão que prevaleceu. O validador reproduz a passagem e exige justificativa para alterações diretas.

Rodada nova em `local-transcript-benchmark/runs/2026-10-15-v6-speakers/`, somente export/validate e reuso verificado dos três intermediários v4. Frente à v5, cinco palavras mudaram: três erros indicados pelo usuário passaram ao rótulo correto; Tá perdeu a inferência rejeitada; uma outra ilha foi proposta para revisão independente. As 16 palavras-alvo anteriormente confirmadas mantiveram o rótulo. A atribuição em para segue a confirmação explícita P1 da conversa. Não existem mais esclarecimentos pendentes desse ponto.

Palavras sem falante: 3/1/4 (oito no total, contra sete na v5). A palavra adicional é a inferência rejeitada retirada, não perda de texto. Texto e tempos preservados integralmente. Há 20 palavras com atribuição inferida/reconciliada, incluindo 17 lacunas preenchidas e três revisões de atribuições diretas. O contexto de bom e outras falas sem evidência suficiente não foi inventado.

137 testes Python selecionados passaram (mesmos quatro de discovery amplo excluídos), nove Node e build passaram. Chrome verificou tela, aviso, quatro downloads idênticos e o formulário de apenas uma mudança nova, com reprodução/seek e JSON vazio. Capturas inspecionadas. Resultados derivados v5/v6 são servidos por jobs de prévia com origem explícita, sem novo upload/inferência. Política continua experimental/default false; nenhum modelo/dependência novo. Os exemplos usados para ajustar a regra não demonstram generalização: resta uma nova proposta para escuta, além de avaliação futura em outras gravações.
