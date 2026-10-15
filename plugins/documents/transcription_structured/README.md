# Transcrição local com falantes e exports

Plugin DOCUMENT `transcription_structured`, `heavy=True`, descoberto automaticamente. Usa o mesmo coordenador de `scripts/transcribe_structured.py`: large-v3, instância nova por áudio, orçamento de contexto textual zero, contagem automática de falantes e alinhamento por palavra em ambiente separado. Nenhum modelo é carregado na importação ou inicialização do plugin. Os modelos rodam nos subprocessos do coordenador.

Requer este checkout com `scripts/`, `.venv`, ffmpeg, modelos e `local-transcript-benchmark/.venv-align` já preparados. O adaptador não é uma instalação independente a partir apenas do wheel; não instala dependências nem altera ambientes. WhisperX permanece fora da `.venv` principal. Configuração dos ambientes e evidências: [guia de transcrição](../../../docs/TRANSCRIPTION_BENCHMARK.md).

## Contrato atual de entrega automática

O fluxo é enviar o áudio, transcrever e baixar CSV/VTT/TXT com todo trecho vinculado a um participante. Novas execuções estruturadas incluem `speaker_completion_policy={"version":1}` por padrão, independentemente das opções experimentais abaixo. A atribuição acústica é mantida; suas lacunas recebem uma hipótese por contexto do segmento nativo, palavras vizinhas originais ou regiões de voz existentes. Não há número fixo de participantes nem uso de referência Dovetail.

Antes desse preenchimento, uma etapa automática `verify` revê turnos curtos por comparação acústica direta: o turno e seu segmento nativo precisam concordar na mesma voz alternativa. Usa o embedding local do Community-1 em CPU com duas threads, sem retranscrição ou novo clustering. Pode corrigir também rótulos já preenchidos. A voz original e o suporte das mudanças ficam na auditoria; evidência fraca, concorrência real ou referências insuficientes preservam a hipótese anterior. O usuário não precisa ativar outro parâmetro.

Na v8, quatro turnos/dez palavras receberam revisão acústica, incluindo “Tá bom” inteiro como P2. O texto e os timestamps permaneceram iguais. As decisões não são confirmação humana de todas as identidades; passagens muito curtas ou sobrepostas podem continuar incertas. A saída permanece automática e vinculada a participantes.

Novas execuções também incluem `speaker_microturn_policy={"version":1}` após o preenchimento. Em segmentos parcialmente detectados, a regra pode rever uma ilha de voz menor que 0,4 segundo quando há a mesma voz estável antes/depois, apoio temporal dessa voz no segmento e ausência de sobreposição. Exige uma lacuna anteriormente preenchida pelo consenso de uma palavra detectada; preserva respostas curtas totalmente detectadas. A revisão é inferência por continuidade, com `speaker_microturn_evidence`, rótulo anterior e `acoustically_verified=false`, sem modelo adicional. Critérios completos em `docs/TRANSCRIPTION_BENCHMARK.md`. Na v9, a regra corrigiu duas palavras para P2 na terceira amostra, mantendo as outras gravações e saudações; CSV/VTT/TXT e downloads foram validados sem nova inferência.

Essa etapa toma uma decisão de participante; não apenas troca o nome de um rótulo desconhecido. Não modifica palavras, ordem ou tempos alinhados. `assignment_method=best_effort_completion`, `speaker_completion_evidence` e a atribuição anterior preservam a evidência da decisão. É uma hipótese automática, sem confirmação acústica adicional. Esses indicadores não bloqueiam a conclusão ou o download, nem exigem que o usuário preencha os trechos.

Se nenhuma voz foi detectada, o texto recebe um participante provisório identificado na auditoria. Isso não declara uma pessoa efetivamente reconhecida nem presume dois participantes. Palavras sem tempo individual podem usar no VTT o intervalo do segmento nativo existente, com indicação em `quality_audit.native_subtitle_fallback`; os tempos de palavra continuam ausentes no JSON/CSV. Sem qualquer intervalo válido, o texto permanece no CSV/TXT/JSON.

