"""Validação estrutural dos CSV/VTT e da proveniência, sem carregar modelos."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qualia.transcription.segments import valid_interval, repeated_segment_runs, plain_text, assign_words
from qualia.transcription.speakers import recover_speaker_gaps, speaker_recovery_policy
from qualia.transcription.refinement import refine_speaker_assignments, refinement_policy
from qualia.transcription.completion import complete_speakers, completion_policy
from qualia.transcription.microturn import reconcile_microturns
from qualia.transcription.voice import DEFAULT_VOICE_VERIFICATION, candidates, supported_change
from qualia.transcription.decoder import decoder_params, transcription_policy
from qualia.transcription.audit import internal_repetitions
from qualia.transcription.speech import recognition_window, window_matches


def read(path):
    return json.loads(path.read_text())


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def seconds(value):
    h, m, s = value.split(':')
    return int(h)*3600+int(m)*60+float(s)


def validate_case(config, root, out, case):
    stem = case['id']
    transcript_path = out/f'{stem}.transcription.json'
    transcript = read(transcript_path)
    alignment = read(out/f'{stem}.alignment.json')
    assigned = read(out/f'{stem}.assigned-words.json')
    diar = read(out/f'{stem}.diarization.json')
    export = read(out/f'{stem}.export.json')
    review = read(out/f'{stem}.review.json')
    duration = transcript['audio_duration_seconds']
    native_words = ' '.join(s['text'] for s in transcript['segments']).split()
    aligned_words = [{**w, 'source_segment': seg.get('source_segment')}
                     for seg in alignment['segments'] for w in seg['words']]
    with (out/f'{stem}.csv').open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames
        rows = list(reader)
    csv_words = ' '.join(row['Text'] for row in rows).split()
    invalid_csv = []
    timed_csv = []
    for i, row in enumerate(rows):
        start, end = row['Start Time'], row['End Time']
        if not start and not end:
            continue
        if not start or not end:
            invalid_csv.append(i)
            continue
        interval = {'start': seconds(start), 'end': seconds(end)}
        if not valid_interval(interval) or interval['end'] > duration+.05:
            invalid_csv.append(i)
        timed_csv.append(interval)
    raw_vtt = (out/f'{stem}.vtt').read_text()
    cues = []
    vtt_words = []
    invalid_vtt = []
    for block in raw_vtt.split('\n\n'):
        lines = block.strip().splitlines()
        if not lines or lines[0] == 'WEBVTT':
            continue
        start, end = lines[0].split(' --> ')
        interval = {'start': seconds(start), 'end': seconds(end)}
        if not valid_interval(interval) or interval['end'] > duration+.05:
            invalid_vtt.append(len(cues))
        cues.append(interval)
        text = '\n'.join(lines[1:])
        text = re.sub(r'^<v [^>]*>', '', text)
        if text.endswith('</v>'):
            text = text[:-4]
        vtt_words.extend(html.unescape(text).split())
    policy = decoder_params(config.get('decoder_params'))
    expected_window = None
    if config.get('speech_boundary_policy') is not None:
        expected_window = recognition_window(round(duration*16000), diar['regular'],
                                             config['speech_boundary_policy'], sha(out/f'{stem}.diarization.json'))
    internal = internal_repetitions(transcript['segments'])
    native_by_segment = {s.get('source_segment', i): s for i, s in enumerate(alignment['segments'])}
    def in_vtt(word):
        if valid_interval(word):
            return True
        source = native_by_segment.get(word.get('source_segment'), {})
        return config.get('speaker_completion_policy') is not None and valid_interval(
            {'start': source.get('native_start'), 'end': source.get('native_end')})
    checks = {
        'source_sha256': transcript['source_sha256'] == sha(root/case['audio']),
        'diarization_source_sha256': diar['source_sha256'] == transcript['source_sha256'],
        'automatic_speaker_count': config.get('num_speakers') is None and diar.get('speaker_options') == {},
        'decoder_policy': transcription_policy(transcript) == policy,
        'recognition_window': window_matches(transcript, expected_window),
        'alignment_transcript_hash': alignment['native_transcript_sha256'] == sha(transcript_path),
        'alignment_text_preserved': ' '.join(w['word'] for w in aligned_words).split() == native_words,
        'assignment_text_preserved': ' '.join(w['word'] for w in assigned).split() == native_words,
        'csv_header': header == ['Speaker','Start Time','End Time','Text'],
        'csv_text_preserved': csv_words == native_words,
        'vtt_header': raw_vtt.startswith('WEBVTT\n'),
        'vtt_timed_text_preserved': vtt_words == ' '.join(w['word'] for w in assigned if in_vtt(w)).split(),
        'csv_valid_bounds': not invalid_csv,
        'vtt_valid_bounds': not invalid_vtt,
        'vtt_nondecreasing_starts': all(a['start'] <= b['start'] for a,b in zip(cues,cues[1:])),
        'review_preserved': review == [w for w in assigned if w['flags']],
        'export_word_count': export['words'] == len(assigned),
        'export_native_repeat_audit': export['native_repeat_runs'] == repeated_segment_runs(transcript['segments']),
        'export_internal_repeat_audit': export.get('native_internal_repetitions', internal) == internal,
    }
    text_path = out/f'{stem}.txt'
    if config.get('voice_verification_policy') is not None:
        voice = read(out/f'{stem}.voice.json')
        report = voice['report']
        checks['voice_policy'] = voice.get('policy') == config['voice_verification_policy'] == DEFAULT_VOICE_VERIFICATION
        checks['voice_input_hashes'] = (voice.get('diarization_sha256') == sha(out/f'{stem}.diarization.json')
                                        and voice.get('native_transcript_sha256') == sha(transcript_path))
        checks['voice_implementation_hash'] = voice.get('implementation_sha256') == sha(Path(__file__).resolve().parents[1]/'qualia/transcription/voice.py')
        expected_turns = [dict(t) for t in diar['exclusive']]
        eligible = set(candidates(diar['exclusive'],diar['regular']))
        changes_valid = True
        for change in report.get('changes', []):
            i = change.get('turn_index')
            if type(i) is not int or i not in eligible:
                changes_valid = False
                continue
            original_turn = diar['exclusive'][i]
            expected_speaker = supported_change(original_turn['speaker'],change['turn_ranking'],change['source_ranking'])
            if not expected_speaker or expected_speaker != change.get('proposed_speaker'):
                changes_valid = False
            expected_turns[i]['speaker'] = expected_speaker
        checks['voice_changes_supported'] = changes_valid and expected_turns == voice['exclusive']
        checks['voice_summary_recorded'] = export.get('voice_verification',{}).get('changed_turns') == report.get('changes',[])
        diar = dict(diar,exclusive=voice['exclusive'],regular=voice['regular'])
    recovery = config.get('speaker_recovery_policy')
    if recovery is not None:
        recovery = speaker_recovery_policy(recovery)
        original = assign_words(aligned_words, diar['exclusive'], diar['regular'])
        refinement = config.get('speaker_refinement_policy')
        if refinement is not None:
            refinement = refinement_policy(refinement)
            expected = refine_speaker_assignments(original, diar['exclusive'], diar['regular'], recovery, refinement)
            checks['speaker_refinement_policy_recorded'] = export.get('speaker_refinement_policy') == refinement
        else:
            expected = recover_speaker_gaps(original, diar['exclusive'], diar['regular'], recovery)
        if config.get('speaker_completion_policy') is not None:
            expected = complete_speakers(expected, diar['exclusive'], alignment['segments'])
        if config.get('speaker_microturn_policy') is not None:
            expected, microturn_report = reconcile_microturns(
                expected, diar['exclusive'], diar['regular'], transcript['segments'], config['speaker_microturn_policy'])
        checks['speaker_recovery_policy_recorded'] = export.get('speaker_recovery_policy') == recovery
        checks['speaker_recovery_reproducible'] = len(assigned) == len(expected) and all(
            a.get('raw_speaker') == e['speaker']
            and a.get('raw_speaker_original') == o['speaker']
            and a.get('assignment_method') == e['assignment_method']
            and a.get('speaker_recovery_evidence') == e.get('speaker_recovery_evidence')
            and a.get('speaker_refinement_evidence') == e.get('speaker_refinement_evidence')
            and a.get('speaker_completion_evidence') == e.get('speaker_completion_evidence')
            and a.get('speaker_microturn_evidence') == e.get('speaker_microturn_evidence')
            and ('speaker_inferred' in a['flags']) == ('speaker_inferred' in e['flags'])
            and (a.get('start'), a.get('end')) == (o.get('start'), o.get('end'))
            for a, e, o in zip(assigned, expected, original))
        if refinement is None:
            checks['direct_speaker_assignments_preserved'] = all(
                not o['speaker'] or a.get('raw_speaker') == o['speaker']
                or a.get('speaker_microturn_evidence') for a, o in zip(assigned, original))
        else:
            checks['direct_speaker_changes_justified'] = all(
                not o['speaker'] or a.get('raw_speaker') == o['speaker']
                or a.get('speaker_microturn_evidence')
                or (a.get('assignment_method') == 'short_ambiguous_speaker_island' and a.get('speaker_refinement_evidence'))
                for a,o in zip(assigned,original))
        checks['inferred_speaker_count'] = export.get('words_with_inferred_speaker') == sum(
            'speaker_inferred' in w['flags'] for w in assigned)
    if config.get('speaker_completion_policy') is not None:
        completion = completion_policy(config['speaker_completion_policy'])
        original = assign_words(aligned_words, diar['exclusive'], diar['regular'])
        if recovery is not None:
            before_completion = (refine_speaker_assignments(original, diar['exclusive'], diar['regular'], recovery, config['speaker_refinement_policy'])
                                 if config.get('speaker_refinement_policy') is not None
                                 else recover_speaker_gaps(original, diar['exclusive'], diar['regular'], recovery))
        else:
            before_completion = original
        expected_complete = complete_speakers(before_completion, diar['exclusive'], alignment['segments'])
        if config.get('speaker_microturn_policy') is not None:
            expected_complete, microturn_report = reconcile_microturns(
                expected_complete, diar['exclusive'], diar['regular'], transcript['segments'], config['speaker_microturn_policy'])
            checks['microturn_report_reproducible'] = export.get('speaker_microturn') == microturn_report
            checks['microturn_evidence_reproducible'] = all(
                a.get('speaker_microturn_evidence') == e.get('speaker_microturn_evidence')
                and a.get('raw_speaker_before_microturn') == e.get('speaker_before_microturn')
                and a.get('assignment_before_microturn') == e.get('assignment_before_microturn')
                and a.get('assignment_method') == e.get('assignment_method')
                and ('speaker_inferred' in a['flags']) == ('speaker_inferred' in e['flags'])
                for a,e in zip(assigned,expected_complete))
        checks['complete_speaker_labels'] = all(w.get('speaker') for w in assigned)
        checks['completion_policy_recorded'] = export.get('speaker_completion_policy') == completion
        checks['completion_reproducible'] = len(assigned) == len(expected_complete) and all(
            a.get('raw_speaker') == e['speaker']
            and a.get('speaker_completion_evidence') == e.get('speaker_completion_evidence')
            and a.get('speaker_review_required') == e.get('speaker_review_required')
            and (a.get('start'), a.get('end')) == (e.get('start'), e.get('end'))
            for a, e in zip(assigned, expected_complete))
    if text_path.exists():
        csv_blocks = [{'speaker': row['Speaker'], 'text': row['Text']} for row in rows]
        checks['txt_text_and_speakers_preserved'] = text_path.read_text(encoding='utf-8') == plain_text(csv_blocks)
    return {'id':stem, 'status':'passed' if all(checks.values()) else 'failed', 'checks':checks,
            'native_words':len(native_words), 'aligned_timed_words':sum(valid_interval(w) for w in assigned),
            'words_without_time':sum(not valid_interval(w) for w in assigned),
            'words_without_speaker':sum(not w['speaker'] for w in assigned),
            'words_with_inferred_speaker':sum('speaker_inferred' in w['flags'] for w in assigned),
            'detected_speakers':diar['detected_speakers'], 'csv_rows':len(rows), 'vtt_cues':len(cues),
            'invalid_csv_rows':invalid_csv, 'invalid_vtt_cues':invalid_vtt,
            'time_bounds_numeric_tolerance_seconds':.05,
            'warning':'Verificação estrutural; não comprova correção textual/identidade de falantes nem substitui revisão humana.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    config = read(args.manifest)
    root = args.manifest.resolve().parent
    out = root/config['output']
    cases = [validate_case(config,root,out,case) for case in config['inputs']]
    report = {'status':'passed' if all(c['status']=='passed' for c in cases) else 'failed', 'cases':cases}
    (out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if report['status']!='passed':
        raise SystemExit(1)


if __name__=='__main__':
    main()
