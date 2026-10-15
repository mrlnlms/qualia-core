"""Complete delivery labels from existing evidence, without acoustic inference."""
from collections import Counter
from copy import deepcopy

from .segments import overlap, valid_interval


def completion_policy(value=None):
    if value is not None and value != {'version': 1}:
        raise ValueError('Política de atribuição completa inválida.')
    return {'version': 1}


def complete_speakers(words, turns, native_segments=()):
    """Every word gets a best-effort label; unsupported labels require review.

    Original words and timestamps are immutable. New labels never become anchors
    within this pass. Speaker count is inherited from voices, never fixed at two.
    """
    result = deepcopy(words)
    turns = [t for t in turns if valid_interval(t) and t.get('speaker')]
    native = {s.get('source_segment', i): s for i, s in enumerate(native_segments)}
    known = [(i, w) for i, w in enumerate(words) if w.get('speaker')]
    durations = Counter()
    for t in turns:
        durations[t['speaker']] += t['end']-t['start']
    for i, word in enumerate(words):
        if word.get('speaker'):
            continue
        segment = word.get('source_segment')
        peers = [(j, w) for j, w in known if segment is not None and w.get('source_segment') == segment]
        votes = Counter(w['speaker'] for _, w in peers)
        source = native.get(segment, {})
        region = {'start': source.get('native_start', source.get('start')),
                  'end': source.get('native_end', source.get('end'))}
        scores = Counter()
        if valid_interval(region):
            for turn in turns:
                scores[turn['speaker']] += overlap(region, turn)
        scores = Counter({s: v for s, v in scores.items() if v > 0})
        left = next(((j, w) for j, w in reversed(known) if j < i), None)
        right = next(((j, w) for j, w in known if j > i), None)
        if votes:
            speaker = max(votes, key=lambda s: (votes[s], scores[s], durations[s]))
            basis = 'native_segment_word_consensus'
        elif scores:
            speaker = max(scores, key=lambda s: (scores[s], durations[s]))
            basis = 'native_segment_voice_overlap'
        elif left and right and left[1]['speaker'] == right[1]['speaker']:
            speaker = left[1]['speaker']
            basis = 'neighbor_agreement'
        elif left or right:
            def distance(anchor):
                j, other = anchor
                if valid_interval(word) and valid_interval(other):
                    return max(0., word['start']-other['end'], other['start']-word['end'])
                return abs(j-i)
            nearest = min([a for a in (left, right) if a], key=distance)
            speaker = nearest[1]['speaker']
            basis = 'nearest_original_word'
        elif turns and valid_interval(word):
            nearest = min(turns, key=lambda t: max(0., word['start']-t['end'], t['start']-word['end']))
            speaker = nearest['speaker']
            basis = 'nearest_voice_region'
        elif durations:
            speaker = durations.most_common(1)[0][0]
            basis = 'dominant_detected_voice'
        else:
            speaker = 'PROVISIONAL_00'
            basis = 'provisional_no_detected_voice'
        row = result[i]
        row['speaker_before_completion'] = word.get('speaker', '')
        row.setdefault('speaker_original', word.get('speaker', ''))
        row['assignment_before_completion'] = word.get('assignment_method', 'overlap')
        row['speaker'] = speaker
        row['assignment_method'] = 'best_effort_completion'
        row['speaker_review_required'] = True
        row['flags'] = list(dict.fromkeys(word.get('flags', []) + ['speaker_inferred', 'speaker_best_effort']))
        row['speaker_completion_evidence'] = {'basis': basis, 'source_segment': segment,
                                             'segment_word_votes': dict(votes),
                                             'segment_voice_overlap_seconds': dict(scores),
                                             'left_word_index': left[0] if left else None,
                                             'right_word_index': right[0] if right else None,
                                             'acoustically_verified': False}
    return result
