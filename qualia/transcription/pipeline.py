"""Coordenação local com isolamento de ambientes, pausa e retomada verificada.

Este módulo só usa a biblioteca padrão e utilidades leves. Modelos são carregados
exclusivamente pelos workers do runner, em processos separados.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .decoder import decoder_params, transcription_policy
from .audit import internal_repetitions
from .speech import DEFAULT_SPEECH_BOUNDARIES, recognition_window, window_matches
from .speakers import DEFAULT_SPEAKER_RECOVERY
from .refinement import DEFAULT_SPEAKER_REFINEMENT
from .completion import completion_policy
from .voice import DEFAULT_VOICE_VERIFICATION
from .microturn import DEFAULT_MICROTURN_POLICY
from .segments import repeated_segment_runs


REPO = Path(__file__).resolve().parents[2]
STAGES = ("transcribe", "diarize", "align", "verify", "export", "validate")
OUTPUTS = {
    "transcribe": ("transcript.transcription.json",),
    "diarize": ("transcript.diarization.json",),
    "align": ("transcript.alignment.json",),
    "verify": ("transcript.voice.json",),
    "export": tuple("transcript." + suffix for suffix in
                    ("csv", "vtt", "txt", "assigned-words.json", "rows.json", "review.json", "export.json")),
    "validate": ("validation.json",),
}
CODE = ("scripts/transcribe_structured.py", "scripts/transcript_benchmark.py",
        "scripts/validate_transcript_benchmark.py", "qualia/transcription/pipeline.py",
        "qualia/transcription/decoder.py", "qualia/transcription/segments.py",
        "qualia/transcription/audit.py", "qualia/transcription/speech.py", "qualia/transcription/speakers.py",
        "qualia/transcription/refinement.py", "qualia/transcription/completion.py", "qualia/transcription/voice.py",
        "qualia/transcription/microturn.py")
STATE = "execution.json"
PAUSE = "pause-between-stages.flag"


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text())


def save(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def exclusive(out, new=False):
    if new:
        if out.exists() and any(out.iterdir()):
            raise ValueError("Pasta de saída já contém arquivos; use outra pasta ou --resume.")
        out.mkdir(parents=True, exist_ok=True)
    elif not (out / STATE).is_file():
        raise ValueError("Pasta não foi criada por este comando; não será alterada.")
    with (out / ".pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Esta rodada já está em execução; consulte --status ou peça --pause.") from error
        try:
            if new and any(p.name != ".pipeline.lock" for p in out.iterdir()):
                raise ValueError("Pasta foi ocupada por outra execução; não será sobrescrita.")
            yield lock.fileno()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def check_transcript(data, config, digest):
    case = config["inputs"][0]
    if (data.get("source_sha256") != digest
            or data.get("source") != Path(case["audio"]).name
            or data.get("model") != config["model"]
            or data.get("language") != config["language"]
            or transcription_policy(data) != decoder_params(config["decoder_params"])):
        raise ValueError("Transcrição incompatível com áudio/modelo/idioma/política.")
    duration = data.get("audio_duration_seconds")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
        raise ValueError("Transcrição sem duração de áudio válida.")
    if not isinstance(data.get("segments"), list):
        raise ValueError("Transcrição sem segmentos.")


def check_diarization(data, config, digest):
    if (data.get("source_sha256") != digest or data.get("speaker_options") != {}
            or data.get("device") != config["device"]):
        raise ValueError("Diarização incompatível; a contagem deve ser automática.")
    if not isinstance(data.get("exclusive"), list) or not isinstance(data.get("regular"), list):
        raise ValueError("Diarização sem intervalos de vozes.")


def check_alignment(data, config, transcript_hash):
    if (data.get("native_transcript_sha256") != transcript_hash
            or data.get("language") != config["language"]
            or data.get("device") != config["device"]):
        raise ValueError("Alinhamento incompatível com transcrição/idioma/dispositivo.")
    if not isinstance(data.get("segments"), list):
        raise ValueError("Alinhamento sem segmentos.")


def check_voice(data, config, diarization_hash, transcript_hash):
    if (data.get('policy') != config.get('voice_verification_policy')
            or data.get('diarization_sha256') != diarization_hash
            or data.get('native_transcript_sha256') != transcript_hash
            or data.get('implementation_sha256') != sha(REPO/'qualia/transcription/voice.py')
            or not isinstance(data.get('exclusive'), list) or not isinstance(data.get('regular'), list)):
        raise ValueError('Verificação acústica incompatível com as vozes/transcrição/política.')


def reuse_files(folder, config, digest):
    """Reutilização explícita do conjunto ASR/vozes/alinhamento, sem referências."""
    candidates = []
    for path in sorted(folder.glob("*.transcription.json")):
        data = read(path)
        if data.get("source_sha256") == digest:
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError("Reutilização exige exatamente uma transcrição para este áudio.")
    transcript = candidates[0]
    prefix = transcript.name.removesuffix(".transcription.json")
    diarization = folder / f"{prefix}.diarization.json"
    alignment = folder / f"{prefix}.alignment.json"
    check_transcript(read(transcript), config, digest)
    check_diarization(read(diarization), config, digest)
    data = read(transcript)
    expected = None
    if config.get('speech_boundary_policy') is not None:
        expected = recognition_window(round(data['audio_duration_seconds']*16000),
                                      read(diarization)['regular'], config['speech_boundary_policy'], sha(diarization))
    if not window_matches(data, expected):
        if config.get('speech_boundary_policy') is not None:
            return {"diarize": diarization}
        raise ValueError('Transcrição com limites diferentes; não reutilizar como áudio inteiro.')
    check_alignment(read(alignment), config, sha(transcript))
    reuse = {"transcribe": transcript, "diarize": diarization, "align": alignment}
    voice = folder/f'{prefix}.voice.json'
    if config.get('voice_verification_policy') is not None and voice.exists():
        check_voice(read(voice), config, sha(diarization), sha(transcript))
        reuse['verify'] = voice
    return reuse


def plan(args):
    audio = args.audio.expanduser().resolve()
    if not audio.is_file():
        raise ValueError("Áudio não encontrado.")
    config = {"output": ".", "model": "large-v3", "language": args.language or "pt",
              "device": args.device or "mps", "num_speakers": None, "max_gap": 1.5,
              "decoder_params": decoder_params(),
              "speaker_completion_policy": completion_policy(),
              "voice_verification_policy": dict(DEFAULT_VOICE_VERIFICATION),
              "speaker_microturn_policy": dict(DEFAULT_MICROTURN_POLICY),
              "inputs": [{"id": "transcript", "audio": str(audio)}]}
    if args.speech_boundaries:
        config['speech_boundary_policy'] = dict(DEFAULT_SPEECH_BOUNDARIES)
    if args.recover_speakers or args.refine_speakers:
        config['speaker_recovery_policy'] = dict(DEFAULT_SPEAKER_RECOVERY)
    if args.refine_speakers:
        config['speaker_refinement_policy'] = dict(DEFAULT_SPEAKER_REFINEMENT)
    settings = {
        # Não resolver symlinks: a invocação deve conservar o diretório da venv.
        "main_python": str((args.main_python or REPO / ".venv/bin/python").expanduser().absolute()),
        "align_python": str((args.align_python or REPO / "local-transcript-benchmark/.venv-align/bin/python").expanduser().absolute()),
    }
    if Path(settings["main_python"]) == Path(settings["align_python"]):
        raise ValueError("Alinhamento precisa de um interpretador em ambiente separado.")
    digest = sha(audio)
    reuse = reuse_files(args.reuse_from.expanduser().resolve(), config, digest) if args.reuse_from else {}
    return config, settings, digest, reuse


def receipt(out, stage, origin="computed", **extra):
    return {"finished_utc": now(), "origin": origin,
            "outputs": {name: sha(out / name) for name in OUTPUTS[stage]}, **extra}


def prepare(out, config, settings, digest, reuse):
    save(out / "manifest.json", config)
    code = {name: sha(REPO / name) for name in CODE}
    for name in CODE:
        target = out / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, target)
    state = {"schema_version": 1, "created_utc": now(), "status": "ready",
             "source_sha256": digest, "manifest_sha256": sha(out / "manifest.json"),
             "code": code, "interpreters": settings, "completed": {}, "attempts": [],
             "active_stage": None, "worker_pid": None, "human_audio_review": "not_performed"}
    for stage, source in reuse.items():
        destination = out / OUTPUTS[stage][0]
        source_hash = sha(source)
        shutil.copyfile(source, destination)
        if sha(destination) != source_hash:
            raise ValueError("Artefato mudou durante a cópia; não executar a rodada.")
        state["completed"][stage] = receipt(
            out, stage, "verified_reuse", reused_from=str(source), reused_sha256=source_hash)
    # Verificar novamente as cópias antes de permitir que etapas sejam puladas.
    for stage in reuse:
        check_stage(out, config, state, stage)
    save(out / STATE, state)
    return state


def verify(out, state):
    if state.get("schema_version") != 1:
        raise ValueError("Versão de estado desconhecida; use outra rodada.")
    if sha(out / "manifest.json") != state["manifest_sha256"]:
        raise ValueError("Manifesto mudou; use outra rodada.")
    config = read(out / "manifest.json")
    if sha(Path(config["inputs"][0]["audio"])) != state["source_sha256"]:
        raise ValueError("Áudio mudou; use outra rodada.")
    if set(state["code"]) != set(CODE):
        raise ValueError("Registro de código incompatível; use outra rodada.")
    for name, digest in state["code"].items():
        if sha(REPO / name) != digest or sha(out / "source" / name) != digest:
            raise ValueError(f"Código mudou: {name}; preserve esta rodada e use outra pasta.")
    if set(state["completed"]) - set(STAGES):
        raise ValueError("Estado contém etapa desconhecida.")
    for stage, value in state["completed"].items():
        if set(value["outputs"]) != set(OUTPUTS[stage]):
            raise ValueError("Comprovante incompleto de etapa.")
        for name, digest in value["outputs"].items():
            if sha(out / name) != digest:
                raise ValueError(f"Artefato concluído mudou: {name}; não será sobrescrito.")
    return config


def check_stage(out, config, state, stage):
    for name in OUTPUTS[stage]:
        if not (out / name).is_file():
            raise ValueError(f"Etapa {stage} terminou sem produzir {name}.")
    if stage == "transcribe":
        data = read(out / OUTPUTS[stage][0])
        check_transcript(data, config, state["source_sha256"])
        expected = None
        if config.get('speech_boundary_policy') is not None:
            path = out / OUTPUTS['diarize'][0]
            expected = recognition_window(round(data['audio_duration_seconds']*16000),
                                          read(path)['regular'], config['speech_boundary_policy'], sha(path))
        if not window_matches(data, expected):
            raise ValueError('Transcrição não corresponde aos limites de reconhecimento configurados.')
    elif stage == "diarize":
        check_diarization(read(out / OUTPUTS[stage][0]), config, state["source_sha256"])
    elif stage == "align":
        check_alignment(read(out / OUTPUTS[stage][0]), config,
                        sha(out / OUTPUTS["transcribe"][0]))
    elif stage == 'verify':
        check_voice(read(out/OUTPUTS[stage][0]), config, sha(out/OUTPUTS['diarize'][0]), sha(out/OUTPUTS['transcribe'][0]))
    elif stage == "validate" and read(out / "validation.json").get("status") != "passed":
        raise ValueError("Validação estrutural não passou; consulte validation.json.")


def preflight(settings, pending):
    required = {}
    if pending:
        required["main_python"] = []
    if "transcribe" in pending:
        required["main_python"] += ["numpy", "pywhispercpp"]
    if "diarize" in pending:
        required["main_python"] += ["torch", "pyannote", "dotenv", "numpy"]
    if "align" in pending:
        required["align_python"] = ["whisperx", "torch", "numpy"]
    if 'verify' in pending:
        required['main_python'] += ['torch', 'pyannote', 'numpy', 'huggingface_hub']
    if any(s in pending for s in STAGES[:3]+('verify',)) and not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg não encontrado; nenhuma dependência será instalada automaticamente.")
    environments = {}
    for key, packages in required.items():
        interpreter = Path(settings[key])
        if not interpreter.is_file():
            label = "alinhamento" if key == "align_python" else "principal"
            raise ValueError(f"Interpretador de {label} não encontrado: {interpreter}")
        code = ("import importlib.util,importlib.metadata,json,sys\n"
                f"packages={packages!r}\n"
                "aliases={'pyannote':'pyannote.audio','dotenv':'python-dotenv'}\n"
                "versions={}\n"
                "for p in packages:\n"
                " try: versions[p]=importlib.metadata.version(aliases.get(p,p))\n"
                " except importlib.metadata.PackageNotFoundError: versions[p]=None\n"
                "print(json.dumps({'prefix':sys.prefix, 'python':sys.version.split()[0], "
                "'packages':versions, 'missing':[p for p in packages if importlib.util.find_spec(p) is None]}))")
        result = subprocess.run([str(interpreter), "-c", code], check=True,
                                capture_output=True, text=True, timeout=30)
        environments[key] = json.loads(result.stdout)
        missing = environments[key]["missing"]
        if missing:
            raise ValueError(f"Dependências ausentes em {interpreter}: {', '.join(missing)}. Ambiente não alterado.")
    if "align_python" in environments:
        if Path(environments["align_python"]["prefix"]).resolve() == Path(environments["main_python"]["prefix"]).resolve():
            raise ValueError("WhisperX e execução principal devem usar ambientes separados.")
    return environments


def command_for(stage, out, settings):
    manifest = str(out / "manifest.json")
    if stage == "validate":
        return [settings["main_python"], str(REPO / "scripts/validate_transcript_benchmark.py"),
                "--manifest", manifest]
    python = settings["align_python" if stage == "align" else "main_python"]
    return [python, str(REPO / "scripts/transcript_benchmark.py"),
            "--manifest", manifest, "--stage", stage]


def run_worker(command, log, lock_fd, on_started):
    """Lock herdado evita outro coordenador se o pai morrer antes do worker."""
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as stream:
        stream.write(f"\n--- Tentativa {now()} ---\n")
        stream.flush()
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True, pass_fds=(lock_fd,))
        begin = time.monotonic()
        try:
            on_started(process.pid)
            while True:
                try:
                    code = process.wait(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    print(f"  Em execução há {time.monotonic()-begin:.0f}s; log: {log}", flush=True)
            if code:
                raise subprocess.CalledProcessError(code, command)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def request_pause(out):
    if not (out / STATE).is_file():
        raise ValueError("Rodada não encontrada; não será criada uma pasta para pedir pausa.")
    (out / PAUSE).write_text(now() + "\n")
    print("Pausa solicitada: a etapa atual pode terminar; a próxima não será iniciada.", flush=True)


def finish(out, state):
    validation = read(out / "validation.json")
    transcript = read(out / OUTPUTS['transcribe'][0])
    audit = {'internal_repetitions': internal_repetitions(transcript['segments']),
             'repeated_segment_runs': repeated_segment_runs(transcript['segments']),
             'warning': 'Sinais para revisão, sem remover texto. Ausência desses sinais não comprova ausência de alucinação.'}
    export_info = read(out / 'transcript.export.json')
    audit['speaker_recovery'] = {'policy': export_info.get('speaker_recovery_policy'),
                                 'inferred_words': export_info.get('words_with_inferred_speaker', 0),
                                 'warning': 'Inferência por continuidade temporal; não confirma identidade. Consulte palavras e evidências no JSON.'}
    audit['speaker_completion'] = {'policy': export_info.get('speaker_completion_policy'),
                                    'context_assigned_words': export_info.get('words_with_best_effort_speaker', 0),
                                    'unassigned_words': export_info['words_without_speaker']}
    audit['native_subtitle_fallback'] = export_info.get('native_subtitle_fallback', [])
    audit['voice_verification'] = export_info.get('voice_verification')
    audit['speaker_microturn'] = export_info.get('speaker_microturn')
    save(out / 'quality-audit.json', audit)
    result = {"status": "completed", "validation": validation,
              "csv": str(out / "transcript.csv"), "vtt": str(out / "transcript.vtt"),
              "txt": str(out / "transcript.txt"),
              "reused_stages": [s for s, r in state["completed"].items() if r["origin"] == "verified_reuse"],
              "human_audio_review": "not_performed", 'quality_audit': audit}
    save(out / "result.json", result)
    case = validation["cases"][0]
    (out / "RESULTADO.md").write_text(
        "# Transcrição estruturada\n\n"
        "CSV/VTT/TXT gerados com participantes atribuídos automaticamente; validação estrutural aprovada.\n\n"
        "- [CSV](transcript.csv)\n- [VTT](transcript.vtt)\n- [Texto para leitura](transcript.txt)\n"
        "- [Validação](validation.json)\n- [Manifesto](manifest.json)\n"
        "- [Estado e tentativas](execution.json)\n\n"
        "- [Sinais de repetição para revisão](quality-audit.json)\n\n"
        f"Falantes estimados: {case['detected_speakers']}. Palavras: {case['native_words']}. "
        f"Sem tempo: {case['words_without_time']}; sem falante: {case['words_without_speaker']}.\n\n"
        f"Sinais de repetição interna: {len(audit['internal_repetitions'])}; "
        f"séries entre segmentos: {len(audit['repeated_segment_runs'])}. "
        "São sinais de revisão; zero não comprova texto correto.\n\n"
        "Palavras sem tempo individual ficam no CSV e usam o intervalo nativo no VTT quando disponível. "
        "Sem nenhum intervalo disponível, permanecem no CSV/TXT/JSON. Os rótulos não identificam pessoas. "
        "Atribuições por contexto e tempos nativos estão registrados em quality-audit.json.\n\n"
        f"Etapas reutilizadas após verificação: {', '.join(result['reused_stages']) or 'nenhuma'}. "
        "Não há uso de referência Dovetail neste comando.\n")
    state.pop("error", None)
    state.update(status="completed", active_stage=None, worker_pid=None, updated_utc=now())
    save(out / STATE, state)
    print(f"CONCLUÍDO: {out / 'transcript.csv'}, {out / 'transcript.vtt'} e {out / 'transcript.txt'}", flush=True)
    print("Validação estrutural aprovada; arquivos prontos com atribuição automática de participantes.", flush=True)
    if audit['internal_repetitions'] or audit['repeated_segment_runs']:
        print("Há trechos com repetição para conferir em quality-audit.json; o texto foi preservado.", flush=True)
    return 0


def execute(out, state, config, lock_fd, args):
    stage = None
    try:
        order = stage_order(config)
        pending = [s for s in order if s not in state["completed"]]
        if not pending:
            return finish(out, state)
        state.pop("error", None)
        state["preflight"] = preflight(state["interpreters"], pending)
        for stage in pending:
            if (out / PAUSE).exists():
                state.update(status="paused", active_stage=None, worker_pid=None, updated_utc=now())
                save(out / STATE, state)
                print("PAUSADO entre etapas; nenhum worker ativo desta rodada.", flush=True)
                return 0
            verify(out, state)
            # Resultados de tentativa interrompida só podem ser usados se compatíveis.
            if stage in STAGES[:3] and (out / OUTPUTS[stage][0]).exists():
                check_stage(out, config, state, stage)
            state.update(status="running", active_stage=stage, worker_pid=None, updated_utc=now())
            state["attempts"].append({"stage": stage, "started_utc": now(), "status": "running"})
            save(out / STATE, state)
            print(f"[{order.index(stage)+1}/{len(order)}] {stage}; log: {out / 'logs' / (stage+'.log')}", flush=True)

            def started(pid):
                state["worker_pid"] = pid
                save(out / STATE, state)

            run_worker(command_for(stage, out, state["interpreters"]),
                       out / "logs" / f"{stage}.log", lock_fd, started)
            check_stage(out, config, state, stage)
            state["completed"][stage] = receipt(out, stage)
            state["attempts"][-1].update(status="completed", finished_utc=now())
            state.update(worker_pid=None, active_stage=None, updated_utc=now())
            save(out / STATE, state)
            print(f"  {stage} concluída e arquivos conferidos.", flush=True)
            if stage == args.pause_after:
                request_pause(out)
            if stage != pending[-1]:
                deadline = time.monotonic() + args.between_stages_seconds
                while time.monotonic() < deadline and not (out / PAUSE).exists():
                    time.sleep(min(.2, max(0, deadline-time.monotonic())))
        verify(out, state)
        return finish(out, state)
    except (Exception, KeyboardInterrupt) as error:
        if state["attempts"] and state["attempts"][-1]["status"] == "running":
            state["attempts"][-1].update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                                           finished_utc=now())
        state.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                     active_stage=stage, worker_pid=None, error=str(error), updated_utc=now())
        save(out / STATE, state)
        if isinstance(error, KeyboardInterrupt):
            print("Interrompido; arquivos e logs preservados. Use --resume para retomar.", flush=True)
            return 130
        raise


def parser():
    result = argparse.ArgumentParser(description="Áudio → CSV/VTT com falantes automáticos, pausa e retomada.")
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audio", type=Path, help="Arquivo de áudio/vídeo para iniciar uma rodada nova.")
    mode.add_argument("--resume", action="store_true", help="Retomar somente as etapas pendentes verificadas.")
    mode.add_argument("--pause", action="store_true", help="Solicitar pausa após a etapa em andamento.")
    mode.add_argument("--status", action="store_true", help="Mostrar estado sem executar modelos.")
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--language", choices=["pt", "en", "es"], help="Padrão pt; política ensaiada em pt.")
    result.add_argument("--device", choices=["mps", "cpu"])
    result.add_argument("--main-python", type=Path)
    result.add_argument("--align-python", type=Path)
    result.add_argument("--reuse-from", type=Path, help="Pasta de intermediários compatíveis; não acessa referências.")
    result.add_argument("--speech-boundaries", action="store_true", help="Experimental: evitar sobras externas longas sem voz detectada; mantém margens e pausas internas.")
    result.add_argument('--recover-speakers', action='store_true', help='Experimental: inferir voz em lacunas limitadas, com evidência e flags preservadas.')
    result.add_argument('--refine-speakers', action='store_true', help='Experimental v6: reconciliar ilhas ambíguas e proteger respostas curtas; inclui recuperação.')
    result.add_argument("--dry-run", action="store_true", help="Descrever sem criar pasta ou iniciar processos.")
    result.add_argument("--pause-after", choices=STAGES)
    result.add_argument("--between-stages-seconds", type=float, default=10.)
    return result


def stage_order(config):
    order = ('diarize', 'transcribe', 'align', 'verify', 'export', 'validate') if config.get('speech_boundary_policy') is not None else STAGES
    return order if config.get('voice_verification_policy') is not None else tuple(s for s in order if s != 'verify')


def main(argv=None):
    args = parser().parse_args(argv)
    out = args.output.expanduser().resolve()
    try:
        if not math.isfinite(args.between_stages_seconds) or args.between_stages_seconds < 0:
            raise ValueError("Intervalo entre etapas deve ser finito e não negativo.")
        if not args.audio and any((args.language, args.device, args.main_python, args.align_python, args.reuse_from, args.speech_boundaries, args.recover_speakers, args.refine_speakers)):
            raise ValueError("Opções de entrada pertencem à criação; na retomada vale o manifesto original.")
        if args.dry_run and (args.pause or args.status):
            raise ValueError("--dry-run descreve uma criação ou retomada; não combine com --pause/--status.")
        if args.pause:
            request_pause(out)
            return 0
        if args.status:
            print(json.dumps(read(out / STATE), ensure_ascii=False, indent=2))
            return 0
        if args.audio:
            config, settings, digest, reuse = plan(args)
            if args.dry_run:
                print(json.dumps({"manifest": config, "output": str(out), "interpreters": settings,
                                  "source_sha256": digest, "reuse": {s: str(p) for s, p in reuse.items()},
                                  "pending": [s for s in stage_order(config) if s not in reuse]}, ensure_ascii=False, indent=2))
                return 0
            with exclusive(out, new=True) as fd:
                state = prepare(out, config, settings, digest, reuse)
                return execute(out, state, config, fd, args)
        with exclusive(out) as fd:
            state = read(out / STATE)
            config = verify(out, state)
            if args.dry_run:
                print(json.dumps({"status": state["status"], "pending": [s for s in stage_order(config) if s not in state["completed"]]}, ensure_ascii=False))
                return 0
            (out / PAUSE).unlink(missing_ok=True)
            return execute(out, state, config, fd, args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"ERRO: {error}", flush=True)
        return 1
