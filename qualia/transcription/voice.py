"""Conservative two-view acoustic verification of isolated brief voice turns.

Importing this module does not load models. Text/reference transcripts are not
features: only native time intervals and audio embeddings are used.
"""
from copy import deepcopy

from .segments import overlap, valid_interval

DEFAULT_VOICE_VERIFICATION = dict(version=1, min_seconds=.4, max_seconds=2.,
                                min_gap=.25, reference_seconds=6., min_similarity=.1,
                                min_margin=.05, min_gain_over_original=.1,
                                min_source_share=.5, max_source_seconds=8.)


def references(turns, regular):
    """Three disjoint samples per detected voice, from its longest pure span."""
    output = []
    for voice in dict.fromkeys(t['speaker'] for t in turns):
        spans = []
        for turn in turns:
            if turn['speaker'] != voice or turn['end']-turn['start'] < 6.:
                continue
            parts = [(turn['start']+.25, turn['end']-.25)]
            for other in regular:
                if other['speaker'] == voice:
                    continue
                remaining = []
                for start, end in parts:
                    if min(end, other['end']) <= max(start, other['start']):
                        remaining.append((start, end))
                    else:
                        if start < other['start']:
                            remaining.append((start, min(end, other['start'])))
                        if end > other['end']:
                            remaining.append((max(start, other['end']), end))
                parts = remaining
            spans.extend((start,end) for start,end in parts if end-start >= 6.)
        if not spans:
            return []
        start, end = max(spans, key=lambda x:x[1]-x[0])
        length = min(12., end-start)
        start = (start+end-length)/2
        for i in range(3):
            output.append(dict(speaker=voice, start=start+i*length/3, end=start+(i+1)*length/3-.05))
    return output


def candidates(turns, regular):
    result = []
    for i, turn in enumerate(turns):
        duration = turn['end']-turn['start']
        left = turn['start']-turns[i-1]['end'] if i else float('inf')
        right = turns[i+1]['start']-turn['end'] if i+1<len(turns) else float('inf')
        if not .4 <= duration <= 2. or min(left, right) < .25:
            continue
        if any(t['speaker'] != turn['speaker'] and overlap(turn,t)>0 for t in regular):
            continue
        result.append(i)
    return result


def supported_change(original, turn_scores, source_scores, policy=None):
    policy = {**DEFAULT_VOICE_VERIFICATION, **(policy or {})}
    if not turn_scores or not source_scores or turn_scores[0]['speaker'] != source_scores[0]['speaker']:
        return None
    candidate = turn_scores[0]['speaker']
    if candidate == original:
        return None
    for scores in (turn_scores, source_scores):
        if len(scores) < 2 or scores[0]['cosine_similarity'] < policy['min_similarity']:
            return None
        if scores[0]['cosine_similarity']-scores[1]['cosine_similarity'] < policy['min_margin']:
            return None
        old = next((s['cosine_similarity'] for s in scores if s['speaker']==original), None)
        if old is None or scores[0]['cosine_similarity']-old < policy['min_gain_over_original']:
            return None
    return candidate


def verify_turns(turns, regular, native_segments, vector):
    """vector(region) returns an audio vector or None. Never reads transcript text."""
    import numpy as np
    refs = references(turns, regular)
    output = deepcopy(turns)
    report = dict(policy=dict(DEFAULT_VOICE_VERIFICATION), references=refs, decisions=[], changes=[],
                  reference_transcript_input=False)
    if not refs:
        report['status'] = 'insufficient_long_voice_references'
        return output, deepcopy(regular), report
    embeddings = [(r,vector(r)) for r in refs]
    if any(value is None for _,value in embeddings):
        report['status'] = 'invalid_reference_embedding'
        return output, deepcopy(regular), report
    voices = list(dict.fromkeys(r['speaker'] for r in refs))

    def ranking(value, exclude=None):
        if value is None:
            return []
        scores = []
        for voice in voices:
            members = [v for i,(r,v) in enumerate(embeddings) if r['speaker']==voice and i!=exclude]
            center = np.mean(members,axis=0)
            center /= np.linalg.norm(center)
            scores.append(dict(speaker=voice,cosine_similarity=float(value@center)))
        return sorted(scores,key=lambda s:s['cosine_similarity'],reverse=True)

    controls = []
    for i,(ref,value) in enumerate(embeddings):
        scores = ranking(value,exclude=i)
        controls.append(dict(speaker=ref['speaker'], ranking=scores,
                             consistent=bool(scores and scores[0]['speaker']==ref['speaker'])))
    report['reference_controls'] = controls
    if not all(c['consistent'] for c in controls):
        report['status'] = 'inconsistent_reference_voices'
        return output, deepcopy(regular), report
    sources = [dict(start=s.get('native_start',s.get('start')), end=s.get('native_end',s.get('end')),
                    source_segment=s.get('source_segment',i)) for i,s in enumerate(native_segments)]
    source_vectors = {}
    for i in candidates(turns,regular):
        turn = turns[i]
        viable = [s for s in sources if valid_interval(s) and .4<=s['end']-s['start']<=8.
                  and overlap(s,turn)/(turn['end']-turn['start']) >= .5]
        if not viable:
            continue
        source = max(viable,key=lambda s:overlap(s,turn))
        scores = ranking(vector(turn))
        key = source['source_segment']
        if key not in source_vectors:
            source_vectors[key] = vector(source)
        source_scores = ranking(source_vectors[key])
        candidate = supported_change(turn['speaker'],scores,source_scores)
        decision = dict(turn_index=i,original_speaker=turn['speaker'],source_segment=key,
                        start=turn['start'],end=turn['end'],turn_ranking=scores,source_ranking=source_scores,
                        proposed_speaker=candidate,accepted=bool(candidate))
        report['decisions'].append(decision)
        if candidate:
            output[i]['speaker'] = candidate
            report['changes'].append(decision)
    revised_regular = []
    for turn in regular:
        change = next((c for c in report['changes'] if c['original_speaker']==turn['speaker']
                       and overlap(c,turn)/(turn['end']-turn['start']) >= .95
                       and overlap(c,turn)/(c['end']-c['start']) >= .95),None)
        revised_regular.append(dict(turn,speaker=change['proposed_speaker']) if change else deepcopy(turn))
    report['status'] = 'completed'
    return output,revised_regular,report
