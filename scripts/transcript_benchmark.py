"""Runner de transcrição por manifesto, independente de entrevista/referência.

Executar cada etapa em processo próprio. O alinhamento usa o ambiente WhisperX
isolado; demais etapas usam a .venv do Qualia. Referências só entram em compare.
"""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qualia.transcription.decoder import decoder_params, transcription_policy, decode_segments
from qualia.transcription.speech import recognition_window, window_matches
from qualia.transcription.audit import internal_repetitions
from qualia.transcription.speakers import recover_speaker_gaps, speaker_recovery_policy
from qualia.transcription.refinement import refine_speaker_assignments, refinement_policy
from qualia.transcription.microturn import reconcile_microturns
from qualia.transcription.completion import complete_speakers, completion_policy
from qualia.transcription.voice import DEFAULT_VOICE_VERIFICATION, verify_turns
from qualia.transcription.segments import (
    assign_words,
    group_words,
    subtitle_rows,
    export_rows,
    export_text,
    valid_interval,
    overlap,
    repeated_segment_runs,
)


def save(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audio_array(path):
    import numpy as np

    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    return np.frombuffer(raw, dtype=np.float32).copy()


def native(path):
    return json.loads(path.read_text())


def verify_transcription(data, audio, config, policy, digest, expected_window=None):
    if data.get('source_sha256') != digest:
        raise ValueError('Hash da transcrição não corresponde à fonte; use outra rodada.')
    if (data.get('source') != audio.name or data.get('model') != config['model']
            or data.get('language') != config['language']):
        raise ValueError('Transcrição não corresponde à fonte/modelo/idioma.')
    if transcription_policy(data) != policy:
        raise ValueError('Política de decoder ausente ou diferente; use outra rodada/transcrição.')
    if not window_matches(data, expected_window):
        raise ValueError('Limites do áudio reconhecido mudaram; use outra rodada/transcrição.')


def transcribe(config, root, out):
    policy = decoder_params(config.get('decoder_params'))
    for case in config['inputs']:
        dest = out / f"{case['id']}.transcription.json"
        audio = root / case['audio']
        digest = sha(audio)
        waveform = None
        window = None
        if config.get('speech_boundary_policy') is not None:
            waveform = audio_array(audio)
            diar_path = out / f"{case['id']}.diarization.json"
            diar = native(diar_path)
            if diar.get('source_sha256') != digest or diar.get('speaker_options') != {}:
                raise ValueError('Limites de reconhecimento exigem vozes automáticas da mesma fonte.')
            window = recognition_window(len(waveform), diar['regular'], config['speech_boundary_policy'], sha(diar_path))
        if dest.exists():
            verify_transcription(native(dest), audio, config, policy, digest, window)
            print(case['id'], 'transcrição disponível com política conferida.', flush=True)
            continue
        if case.get('reuse_transcription'):
            candidate = root / case['reuse_transcription']
            if not candidate.is_file():
                raise ValueError('Transcrição declarada para reutilização não existe; sem fallback implícito.')
            payload = candidate.read_bytes()
            candidate_hash = hashlib.sha256(payload).hexdigest()
            expected = case.get('reuse_transcription_sha256')
            if expected and expected != candidate_hash:
                raise ValueError('Transcrição candidata mudou; use outra rodada.')
            data = json.loads(payload)
            verify_transcription(data, audio, config, policy, digest, window)
            data.update(source_sha256=digest, reused_from=str(candidate.resolve()),
                        reused_sha256=candidate_hash, decoder_params=policy)
            save(dest, data)
            print(case['id'], 'transcrição reutilizada com política e hash conferidos.', flush=True)
            continue
        if waveform is None:
            waveform = audio_array(audio)
        begin = time.monotonic()
        print(case['id'], 'transcrevendo com instância nova e política explícita...', flush=True)
        selected = waveform if window is None else waveform[window['start_sample']:window['end_sample']]
        segments = decode_segments(selected, config['model'], config['language'], params=policy)
        if window and window['start_sample']:
            offset = window['start_sample']/16000
            segments = [{**s, 'start': s['start']+offset, 'end': s['end']+offset} for s in segments]
        data = {'source': audio.name, 'source_sha256': digest,
                    'model': config['model'], 'language': config['language'],
                    'audio_duration_seconds': len(waveform)/16000,
                    'elapsed_seconds': time.monotonic()-begin,
                    'elapsed_includes_model_load': True,
                    'decoder_params': policy, 'model_instance_policy': 'fresh_per_audio',
                    'segments': segments}
        if window is not None:
            data['recognition_window'] = window
        save(dest, data)


def diarize(config, root, out):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    import torch
    from dotenv import load_dotenv
    from pyannote.audio import Pipeline

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    torch.set_num_threads(4)
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1", token=os.environ["HF_TOKEN"]
    )
    pipeline.to(torch.device(config["device"]))
    options = (
        {}
        if config.get("num_speakers") is None
        else {"num_speakers": config["num_speakers"]}
    )
    for case in config["inputs"]:
        dest = out / f'{case["id"]}.diarization.json'
        digest = sha(root / case["audio"])
        if dest.exists():
            data = native(dest)
            if (
                data.get("source_sha256") != digest
                or data.get("speaker_options") != options
            ):
                raise ValueError("Cache de diarização mudou; use nova rodada.")
            print(case["id"], "diarização disponível.", flush=True)
            continue
        waveform = audio_array(root / case["audio"])
        begin = time.monotonic()
        last = 0

        def hook(step, artifact, file=None, total=None, completed=None):
            nonlocal last
            now = time.monotonic()
            if now - last >= 20:
                print(
                    case["id"],
                    step,
                    f"{completed}/{total}",
                    f"{now-begin:.1f}s",
                    flush=True,
                )
                last = now

        result = pipeline(
            {"waveform": torch.from_numpy(waveform).unsqueeze(0), "sample_rate": 16000},
            hook=hook,
            **options,
        )

        def turns(value):
            return [
                {"start": turn.start, "end": turn.end, "speaker": voice}
                for turn, voice in value
            ]

        exclusive = turns(result.exclusive_speaker_diarization)
        save(
            dest,
            {
                "source": case["audio"],
                "source_sha256": digest,
                "speaker_options": options,
                "device": config["device"],
                "elapsed_seconds": time.monotonic() - begin,
                "detected_speakers": len(set(r["speaker"] for r in exclusive)),
                "exclusive": exclusive,
                "regular": turns(result.speaker_diarization),
            },
        )
        print(
            case["id"],
            "falantes estimados:",
            len(set(r["speaker"] for r in exclusive)),
            flush=True,
        )


