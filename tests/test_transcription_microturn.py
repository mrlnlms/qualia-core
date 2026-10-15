from copy import deepcopy

import pytest

from qualia.transcription.microturn import reconcile_microturns


def fixture():
    turns = [dict(start=0., end=5., speaker='A'), dict(start=6., end=6.3, speaker='C'),
             dict(start=7., end=12., speaker='A')]
    native = [dict(start=4.9, end=6.4)]
    words = [dict(word='arbitrary', start=5.8, end=5.9, source_segment=0, speaker='C',
                  assignment_method='best_effort_completion', speaker_before_completion='',
                  speaker_original='', flags=['speaker_inferred'],
                  speaker_completion_evidence={'basis':'native_segment_word_consensus'}),
             dict(word='text', start=6., end=6.2, source_segment=0, speaker='C',
                  speaker_original='C', assignment_method='overlap', flags=[])]
    return words, turns, native


def test_partially_detected_tiny_island_uses_continuity_without_mutating_sources():
    words, turns, native = fixture()
    before = deepcopy((words, turns, native))
    revised, report = reconcile_microturns(words, turns, turns, native)
    assert [w['speaker'] for w in revised] == ['A', 'A']
    assert (words, turns, native) == before
    assert [(w['word'],w['start'],w['end']) for w in revised] == [(w['word'],w['start'],w['end']) for w in words]
    assert revised[1]['speaker_original'] == 'C'
    assert all(w['assignment_method'] == 'subsecond_voice_continuity' for w in revised)
    assert all(w['speaker_microturn_evidence']['acoustically_verified'] is False for w in revised)
    assert len(report['changes']) == 1


@pytest.mark.parametrize('failure', ['fully_detected','different_neighbors','simultaneous',
                                    'no_context_support','longer_turn','no_direct_word'])
def test_real_short_replies_and_unsupported_context_are_preserved(failure):
    words, turns, native = fixture()
    regular = deepcopy(turns)
    if failure == 'fully_detected':
        words[0]['assignment_method'] = 'overlap'
    elif failure == 'different_neighbors':
        turns[-1]['speaker'] = 'B'
    elif failure == 'simultaneous':
        regular.append(dict(start=6.1,end=6.3,speaker='B'))
    elif failure == 'no_context_support':
        native[0]['start'] = 5.1
    elif failure == 'longer_turn':
        turns[1]['end'] = 6.5
    elif failure == 'no_direct_word':
        words[1]['assignment_method'] = 'near_voice_boundary'
    revised, report = reconcile_microturns(words, turns, regular, native)
    assert revised == words
    assert report['changes'] == []


def test_unknown_policy_rejected():
    words, turns, native = fixture()
    with pytest.raises(ValueError):
        reconcile_microturns(words, turns, turns, native, {'version':2})
