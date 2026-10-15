"""Política experimental de contexto, sem texto de referência ou modelos."""
import math

from .segments import overlap, valid_interval
from .speakers import recover_speaker_gaps

DEFAULT_SPEAKER_REFINEMENT = {
    'max_island_seconds': .75, 'min_alternative_seconds': .05,
    'min_alternative_share': .15, 'anchor_words': 3, 'context_seconds': 6.,
    'max_corridor_seconds': 3., 'max_short_turn_words': 3,
    'max_short_turn_seconds': 2., 'short_turn_pause_seconds': 1.5,
    'short_turn_missing_share': .5,
}


def refinement_policy(value=None):
    if value is not None and (not isinstance(value, dict) or set(value)-set(DEFAULT_SPEAKER_REFINEMENT)):
        raise ValueError('Política de contexto desconhecida.')
    result = {**DEFAULT_SPEAKER_REFINEMENT, **(value or {})}
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in result.values()):
        raise ValueError('Limites de contexto devem ser positivos e finitos.')
    if any(type(result[k]) is not int for k in ('anchor_words', 'max_short_turn_words')):
        raise ValueError('Contagens devem ser inteiras.')
    if result['min_alternative_share'] > 1 or result['short_turn_missing_share'] > 1:
        raise ValueError('Fração alternativa inválida.')
    return result


def refine_speaker_assignments(words, turns, regular_turns, recovery_policy=None, policy=None):
    """Uma passagem baseada exclusivamente nas atribuições originais.

    Corrige ilha de uma palavra somente com apoio temporal alternativo e três
    âncoras limpas por lado. Sobreposição simultânea e apoio exclusivo à voz
    minoritária impedem mudança. Respostas curtas com voz parcialmente ausente
    ficam pendentes, sem adivinhar a identidade de uma pessoa não detectada.
    """
    policy = refinement_policy(policy)
    result = recover_speaker_gaps(words, turns, regular_turns, recovery_policy)
    regular = [t for t in regular_turns if valid_interval(t)]
    short_segments = {}
    for i, word in enumerate(words):
        if word.get('source_segment') is not None:
            short_segments.setdefault(word['source_segment'], []).append(i)
    protected = set()
    for indices in short_segments.values():
        group = [words[i] for i in indices]
        if (len(group) > policy['max_short_turn_words'] or not all(valid_interval(w) for w in group)
                or not any(not w.get('speaker') for w in group)
                or group[-1]['end']-group[0]['start'] > policy['max_short_turn_seconds']):
            continue
        missing_time = sum(w['end']-w['start'] for w in group if not w.get('speaker'))
        total_time = sum(w['end']-w['start'] for w in group)
        if missing_time / total_time < policy['short_turn_missing_share']:
            continue
        first, last = indices[0], indices[-1]
        previous = words[first-1] if first else None
        following = words[last+1] if last+1 < len(words) else None
        isolated = ((previous is None or (valid_interval(previous) and group[0]['start']-previous['end'] >= policy['short_turn_pause_seconds']))
                    or (following is None or (valid_interval(following) and following['start']-group[-1]['end'] >= policy['short_turn_pause_seconds'])))
        if isolated:
            protected.update(indices)
            for i in indices:
                if words[i].get('speaker'):
                    continue
                row = result[i]
                if row.get('speaker'):
                    row['speaker_recovery_proposal'] = {'speaker': row['speaker'], 'method': row['assignment_method']}
                row['speaker'] = ''
                row['assignment_method'] = 'short_turn_abstention'
                row['flags'] = [f for f in row['flags'] if f != 'speaker_inferred'] + ['short_turn_requires_voice_review']
                row.pop('speaker_recovery_evidence', None)
                row['speaker_refinement_evidence'] = {'method': 'short_turn_abstention', 'source_segment': words[i]['source_segment'], 'policy': dict(policy)}

    runs = []
    for i, word in enumerate(words):
        if not word.get('speaker'):
            continue
        if runs and words[runs[-1][-1]]['speaker'] == word['speaker']:
            runs[-1].append(i)
        else:
            runs.append([i])

    def simultaneous(start, end):
        region = {'start': start, 'end': end}
        active = [t for t in regular if overlap(region, t) > 0]
        return any(a['speaker'] != b['speaker'] and min(a['end'],b['end'],end) > max(a['start'],b['start'],start)
                   for n,a in enumerate(active) for b in active[n+1:])

    def clean(i):
        return valid_interval(words[i]) and not set(words[i].get('flags', [])) & {
            'word_crosses_speakers', 'overlapping_voice_regions', 'speaker_inferred', 'unaligned_time'}

    for n in range(1, len(runs)-1):
        island, left_run, right_run = runs[n], runs[n-1], runs[n+1]
        if len(island) != 1 or island[0] in protected:
            continue
        i = island[0]; word = words[i]
        left, right = left_run[-1], right_run[0]
        candidate = words[left]['speaker']
        if candidate != words[right]['speaker'] or not all(valid_interval(words[j]) for j in range(left, right+1)):
            continue
        if word['end']-word['start'] > policy['max_island_seconds']:
            continue
        start, end = words[left]['end'], words[right]['start']
        if not (0 <= word['start']-start and 0 <= end-word['end'] and end-start <= policy['max_corridor_seconds']):
            continue
        scores = word.get('speaker_overlap_seconds', {})
        support = scores.get(candidate, 0.)
        if (set(scores)-{candidate, word['speaker']} or support < policy['min_alternative_seconds']
                or support / max(sum(scores.values()), 1e-12) < policy['min_alternative_share']
                or simultaneous(start, end)):
            continue
        left_anchors = [j for j in left_run if clean(j) and word['start']-words[j]['end'] <= policy['context_seconds']]
        right_anchors = [j for j in right_run if clean(j) and words[j]['start']-word['end'] <= policy['context_seconds']]
        if min(len(left_anchors),len(right_anchors)) < policy['anchor_words']:
            continue
        evidence = {'method': 'short_ambiguous_speaker_island', 'island_word_index': i,
                    'original_speaker': word['speaker'], 'context_speaker': candidate,
                    'left_anchor_indices': left_anchors[-policy['anchor_words']:],
                    'right_anchor_indices': right_anchors[:policy['anchor_words']],
                    'alternative_overlap_seconds': support, 'corridor_start': start,
                    'corridor_end': end, 'policy': dict(policy)}
        for j in range(left+1, right):
            if j in protected or (j != i and words[j].get('speaker')):
                continue
            row = result[j]
            if j != i and 'no_voice_overlap' not in words[j].get('flags', []):
                continue
            row['speaker'] = candidate
            row['assignment_method'] = 'short_ambiguous_speaker_island' if j == i else 'reconciled_island_gap'
            row['flags'] = list(dict.fromkeys(row['flags'] + ['speaker_inferred', 'speaker_context_reconciled']))
            row['speaker_refinement_evidence'] = {**evidence, 'method': row['assignment_method']}
    return result