def align(config, root, out):
    os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    import whisperx

    torch.set_num_threads(4)
    print("Carregando alinhador por idioma...", flush=True)
    model, metadata = whisperx.load_align_model(config["language"], config["device"])
    for case in config["inputs"]:
        dest = out / f'{case["id"]}.alignment.json'
        if dest.exists():
            print(case["id"], "alinhamento disponível.", flush=True)
            continue
        transcript = native(out / f'{case["id"]}.transcription.json')
        waveform = audio_array(root / case["audio"])
        journal = out / f'{case["id"]}.alignment.checkpoint.jsonl'
        existing = []
        if journal.exists():
            for line in journal.read_text().splitlines():
                existing.append(json.loads(line))
        results = list(existing)
        begin = time.monotonic()
        last = 0
        with journal.open("a") as f:
            for idx, seg in enumerate(transcript["segments"]):
                if idx < len(existing):
                    if (
                        existing[idx]["source_segment"] != idx
                        or existing[idx]["source_text"] != seg["text"]
                    ):
                        raise ValueError("Checkpoint não corresponde à transcrição.")
                    continue
                flags = []
                words = []
                if valid_interval(seg):
                    result = whisperx.align(
                        [seg],
                        model,
                        metadata,
                        waveform,
                        config["device"],
                        interpolate_method="ignore",
                        return_char_alignments=False,
                    )
                    words = result["word_segments"]
                    if (
                        " ".join(w["word"] for w in words).split()
                        != seg["text"].split()
                    ):
                        words = []
                        flags.append("alignment_text_mismatch_or_failed")
                else:
                    flags.append("native_nonpositive_duration")
                if not words:
                    words = [
                        {"word": w, "flags": flags + ["unaligned_time"]}
                        for w in seg["text"].split()
                    ]
                row = {
                    "source_segment": idx,
                    "source_text": seg["text"],
                    "native_start": seg["start"],
                    "native_end": seg["end"],
                    "words": words,
                }
                f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                f.flush()
                results.append(row)
                now = time.monotonic()
                if now - last >= 20:
                    print(
                        case["id"],
                        f'alinhados {idx+1}/{len(transcript["segments"])}',
                        f"{now-begin:.1f}s",
                        flush=True,
                    )
                    last = now
        save(
            dest,
            {
                "language": config["language"],
                "device": config["device"],
                "elapsed_seconds": time.monotonic() - begin,
                "native_transcript_sha256": sha(
                    out / f'{case["id"]}.transcription.json'
                ),
                "segments": results,
            },
        )
        print(case["id"], "alinhamento concluído.", flush=True)


