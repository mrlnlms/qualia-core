"""Inferência de voz apenas em lacunas limitadas; nunca altera âncoras/texto/tempos."""
from copy import deepcopy

import pytest

from qualia.transcription.segments import assign_words
from qualia.transcription.speakers import recover_speaker_gaps


def test_close_boundary_recovers_without_editing_source():
    turns = [{'speaker': 'C', 'start': 0., 'end': 1.}, {'speaker': 'C', 'start': 1.3, 'end': 2.}]
    words = assign_words([{'word': 'ponte', 'start': 1.02, 'end': 1.1}], turns)
    original = deepcopy(words)
    result = recover_speaker_gaps(words, turns, turns)
    assert result[0]['speaker'] == 'C'
    assert result[0]['speaker_original'] == ''
    assert result[0]['assignment_method'] == 'near_voice_boundary'
    assert {'no_voice_overlap', 'speaker_inferred'} <= set(result[0]['flags'])
    assert words == original


def test_short_phrase_is_bridged_by_original_words_of_same_voice():
    turns = [{'speaker': 'B', 'start': 0., 'end': 1.}, {'speaker': 'B', 'start': 3.4, 'end': 5.}]
    words = assign_words([{'word': 'antes', 'start': .5, 'end': .9},
                          {'word': 'uma', 'start': 1.6, 'end': 2.},
                          {'word': 'frase', 'start': 2.1, 'end': 2.8},
                          {'word': 'depois', 'start': 3.5, 'end': 4.}], turns)
    result = recover_speaker_gaps(words, turns, turns)
    assert [w['speaker'] for w in result] == ['B'] * 4
    assert [w['assignment_method'] for w in result] == ['overlap', 'same_voice_bridge', 'same_voice_bridge', 'overlap']
    assert [(w.get('start'), w.get('end'), w['word']) for w in result] == [(w.get('start'), w.get('end'), w['word']) for w in words]


@pytest.mark.parametrize('reason', ['speaker_change', 'concurrent_voice', 'long_word', 'missing_time', 'missing_right_anchor', 'tie'])
def test_ambiguous_or_invalid_word_remains_unknown(reason):
    turns = [{'speaker': 'A', 'start': 0., 'end': 1.}, {'speaker': 'A', 'start': 1.3, 'end': 2.}]
    word = {'word': 'incerta', 'start': 1.01, 'end': 1.1}
    regular = deepcopy(turns)
    if reason == 'speaker_change':
        turns[1]['speaker'] = 'B'
    elif reason == 'concurrent_voice':
        regular.append({'speaker': 'B', 'start': 1., 'end': 1.2})
    elif reason == 'long_word':
        word['end'] = 10.
        turns[1].update(start=10.1, end=11.)
    elif reason == 'missing_time':
        word.pop('start')
    elif reason == 'missing_right_anchor':
        turns.pop()
    elif reason == 'tie':
        turns = [{'speaker': speaker, 'start': 1., 'end': 1.2} for speaker in ('A', 'B')]
    words = assign_words([word], turns, regular)
    assert recover_speaker_gaps(words, turns, regular)[0]['speaker'] == ''


def test_direct_assignments_and_three_speakers_never_change():
    turns = [{'speaker': str(i), 'start': float(i), 'end': float(i+1)} for i in range(3)]
    words = assign_words([{'word': str(i), 'start': i+.1, 'end': i+.8} for i in range(3)], turns)
    assert [w['speaker'] for w in recover_speaker_gaps(words, turns, turns)] == ['0', '1', '2']


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        recover_speaker_gaps([], [], policy={'boundary_tolerance_seconds': float('inf')})


def test_bridge_rejects_other_voice_in_context_even_outside_unknown_words():
    turns = [{'speaker': 'A', 'start': 0., 'end': 1.}, {'speaker': 'A', 'start': 3.4, 'end': 5.}]
    words = assign_words([{'word': 'antes', 'start': .5, 'end': .9},
                          {'word': 'trecho', 'start': 1.6, 'end': 2.8},
                          {'word': 'depois', 'start': 3.5, 'end': 4.}], turns)
    regular = turns + [{'speaker': 'C', 'start': .7, 'end': .8}]
    result = recover_speaker_gaps(words, turns, regular)
    assert result[1]['speaker'] == ''


def test_equal_nearest_turns_from_multiple_voices_do_not_choose_one():
    turns = [{'speaker': s, 'start': 0., 'end': 1.} for s in ('A', 'B')]
    turns.append({'speaker': 'A', 'start': 1.3, 'end': 2.})
    words = assign_words([{'word': 'incerta', 'start': 1.01, 'end': 1.1}], turns)
    assert recover_speaker_gaps(words, turns)[0]['speaker'] == ''