O comportamento acima substitui, para novas entregas, as descrições históricas de lacunas “Sem falante” nas rodadas v5/v6 abaixo. Os benchmarks históricos sem a política continuam reproduzíveis. Edição na interface não faz parte desta mudança.

## Uso

Após iniciar a API, selecionar **Local Transcription — speakers & exports** na tela Transcribe. Um upload inicia execução pesada; não fazer esse teste durante reuniões sem liberar a máquina.

```sh
curl -X POST http://127.0.0.1:8000/transcribe/transcription_structured \
  -F 'file=@/caminho/audio.m4a' \
  -F 'config={"language":"pt","device":"mps","speech_boundaries":false}'
```

Resposta padrão: HTTP 202 com `job_id`, `status_url` e `stream_url`. O resultado aparece em `GET /jobs/{job_id}` ao concluir. `?sync=true` conserva o limite de 60 s da API; prefira jobs para gravações longas. O gerenciamento existente limita concorrência pesada; não iniciar outros processos de modelos em paralelo por fora da fila.

Parâmetros: `language` pt/en/es (padrão pt; evidência atual em português), `device` mps/cpu (padrão mps), `speech_boundaries` e `recover_speakers` booleanos (ambos experimentais, padrão false). Não aceita contagem fixa de falantes. O modelo desta opção é large-v3; a opção simples `transcription_local` continua permitindo outros tamanhos.

`speech_boundaries` é experimental: usa voz detectada para limitar somente sobras externas longas, com margem de 5 s e redução mínima de 10 s, preservando pausas internas. Pode perder falas baixas/breves. A revisão do encerramento da v4 foi recebida, mas não valida generalização nem promove o parâmetro para padrão.

## Resultado

- `transcription`: TXT com falas consecutivas da mesma voz agrupadas; participante numa linha e texto abaixo.
- `detected_language`: idioma configurado; este modo exige idioma explícito, sem detecção automática.
- `duration`: duração do áudio original em segundos, incluindo eventuais sobras externas.
- `exports`: `csv`, `vtt`, `txt`, cada um com `filename`, `media_type`, `content`. UTF-8 e quebras de linha originais preservadas; os conteúdos não são URLs de arquivos temporários.
- `segments`, `words`: blocos e palavras com atribuições/tempos, incluindo valores ausentes.
- `review`: palavras com flags de incerteza; flags não equivalem a erros confirmados.
- `quality_audit`: sinais de repetição, sem apagar palavras. Ausência de sinais não prova correção.
- `provenance`: hash da fonte, configuração, hashes de código/artefatos, ambientes e validação estrutural. `human_audio_review=not_performed` refere-se à requisição atual.
- `status=completed`, `error=null` somente após validação estrutural aprovada.

A tela aguarda o job, mostra espera/execução e tempo decorrido, permite copiar o TXT e baixar CSV/VTT/TXT e JSON integral de auditoria. Não exibe porcentagem de conclusão de etapas. Não há editor de palavras/falantes nesta entrega: os arquivos podem ser revisados externamente, preservando o JSON original. IDs Participant são locais a cada gravação, sem identificação de pessoas.

O endereço da página recebe `?job=<id>` antes do hash durante o acompanhamento. Esse link reabre o mesmo job, inclusive enquanto está executando, sem enviar outro áudio nem repetir inferência. Exemplo: `http://127.0.0.1:5173/?job=<id>#/transcribe/transcription_structured`. A disponibilidade depende do TTL do job e do processo da API continuar ativo; guardar os downloads. O Vite encaminha `/jobs` para a API, incluindo SSE.

`recover_speakers=true` acrescenta uma etapa leve de atribuição após o alinhamento. Recupera somente lacunas com voz concordante dos dois lados, por proximidade da borda (até 0,15 s) ou ponte curta (até 3 s, pausas às palavras vizinhas até 1,5 s). Concorrentes na vizinhança impedem a borda; concorrentes em todo o contexto ou palavras vizinhas discordantes impedem a ponte. Sem tempo, empate e trocas de voz continuam pendentes. A regra parte da atribuição original, sem usar os novos rótulos como âncoras durante a passagem.