def verify(config, root, out):
    """Small CPU-only acoustic pass; isolated from WhisperX and export."""
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    os.environ['OMP_NUM_THREADS'] = '2'
    import numpy as np
    import torch
    from huggingface_hub import try_to_load_from_cache
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding
    if config.get('voice_verification_policy') != DEFAULT_VOICE_VERIFICATION:
        raise ValueError('Política acústica desconhecida.')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    checkpoint = try_to_load_from_cache('pyannote/speaker-diarization-community-1', 'embedding/pytorch_model.bin')
    if not isinstance(checkpoint, str):
        raise ValueError('Embedding local ausente; nenhuma dependência/modelo será baixado.')
    embedding = PretrainedSpeakerEmbedding(checkpoint, device=torch.device('cpu'))
    for case in config['inputs']:
        audio = audio_array(root/case['audio'])
        diar_path, native_path = out/f'{case["id"]}.diarization.json', out/f'{case["id"]}.transcription.json'
        diar, transcript = native(diar_path), native(native_path)
        def vector(region):
            piece = audio[round(region['start']*16000):round(region['end']*16000)]
            if len(piece) < embedding.min_num_samples:
                return None
            value = embedding(torch.from_numpy(piece)[None,None,:])[0]
            if not np.isfinite(value).all() or np.linalg.norm(value)==0:
                return None
            return value/np.linalg.norm(value)
        begin = time.monotonic()
        exclusive, regular, report = verify_turns(diar['exclusive'], diar['regular'], transcript['segments'], vector)
        save(out/f'{case["id"]}.voice.json', dict(
            policy=dict(DEFAULT_VOICE_VERIFICATION), exclusive=exclusive, regular=regular, report=report,
            diarization_sha256=sha(diar_path), native_transcript_sha256=sha(native_path),
            implementation_sha256=sha(Path(__file__).resolve().parents[1]/'qualia/transcription/voice.py'),
            embedding_sha256=sha(Path(checkpoint)), device='cpu', threads=2, elapsed_seconds=time.monotonic()-begin))
        print(case['id'], 'vozes verificadas:',len(report['changes']),'revisões acústicas.',flush=True)


