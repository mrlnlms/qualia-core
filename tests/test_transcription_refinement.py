from copy import deepcopy

from qualia.transcription.segments import assign_words
from qualia.transcription.refinement import refine_speaker_assignments


def fixture():
    turns=[{'speaker':'A','start':0.,'end':1.}, {'speaker':'B','start':1.,'end':1.25}, {'speaker':'A','start':1.25,'end':3.}]
    words=assign_words([{'word':str(i),'start':i*.2,'end':i*.2+.15} for i in range(4)] +
                      [{'word':'x','start':.95,'end':1.3}] +
                      [{'word':str(i),'start':1.4+i*.2,'end':1.55+i*.2} for i in range(4)],turns,turns)
    return words,turns


def test_ambiguous_island_is_reconciled_without_mutating_text_times_or_input():
    words,turns=fixture();before=deepcopy(words)
    result=refine_speaker_assignments(words,turns,turns)
    assert result[4]['speaker']=='A'
    assert result[4]['speaker_original']=='B'
    assert result[4]['assignment_method']=='short_ambiguous_speaker_island'
    assert words==before
    assert [(w['word'],w['start'],w['end']) for w in result]==[(w['word'],w['start'],w['end']) for w in words]


def test_genuine_short_turn_with_exclusive_support_is_preserved():
    words,turns=fixture();words[4]['speaker_overlap_seconds']={'B':.35}
    assert refine_speaker_assignments(words,turns,turns)[4]['speaker']=='B'


def test_simultaneous_voices_are_not_smoothed():
    words,turns=fixture();regular=turns+[{'speaker':'A','start':1.,'end':1.25}]
    assert refine_speaker_assignments(words,turns,regular)[4]['speaker']=='B'


def test_short_partially_detected_response_stays_unknown_instead_of_inheriting_voice():
    turns=[{'speaker':'A','start':0.,'end':1.}, {'speaker':'A','start':1.7,'end':2.}, {'speaker':'A','start':4.,'end':6.}]
    raw=[{'word':'start','start':.2,'end':.8,'source_segment':0},
         {'word':'reply','start':1.01,'end':1.6,'source_segment':1},
         {'word':'end','start':1.8,'end':1.95,'source_segment':1},
         {'word':'next','start':4.1,'end':4.5,'source_segment':2}]
    result=refine_speaker_assignments(assign_words(raw,turns),turns,turns)
    assert result[1]['speaker']==''
    assert result[1]['assignment_method']=='short_turn_abstention'
    assert result[2]['speaker']=='A'


def test_small_missing_part_of_short_segment_is_not_mistaken_for_missed_response():
    turns=[{'speaker':'A','start':0.,'end':1.}, {'speaker':'A','start':1.3,'end':2.5}, {'speaker':'A','start':5.,'end':6.}]
    raw=[{'word':'before','start':.5,'end':.9,'source_segment':0},
         {'word':'brief','start':1.02,'end':1.1,'source_segment':1},
         {'word':'longer','start':1.4,'end':2.2,'source_segment':1},
         {'word':'next','start':5.1,'end':5.5,'source_segment':2}]
    result=refine_speaker_assignments(assign_words(raw,turns),turns,turns)
    assert result[1]['speaker']=='A'
    assert result[1]['assignment_method']=='near_voice_boundary'
