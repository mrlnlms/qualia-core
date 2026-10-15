"""Contextual recovery of partly detected utterances around tiny voice islands.

This is temporal inference, not acoustic verification. Transcript text and
reference transcripts are never features. Fully detected short replies stay
untouched, even when surrounding turns belong to another voice.
"""
from copy import deepcopy

from .segments import overlap, valid_interval


DEFAULT_MICROTURN_POLICY = {'version': 1}
LIMITS = dict(max_turn_seconds=.4, min_anchor_seconds=2., max_neighbor_gap_seconds=1.5,
              min_source_seconds=.4, max_source_seconds=3., min_turn_source_share=.5,
              min_context_support_seconds=.05, max_source_words=3)


def microturn_policy(value=None):
    if value is not None and value != DEFAULT_MICROTURN_POLICY:
        raise ValueError('Política de continuidade de voz desconhecida.')
    return dict(DEFAULT_MICROTURN_POLICY)


def reconcile_microturns(words, turns, regular, native_segments, policy=None):
    policy = microturn_policy(policy)
    result = deepcopy(words)
    report = dict(policy=policy, limits=dict(LIMITS), changes=[], acoustically_verified=False)
    groups = {}
    for i, word in enumerate(words):
        groups.setdefault(word.get('source_segment'), []).append(i)
    sources = {s.get('source_segment', i): s for i, s in enumerate(native_segments)}
    for i in range(1, len(turns)-1):
        left, turn, right = turns[i-1:i+2]
        if not all(valid_interval(t) for t in (left, turn, right)):
            continue
        duration = turn['end']-turn['start']
        candidate = left['speaker']
        if not (duration < LIMITS['max_turn_seconds'] and candidate == right['speaker']
                and candidate != turn['speaker']):
            continue
        if min(left['end']-left['start'], right['end']-right['start']) < LIMITS['min_anchor_seconds']:
            continue
        if not (0 <= turn['start']-left['end'] <= LIMITS['max_neighbor_gap_seconds']
                and 0 <= right['start']-turn['end'] <= LIMITS['max_neighbor_gap_seconds']):
            continue
        if any(t['speaker'] != turn['speaker'] and overlap(turn, t) > 0 for t in regular):
            continue
        for source_id, source in sources.items():
            indices = groups.get(source_id, [])
            if not indices or len(indices) > LIMITS['max_source_words'] or not valid_interval(source):
                continue
            if not (LIMITS['min_source_seconds'] <= source['end']-source['start'] <= LIMITS['max_source_seconds']
                    and overlap(source, turn)/duration >= LIMITS['min_turn_source_share']):
                continue
            group = [words[j] for j in indices]
            # A native consensus amplified a gap: this is not a wholly detected
            # short response that could legitimately belong to a different voice.
            gaps = [j for j in indices if words[j].get('assignment_method') == 'best_effort_completion'
                    and words[j].get('speaker_before_completion') == ''
                    and words[j].get('speaker_completion_evidence', {}).get('basis') == 'native_segment_word_consensus']
            direct = [j for j in indices if words[j].get('assignment_method', 'overlap') == 'overlap'
                      and valid_interval(words[j]) and overlap(words[j], turn) > 0]
            if not gaps or not direct or any(w.get('speaker') != turn['speaker'] for w in group):
                continue
            support = sum(overlap(source, t) for t in turns if t['speaker'] == candidate)
            if support < LIMITS['min_context_support_seconds']:
                continue
            # Reject a competing real voice anywhere in the native segment.
            active = [t for t in regular if overlap(t, source) > 0]
            if any(a['speaker'] != b['speaker'] and min(a['end'], b['end'], source['end'])
                   > max(a['start'], b['start'], source['start'])
                   for n, a in enumerate(active) for b in active[n+1:]):
                continue
            evidence = dict(turn_index=i, source_segment=source_id, word_indices=indices,
                            original_speaker=turn['speaker'], proposed_speaker=candidate,
                            start=turn['start'], end=turn['end'], context_support_seconds=support,
                            gap_word_indices=gaps, direct_word_indices=direct,
                            acoustically_verified=False)
            report['changes'].append(evidence)
            for j in indices:
                row = result[j]
                row.setdefault('speaker_original', row['speaker'])
                row['speaker_before_microturn'] = row['speaker']
                row['assignment_before_microturn'] = row.get('assignment_method', 'overlap')
                row['speaker'] = candidate
                row['assignment_method'] = 'subsecond_voice_continuity'
                row['speaker_review_required'] = True
                row['flags'] = list(dict.fromkeys(row.get('flags', []) + ['speaker_inferred', 'speaker_context_reconciled']))
                row['speaker_microturn_evidence'] = deepcopy(evidence)
    return result, report
