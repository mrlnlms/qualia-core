"""Coordenação sem modelos: pausa, retomada, proveniência e falhas reais."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from qualia.transcription import pipeline


REPO = Path(__file__).resolve().parents[1]


def test_recovery_policy_is_recorded_and_tampered_original_voice_fails_validation(recording):
    audio, out = recording
    assert invoke(['--audio', str(audio), '--output', str(out), '--recover-speakers',
                   '--between-stages-seconds', '0'], fake_worker(audio, [])) == 0
    config = pipeline.read(out / 'manifest.json')
    export = pipeline.read(out / 'transcript.export.json')
    assert export['speaker_recovery_policy'] == config['speaker_recovery_policy']
    assigned = pipeline.read(out / 'transcript.assigned-words.json')
    assigned[0]['raw_speaker_original'] = 'tampered-original'
    save(out / 'transcript.assigned-words.json', assigned)
    report = load_script('validate_transcript_benchmark').validate_case(config, out, out, config['inputs'][0])
    assert not report['checks']['speaker_recovery_reproducible']
    assert report['status'] == 'failed'


def test_default_delivery_assigns_every_word_without_optional_recovery(recording):
    audio, out = recording
    calls = []
    assert invoke(['--audio', str(audio), '--output', str(out), '--between-stages-seconds', '0'], fake_worker(audio, calls)) == 0
    assigned = pipeline.read(out/'transcript.assigned-words.json')
    assert all(w['speaker'] for w in assigned)
    assert assigned[1]['assignment_method'] == 'best_effort_completion'
    assert assigned[1]['speaker_review_required'] is True
    assert pipeline.read(out/'validation.json')['status'] == 'passed'


def test_default_microturn_export_and_validation_preserve_legacy_and_reject_tampering(recording):
    audio, out = recording
    out.mkdir()
    config, _, _, _ = pipeline.plan(pipeline.parser().parse_args(['--audio',str(audio),'--output',str(out)]))
    assert config['speaker_microturn_policy'] == {'version':1}
    save(out/'manifest.json', config)
    fixture_stage('transcribe', out, audio)
    native = pipeline.read(out/'transcript.transcription.json')
    native['audio_duration_seconds'] = 21.
    native['segments'] = [dict(start=0.,end=4.9,text='lead'), dict(start=4.9,end=6.4,text='gap direct'),
                          dict(start=6.4,end=12.,text='tail'),dict(start=15.,end=20.,text='third')]
    save(out/'transcript.transcription.json',native)
    fixture_stage('diarize',out,audio)
    diar = pipeline.read(out/'transcript.diarization.json')
    turns = [dict(start=0.,end=5.,speaker='A'),dict(start=6.,end=6.3,speaker='C'),
             dict(start=7.,end=12.,speaker='A'),dict(start=15.,end=20.,speaker='B')]
    diar.update(exclusive=turns,regular=turns,detected_speakers=3)
    save(out/'transcript.diarization.json',diar)
    segments = [dict(source_segment=i,source_text=s['text'],native_start=s['start'],native_end=s['end'],words=w)
                for i,(s,w) in enumerate(zip(native['segments'],[
                    [dict(word='lead',start=1.,end=2.)],
                    [dict(word='gap',start=5.8,end=5.9),dict(word='direct',start=6.,end=6.2)],
                    [dict(word='tail',start=8.,end=9.)], [dict(word='third',start=16.,end=17.)]]))]
    save(out/'transcript.alignment.json',dict(language='pt',device='mps',
         native_transcript_sha256=pipeline.sha(out/'transcript.transcription.json'),segments=segments))
    fixture_stage('verify',out,audio)
    exporter = load_script('transcript_benchmark')
    validator = load_script('validate_transcript_benchmark')
    exporter.export(config,out,out)
    words = pipeline.read(out/'transcript.assigned-words.json')
    assert [w['raw_speaker'] for w in words[1:3]] == ['A','A']
    assert words[2]['raw_speaker_original'] == 'C'
    assert validator.validate_case(config,out,out,config['inputs'][0])['status'] == 'passed'
    words[2]['speaker_microturn_evidence']['proposed_speaker'] = 'B'
    save(out/'transcript.assigned-words.json',words)
    assert validator.validate_case(config,out,out,config['inputs'][0])['status'] == 'failed'
    del config['speaker_microturn_policy']
    exporter.export(config,out,out)
    assert [w['raw_speaker'] for w in pipeline.read(out/'transcript.assigned-words.json')[1:3]] == ['C','C']
    assert validator.validate_case(config,out,out,config['inputs'][0])['status'] == 'passed'


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, data):
    path.write_text(json.dumps(data))


@pytest.fixture
def recording(tmp_path):
    audio = tmp_path / "entrevista com espaços.wav"
    audio.write_bytes(b"audio-fixture-no-inference")
    return audio, tmp_path / "output"


def fixture_stage(stage, out, audio):
    stem = "transcript"
    if stage == "transcribe":
        save(out / f"{stem}.transcription.json", {
            "source": audio.name, "source_sha256": pipeline.sha(audio),
            "model": "large-v3", "language": "pt",
            "decoder_params": {"no_context": True, "n_max_text_ctx": 0},
            "audio_duration_seconds": 2.,
            "segments": [{"start": 0., "end": 1., "text": "fala pendente"}],
        })
    elif stage == "diarize":
        turns = [{"start": 0., "end": 1., "speaker": "voice"}]
        save(out / f"{stem}.diarization.json", {
            "source_sha256": pipeline.sha(audio), "speaker_options": {},
            "device": "mps", "detected_speakers": 1,
            "exclusive": turns, "regular": turns,
        })
    elif stage == "align":
        save(out / f"{stem}.alignment.json", {
            "language": "pt", "device": "mps",
            "native_transcript_sha256": pipeline.sha(out / f"{stem}.transcription.json"),
            "segments": [{"source_segment": 0, "source_text": "fala pendente",
                          "words": [{"word": "fala", "start": 0., "end": .4},
                                    {"word": "pendente"}]}],
        })
    elif stage == 'verify':
        save(out/f'{stem}.voice.json', {
            'policy':pipeline.read(out/'manifest.json')['voice_verification_policy'],
            'exclusive':pipeline.read(out/f'{stem}.diarization.json')['exclusive'],
            'regular':pipeline.read(out/f'{stem}.diarization.json')['regular'],
            'diarization_sha256':pipeline.sha(out/f'{stem}.diarization.json'),
            'native_transcript_sha256':pipeline.sha(out/f'{stem}.transcription.json'),
            'implementation_sha256':pipeline.sha(REPO/'qualia/transcription/voice.py'),
            'report':{'status':'insufficient_long_voice_references','changes':[]},
        })
    elif stage == "export":
        load_script("transcript_benchmark").export(
            pipeline.read(out / "manifest.json"), out, out)
    elif stage == "validate":
        config = pipeline.read(out / "manifest.json")
        report = load_script("validate_transcript_benchmark").validate_case(
            config, out, out, config["inputs"][0])
        save(out / "validation.json", {"status": report["status"], "cases": [report]})


def fake_worker(audio, calls, pause=False, fail=None):
    def worker(command, log, lock_fd, on_started):
        stage = command[command.index("--stage") + 1] if "--stage" in command else "validate"
        out = Path(command[command.index("--manifest") + 1]).parent
        calls.append((stage, command[0]))
        on_started(123456)
        if fail == stage:
            (out / "transcript.alignment.checkpoint.jsonl").write_text("partial\n")
            raise subprocess.CalledProcessError(1, command)
        fixture_stage(stage, out, audio)
        if pause and stage == "transcribe":
            pipeline.request_pause(out)
    return worker


def invoke(args, worker):
    with patch.object(pipeline, "preflight", return_value={}), patch.object(pipeline, "run_worker", worker):
        return pipeline.main(args)


def test_pauses_after_stage_and_resumes_without_repeating_it(recording):
    audio, out = recording
    calls = []
    assert invoke(["--audio", str(audio), "--output", str(out), "--pause-after", "transcribe"],
                  fake_worker(audio, calls)) == 0
    assert pipeline.read(out / "execution.json")["status"] == "paused"
    assert [c[0] for c in calls] == ["transcribe"]
    assert invoke(["--resume", "--output", str(out), "--between-stages-seconds", "0"],
                  fake_worker(audio, calls)) == 0
    assert [c[0] for c in calls] == list(pipeline.STAGES)
    assert pipeline.read(out / "execution.json")["status"] == "completed"
    assert pipeline.read(out / "validation.json")["status"] == "passed"
    assert "pendente" in (out / "transcript.csv").read_text()
    assert "pendente" not in (out / "transcript.vtt").read_text()
    assert calls[2][1] != calls[0][1]  # WhisperX recebe outro interpretador.


def test_pause_requested_during_worker_prevents_next_stage(recording):
    audio, out = recording
    calls = []
    assert invoke(["--audio", str(audio), "--output", str(out)],
                  fake_worker(audio, calls, pause=True)) == 0
    assert [s for s, _ in calls] == ["transcribe"]
    assert pipeline.read(out / "execution.json")["status"] == "paused"


def test_failure_preserves_checkpoint_and_resumes_only_pending_stages(recording):
    audio, out = recording
    calls = []
    assert invoke(["--audio", str(audio), "--output", str(out), "--between-stages-seconds", "0"],
                  fake_worker(audio, calls, fail="align")) == 1
    state = pipeline.read(out / "execution.json")
    assert state["status"] == "failed"
    assert "align" not in state["completed"]
    checkpoint = out / "transcript.alignment.checkpoint.jsonl"
    assert checkpoint.read_text() == "partial\n"
    assert invoke(["--resume", "--output", str(out), "--between-stages-seconds", "0"],
                  fake_worker(audio, calls)) == 0
    assert [s for s, _ in calls].count("transcribe") == 1
    assert [s for s, _ in calls].count("align") == 2
    assert checkpoint.read_text() == "partial\n"


@pytest.mark.parametrize("change", ["audio", "artifact", "manifest", "code"])
def test_changed_inputs_or_completed_artifacts_refuse_resume(recording, change):
    audio, out = recording
    calls = []
    invoke(["--audio", str(audio), "--output", str(out), "--pause-after", "transcribe"],
           fake_worker(audio, calls))
    if change == "audio":
        audio.write_bytes(b"changed")
    elif change == "artifact":
        path = out / "transcript.transcription.json"
        path.write_text(path.read_text() + " ")
    elif change == "manifest":
        data = pipeline.read(out / "manifest.json")
        data["language"] = "en"
        save(out / "manifest.json", data)
    else:
        state = pipeline.read(out / "execution.json")
        state["code"]["scripts/transcript_benchmark.py"] = "changed"
        save(out / "execution.json", state)
    assert invoke(["--resume", "--output", str(out)], fake_worker(audio, calls)) == 1
    assert len(calls) == 1


def test_existing_unrelated_folder_is_preserved(recording):
    audio, out = recording
    out.mkdir()
    (out / "original.txt").write_text("preserve")
    assert invoke(["--audio", str(audio), "--output", str(out)],
                  fake_worker(audio, [])) == 1
    assert sorted(p.name for p in out.iterdir()) == ["original.txt"]


def test_dry_run_does_not_create_output_or_start_subprocess(recording):
    audio, out = recording
    with patch.object(pipeline, "run_worker") as worker, patch.object(pipeline, "preflight") as checks:
        assert pipeline.main(["--audio", str(audio), "--output", str(out), "--dry-run"]) == 0
    assert not out.exists()
    worker.assert_not_called()
    checks.assert_not_called()


def test_exclusive_lock_prevents_second_coordinator(recording):
    audio, out = recording
    calls = []
    invoke(["--audio", str(audio), "--output", str(out), "--pause-after", "transcribe"],
           fake_worker(audio, calls))
    with (out / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert invoke(["--resume", "--output", str(out)], fake_worker(audio, calls)) == 1
    assert len(calls) == 1


def test_verified_reuse_skips_all_model_stages(recording, tmp_path):
    audio, out = recording
    cached = tmp_path / "cached"
    cached.mkdir()
    for stage in pipeline.STAGES[:3]:
        fixture_stage(stage, cached, audio)
    save(cached/'manifest.json',{'voice_verification_policy':dict(pipeline.DEFAULT_VOICE_VERIFICATION)})
    fixture_stage('verify',cached,audio)
    calls = []
    assert invoke(["--audio", str(audio), "--output", str(out), "--reuse-from", str(cached),
                   "--between-stages-seconds", "0"], fake_worker(audio, calls)) == 0
    assert [s for s, _ in calls] == ["export", "validate"]
    assert pipeline.read(out / "execution.json")["completed"]["align"]["origin"] == "verified_reuse"


@pytest.mark.parametrize("change", ["policy", "alignment", "speakers", "model"])
def test_incompatible_reuse_is_refused(recording, tmp_path, change):
    audio, out = recording
    cached = tmp_path / "cached"
    cached.mkdir()
    for stage in pipeline.STAGES[:3]:
        fixture_stage(stage, cached, audio)
    if change in {"policy", "model"}:
        path = cached / "transcript.transcription.json"
        data = pipeline.read(path)
        if change == "policy":
            data["decoder_params"]["n_max_text_ctx"] = 16384
        else:
            data["model"] = "tiny"
    elif change == "alignment":
        path = cached / "transcript.alignment.json"
        data = pipeline.read(path)
        data["native_transcript_sha256"] = "changed"
    else:
        path = cached / "transcript.diarization.json"
        data = pipeline.read(path)
        data["speaker_options"] = {"num_speakers": 2}
    save(path, data)
    calls = []
    assert invoke(["--audio", str(audio), "--output", str(out), "--reuse-from", str(cached)],
                  fake_worker(audio, calls)) == 1
    assert not calls
    assert not out.exists()


def test_success_exit_without_output_does_not_complete_stage(recording):
    audio, out = recording
    assert invoke(["--audio", str(audio), "--output", str(out)], lambda *args: None) == 1
    state = pipeline.read(out / "execution.json")
    assert state["status"] == "failed"
    assert state["completed"] == {}


def test_real_child_failure_is_logged_and_attempts_do_not_overwrite(tmp_path):
    log = tmp_path / "worker.log"
    with (tmp_path / "lock").open("a") as lock:
        for _ in range(2):
            with pytest.raises(subprocess.CalledProcessError):
                pipeline.run_worker([sys.executable, "-c", "print('attempt', flush=True); raise SystemExit(7)"],
                                    log, lock.fileno(), lambda pid: None)
    assert log.read_text().count("attempt") == 2


def test_preflight_checks_only_needed_environment(recording):
    audio, out = recording
    settings = {"main_python": str(Path(sys.executable)), "align_python": str(out / "missing-align")}
    # Exportação e validação não dependem do ambiente WhisperX nem de ffmpeg.
    pipeline.preflight(settings, ["export", "validate"])
    with pytest.raises(ValueError, match="alinhamento"):
        pipeline.preflight(settings, ["align"])


def test_preflight_refuses_two_interpreters_using_same_environment():
    settings = {"main_python": sys.executable, "align_python": sys.executable}
    response = subprocess.CompletedProcess([], 0, json.dumps({"prefix": "/same", "python": "3.13", "missing": []}))
    with patch.object(pipeline.subprocess, "run", return_value=response):
        with pytest.raises(ValueError, match="separados"):
            pipeline.preflight(settings, ["align"])


def test_resume_after_last_receipt_finishes_summary_without_workers(recording):
    audio, out = recording
    calls = []
    invoke(["--audio", str(audio), "--output", str(out), "--between-stages-seconds", "0"],
           fake_worker(audio, calls))
    state = pipeline.read(out / "execution.json")
    state["status"] = "running"  # Queda entre o último comprovante e o fechamento.
    save(out / "execution.json", state)
    (out / "RESULTADO.md").unlink()
    before = len(calls)
    assert invoke(["--resume", "--output", str(out)], fake_worker(audio, calls)) == 0
    assert len(calls) == before
    assert pipeline.read(out / "execution.json")["status"] == "completed"
    assert (out / "RESULTADO.md").is_file()


def test_dry_run_pause_is_refused_without_creating_flag(recording):
    audio, out = recording
    calls = []
    invoke(["--audio", str(audio), "--output", str(out), "--pause-after", "transcribe"],
           fake_worker(audio, calls))
    (out / pipeline.PAUSE).unlink()
    assert pipeline.main(["--pause", "--dry-run", "--output", str(out)]) == 1
    assert not (out / pipeline.PAUSE).exists()


def test_interrupt_terminates_and_reaps_real_worker(tmp_path):
    seen = []

    def interrupt(pid):
        seen.append(pid)
        raise KeyboardInterrupt

    with (tmp_path / "lock").open("a") as lock:
        with pytest.raises(KeyboardInterrupt):
            pipeline.run_worker([sys.executable, "-c", "import time; time.sleep(5)"],
                                tmp_path / "interrupt.log", lock.fileno(), interrupt)
    assert len(seen) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(seen[0], 0)


def test_opt_in_speech_boundaries_reuse_only_diarization_if_audio_window_changes(recording, tmp_path):
    audio,out=recording
    cached=tmp_path/'cached';cached.mkdir()
    for stage in pipeline.STAGES[:3]:
        fixture_stage(stage,cached,audio)
    path=cached/'transcript.transcription.json'
    data=pipeline.read(path);data['audio_duration_seconds']=100.;save(path,data)
    args=pipeline.parser().parse_args(['--audio',str(audio),'--output',str(out),
                                      '--reuse-from',str(cached),'--speech-boundaries'])
    config,settings,digest,reuse=pipeline.plan(args)
    assert set(reuse)=={'diarize'}
    assert pipeline.stage_order(config)==('diarize','transcribe','align','verify','export','validate')