def export(config, root, out):
    for case in config["inputs"]:
        transcript = native(out / f'{case["id"]}.transcription.json')
        repeats = repeated_segment_runs(transcript["segments"])
        alignment = native(out / f'{case["id"]}.alignment.json')
        diar = native(out / f'{case["id"]}.diarization.json')
        original_diar = diar
        voice = None
        if config.get('voice_verification_policy') is not None:
            voice = native(out/f'{case["id"]}.voice.json')
            if (voice.get('policy') != config['voice_verification_policy']
                    or voice.get('diarization_sha256') != sha(out/f'{case["id"]}.diarization.json')
                    or voice.get('native_transcript_sha256') != sha(out/f'{case["id"]}.transcription.json')):
                raise ValueError('Verificação acústica não corresponde aos intermediários.')
            diar = dict(diar, exclusive=voice['exclusive'], regular=voice['regular'])
        words = [
            {**word, "source_segment": seg["source_segment"]}
            for seg in alignment["segments"]
            for word in seg["words"]
        ]
        assigned = assign_words(words, diar["exclusive"], diar["regular"])
        acoustic_labels = [w['speaker'] for w in assigned]
        pre_acoustic = assign_words(words, original_diar['exclusive'], original_diar['regular']) if voice is not None else None
        recovery = config.get('speaker_recovery_policy')
        if recovery is not None:
            recovery = speaker_recovery_policy(recovery)
            if config.get('speaker_refinement_policy') is not None:
                assigned = refine_speaker_assignments(assigned, diar['exclusive'], diar['regular'], recovery,
                                                      config['speaker_refinement_policy'])
            else:
                assigned = recover_speaker_gaps(assigned, diar['exclusive'], diar['regular'], recovery)
        voices = list(dict.fromkeys(r["speaker"] for r in original_diar["exclusive"]))
        detected_voices = len(voices)
        completion = config.get('speaker_completion_policy')
        if completion is not None:
            completion = completion_policy(completion)
            assigned = complete_speakers(assigned, diar['exclusive'], alignment['segments'])
            voices = list(dict.fromkeys(voices + [w['speaker'] for w in assigned if w['speaker']]))
        microturn = None
        if config.get('speaker_microturn_policy') is not None:
            assigned, microturn = reconcile_microturns(
                assigned, diar['exclusive'], diar['regular'], transcript['segments'], config['speaker_microturn_policy'])
        names = {v: f"Participant {i+1}" for i, v in enumerate(voices)}
        for i, row in enumerate(assigned):
            if voice is not None:
                previous = pre_acoustic[i]['speaker']
                row['raw_speaker_before_voice_verification'] = previous
                row['speaker_before_voice_verification'] = names.get(previous,'')
                changes = [c for c in voice['report']['changes'] if c['source_segment'] == row.get('source_segment')]
                if (previous != acoustic_labels[i] or (changes and not previous and row.get('assignment_method') == 'best_effort_completion')):
                    row['flags'] = list(dict.fromkeys(row['flags']+['speaker_acoustically_revised']))
                    row['speaker_acoustic_evidence'] = changes
            row["raw_speaker"] = row["speaker"]
            row["speaker"] = names.get(row["speaker"], "")
            if 'speaker_before_microturn' in row:
                row['raw_speaker_before_microturn'] = row['speaker_before_microturn']
                row['speaker_before_microturn'] = names.get(row['speaker_before_microturn'], '')
            if 'speaker_original' in row:
                row['raw_speaker_original'] = row['speaker_original']
                row['speaker_original'] = names.get(row['speaker_original'], '')
        rows = group_words(assigned, config["max_gap"])
        cues = subtitle_rows(assigned, max_gap=config["max_gap"],
                             native_segments=alignment['segments'] if completion is not None else None)
        stats = export_rows(
            rows, out / f'{case["id"]}.csv', out / f'{case["id"]}.vtt', vtt_rows=cues
        )
        export_text(rows, out / f'{case["id"]}.txt')
        save(out / f'{case["id"]}.assigned-words.json', assigned)
        save(out / f'{case["id"]}.rows.json', rows)
        save(out / f'{case["id"]}.review.json', [w for w in assigned if w["flags"]])
        original = " ".join(s["source_text"] for s in alignment["segments"]).split()
        assert " ".join(r["text"] for r in rows).split() == original
        assert len(assigned) == len(original)
        save(
            out / f'{case["id"]}.export.json',
            {
                **stats,
                "words": len(words),
                "words_with_time": sum(valid_interval(w) for w in assigned),
                "words_without_speaker": sum(not w["speaker"] for w in assigned),
                "speaker_completion_policy": completion,
                "speaker_microturn": microturn,
                "words_with_best_effort_speaker": sum(w.get('assignment_method') == 'best_effort_completion' for w in assigned),
                "native_subtitle_fallback": [r for r in cues if 'native_segment_timing' in r.get('flags', [])],
                "voice_verification": ({'policy':voice['policy'], 'status':voice['report']['status'],
                                         'changed_turns':voice['report']['changes'], 'device':'cpu', 'threads':2}
                                        if voice is not None else None),
                "speaker_recovery_policy": recovery,
                "speaker_refinement_policy": (refinement_policy(config['speaker_refinement_policy'])
                                               if config.get('speaker_refinement_policy') is not None else None),
                "words_with_inferred_speaker": sum('speaker_inferred' in w['flags'] for w in assigned),
                "words_crossing_speakers": sum(
                    "word_crosses_speakers" in w["flags"] for w in assigned
                ),
                "detected_speakers": detected_voices,
                "participant_labels": len(voices),
                "text_preserved": True,
                "native_repeat_runs": repeats,
                "native_internal_repetitions": internal_repetitions(transcript['segments']),
                "longest_flagged_identical_segment_run": max(
                    (r["count"] for r in repeats), default=0
                ),
            },
        )
        print(case["id"], stats, flush=True)