Atualização v6: a mesma opção experimental agora inclui reconciliação de ilhas de uma palavra ambígua, com âncoras originais concordantes, apoio temporal à alternativa e proteção de sobreposição real/intervenções com apoio exclusivo. Respostas curtas com maioria da duração sem voz detectada ficam pendentes. CLI equivalente: `--refine-speakers`; `--recover-speakers` mantém a v5 para comparação. Não foi acrescentado outro controle à tela e o padrão continua false. Critérios/limites e evidência em `docs/TRANSCRIPTION_BENCHMARK.md`, seção v6.

Em `words`, o rótulo anterior é preservado em `speaker_original`/`raw_speaker_original`; método e evidência ficam em `assignment_method` e `speaker_recovery_evidence`. As flags `no_voice_overlap` e `speaker_inferred` mantêm as palavras na revisão. CSV/VTT/TXT exibem o participante sugerido sem alterar palavras ou timestamps; o JSON e a tela indicam que houve inferência. Os métodos não são probabilidades de confiança. A opção não revê atribuições que já existiam e não garante eliminar todo Sem falante.

Na candidata v6, atribuições diretas ambíguas também podem ser revistas sob os critérios adicionais; `speaker_refinement_evidence` explica o motivo e a origem inicial continua preservada. `short_turn_abstention` significa retirada de sugestão sem evidência suficiente, sem indicar outra identidade. As limitações da regra v5 acima ficam registradas como histórico; a v6 não é correção irrestrita de toda atribuição anterior.

A candidata v5 foi reexportada nos três áudios sem novos modelos: palavras sem voz 4→3, 12→1 e 9→3; 18 palavras receberam rótulo inferido em 12 trechos. Texto/tempos e atribuições anteriores ficaram intactos. Confirmação humana das novas atribuições está pendente; opção não foi promovida para padrão. Evidências em `local-transcript-benchmark/runs/2026-10-15-v5-speakers/`. Os jobs publicados na prévia têm origem explícita `preview_from_verified_reexport_no_new_inference`, preservando o resultado anterior; isso não é outro teste de inferência/upload.

Nas rodadas históricas sem atribuição completa, palavras sem tempo ficavam fora do VTT e blocos sem voz apareciam como Sem falante. Novas execuções seguem o contrato de entrega automática descrito acima. Não há deduplicação nem uso de Dovetail na execução.

Intermediários e logs do adaptador são temporários e removidos ao terminar; guardar os downloads antes de sair da página. O core mantém seu cache existente e os jobs seguem seu TTL; isso não é um arquivo permanente. Para logs persistentes, checkpoints, pausa/retomada entre etapas, usar o CLI diretamente. Cancelamento de job já em execução e edição na tela não foram acrescentados.

## Validação

Testes do adaptador e API substituem inferência por workers de teste. Reexportação/empacotamento real de três intermediários v4 consta em `local-transcript-benchmark/runs/2026-10-15-integration-v1/`, sem carregar modelos; CSV/VTT idênticos à v4 e TXT idêntico aos exports de leitura v2.

Após liberação explícita, um teste real completo de `segunda.m4a` (23 min 9 s) foi executado via upload/proxy/API/jobs, sem reutilizar intermediários, em 556,441 s. Resultado: 2.882 palavras, dois falantes estimados, 96 linhas CSV e 278 legendas VTT, zero palavras sem tempo e 12 sem falante; validação estrutural aprovada. CSV idêntico à v4 e zero sinais dos detectores de repetição, sem nova afirmação de acurácia global.

O resultado foi reaberto por link em Chrome headless com perfil isolado. A propriedade textarea.value corresponde ao TXT, os quatro botões foram clicados e os downloads CSV/VTT/TXT conferem byte por byte; o JSON preserva os dados integrais. O limite mostrado no frontend foi corrigido para 500 MB nos transcritores locais, conservando 25 MB no Groq. Evidências, screenshot e arquivos em `local-transcript-benchmark/runs/2026-10-15-api-real-v1/`, especialmente `verification.json` e `browser-v2/verification.json`. O primeiro verificador de navegador procurava texto na serialização HTML, que não inclui textarea.value; sua falha era do critério de verificação. A v2 verifica o valor real e downloads, preservando a v1.
