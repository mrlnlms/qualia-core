"""Recuperação experimental de lacunas, sem modelos, referência ou alteração textual."""
import math

from .segments import overlap, valid_interval


DEFAULT_SPEAKER_RECOVERY = {'boundary_tolerance_seconds': .15,
                            'max_bridge_seconds': 3., 'max_neighbor_gap_seconds': 1.5}


def speaker_recovery_policy(value=None):
    if value is not None and (not isinstance(value, dict) or set(value) - set(DEFAULT_SPEAKER_RECOVERY)):
        raise ValueError('Política de recuperação de falantes inválida.')
    policy = {**DEFAULT_SPEAKER_RECOVERY, **(value or {})}
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in policy.values()):
        raise ValueError('Limites de recuperação devem ser números finitos não negativos.')
    return policy


def recover_speaker_gaps(words, turns, regular_turns=None, policy=None):
    """Preenche apenas lacunas entre vozes concordantes; âncoras nunca são inferidas.

    Bordas: grupo curto próximo de voz, sem concorrente na margem temporal.
    Ponte: palavras originais dos dois lados concordam, com pausas limitadas e
    sem outra voz em todo o contexto. Campos originais e flags são preservados.
    Os métodos são evidência heurística, não probabilidades de confiança.
    """
    policy = speaker_recovery_policy(policy)
    result = [{**word, 'flags': list(word.get('flags', [])),
               'speaker_original': word.get('speaker', ''),
               'assignment_method': 'overlap' if word.get('speaker') else 'unassigned'} for word in words]
    turns = [t for t in turns if valid_interval(t) and t.get('speaker')]
    regular = [t for t in (regular_turns if regular_turns is not None else turns)
               if valid_interval(t) and t.get('speaker')]

    def has_other_voice(start, end, speaker):
        region = {'start': max(0., start), 'end': end}
        return any(t['speaker'] != speaker and overlap(region, t) > 0 for t in regular)

    index = 0
    while index < len(words):
        if words[index].get('speaker'):
            index += 1
            continue
        first = index
        while index < len(words) and not words[index].get('speaker'):
            index += 1
        group = words[first:index]
        if any(not valid_interval(w) or 'no_voice_overlap' not in w.get('flags', [])
               or {'speaker_tie', 'overlapping_voice_regions'} & set(w.get('flags', [])) for w in group):
            continue
        if any(a['end'] > b['start'] for a, b in zip(group, group[1:])):
            continue
        start, end = group[0]['start'], group[-1]['end']
        # Reject malformed/inconsistent original assignments, including hidden overlap.
        region = {'start': start, 'end': end}
        if any(overlap(region, t) > 0 for t in turns):
            continue
        before = [t for t in turns if t['end'] <= start]
        after = [t for t in turns if t['start'] >= end]
        if not before or not after:
            continue
        latest = max(t['end'] for t in before)
        earliest = min(t['start'] for t in after)
        left = {t['speaker'] for t in before if math.isclose(t['end'], latest, abs_tol=1e-8, rel_tol=0)}
        right = {t['speaker'] for t in after if math.isclose(t['start'], earliest, abs_tol=1e-8, rel_tol=0)}
        if len(left) != 1 or left != right:
            continue
        speaker = next(iter(left))
        left_gap, right_gap = start-latest, earliest-end
        tolerance = policy['boundary_tolerance_seconds']
        method = None
        if (end-start <= policy['max_neighbor_gap_seconds']
                and min(left_gap, right_gap) <= tolerance
                and not has_other_voice(start-tolerance, end+tolerance, speaker)):
            method = 'near_voice_boundary'
        if method is None and first > 0 and index < len(words):
            previous, following = words[first-1], words[index]
            if (valid_interval(previous) and valid_interval(following)
                    and previous.get('speaker') == following.get('speaker') == speaker
                    and end-start <= policy['max_bridge_seconds']
                    and 0 <= start-previous['end'] <= policy['max_neighbor_gap_seconds']
                    and 0 <= following['start']-end <= policy['max_neighbor_gap_seconds']
                    and not has_other_voice(previous['start'], following['end'], speaker)):
                method = 'same_voice_bridge'
        if method:
            evidence = {'method': method, 'left_voice': speaker, 'right_voice': speaker,
                        'left_distance_seconds': left_gap, 'right_distance_seconds': right_gap,
                        'group_start': start, 'group_end': end, 'policy': dict(policy)}
            for position in range(first, index):
                result[position]['speaker'] = speaker
                result[position]['assignment_method'] = method
                result[position]['speaker_recovery_evidence'] = {**evidence, 'policy': dict(policy)}
                result[position]['flags'].append('speaker_inferred')
    return result