def seconds(value):
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def compare(config, root, out):
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    reports = []
    for case in config["inputs"]:
        if not case.get("reference"):
            continue
        with (root / case["reference"]).open(encoding="utf-8-sig", newline="") as f:
            refs = [
                {
                    "start": seconds(r["Start Time"]),
                    "end": seconds(r["End Time"]),
                    "speaker": r["Speaker"],
                }
                for r in csv.DictReader(f)
            ]
        words = native(out / f'{case["id"]}.assigned-words.json')
        speakers = sorted(set(w["speaker"] for w in words if w["speaker"]))
        targets = sorted(set(r["speaker"] for r in refs))
        scores = np.array(
            [
                [
                    sum(
                        overlap(w, r)
                        for w in words
                        if valid_interval(w) and w["speaker"] == v
                        for r in refs
                        if r["speaker"] == t
                    )
                    for t in targets
                ]
                for v in speakers
            ]
        )
        mapping = {}
        if speakers:
            left, right = linear_sum_assignment(-scores)
            mapping = {speakers[i]: targets[j] for i, j in zip(left, right)}
        per_speaker = {}
        baseline = native(root / case["baseline"]) if case.get("baseline") else None
        baseline_mapping = {}
        if baseline:
            baseline_names = sorted(set(b["speaker"] for b in baseline if b["speaker"]))
            matrix = np.zeros((len(baseline_names), len(targets)))
            for i, name in enumerate(baseline_names):
                for j, target in enumerate(targets):
                    for w in words:
                        if not valid_interval(w):
                            continue
                        for r in refs:
                            if r["speaker"] != target:
                                continue
                            start = max(w["start"], r["start"])
                            end = min(w["end"], r["end"])
                            if start < end:
                                matrix[i, j] += sum(
                                    overlap({"start": start, "end": end}, b)
                                    for b in baseline
                                    if b["speaker"] == name
                                )
            left, right = linear_sum_assignment(-matrix)
            baseline_mapping = {
                baseline_names[i]: targets[j] for i, j in zip(left, right)
            }
        for t in targets:
            compared = sum(
                overlap(w, r)
                for w in words
                if valid_interval(w)
                for r in refs
                if r["speaker"] == t
            )
            matched = sum(
                overlap(w, r)
                for w in words
                if valid_interval(w) and mapping.get(w["speaker"]) == t
                for r in refs
                if r["speaker"] == t
            )
            stats = {
                "compared_word_time_seconds": compared,
                "agreement_current": matched / compared if compared else None,
                "agreement_v2": matched / compared if compared else None,
            }
            if baseline:
                prior = 0
                for w in words:
                    if not valid_interval(w):
                        continue
                    for r in refs:
                        if r["speaker"] != t:
                            continue
                        start = max(w["start"], r["start"])
                        end = min(w["end"], r["end"])
                        if start >= end:
                            continue
                        interval = {"start": start, "end": end}
                        prior += sum(
                            overlap(interval, b)
                            for b in baseline
                            if baseline_mapping.get(b["speaker"]) == t
                        )
                stats["agreement_baseline_on_same_word_intervals"] = prior / compared if compared else None
                stats["agreement_v1_on_same_word_intervals"] = (
                    prior / compared if compared else None
                )
            per_speaker[t] = stats
        report = {
            "id": case["id"],
            "source": case["audio"],
            "reference_speakers": len(targets),
            "export": native(out / f'{case["id"]}.export.json'),
            "comparison_label_mapping_only": mapping,
            "unmatched_generated_speakers": [s for s in speakers if s not in mapping],
            "baseline_label_mapping_only": baseline_mapping,
            "reference_sha256": sha(root / case["reference"]),
            "per_reference_speaker": per_speaker,
            "warning": "Tempo de palavras alinhadas intersectando a referência; não DER/precisão contra áudio revisado. Contagem referência não entra no modelo.",
        }
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    save(out / "comparison.json", reports)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--stage",
        required=True,
        choices=["transcribe", "diarize", "align", "verify", "export", "compare"],
    )
    args = parser.parse_args()
    config = native(args.manifest)
    root = args.manifest.resolve().parent
    out = root / config["output"]
    out.mkdir(parents=True, exist_ok=True)
    signature = {
        "config": config,
        "sources": {x["id"]: sha(root / x["audio"]) for x in config["inputs"]},
    }
    state = out / "config-and-sources.json"
    if state.exists() and native(state) != signature:
        raise ValueError("Configuração/fontes mudaram; use nova rodada.")
    save(state, signature)
    {
        "transcribe": transcribe,
        "diarize": diarize,
        "align": align,
        "verify": verify,
        "export": export,
        "compare": compare,
    }[args.stage](config, root, out)


if __name__ == "__main__":
    main()
