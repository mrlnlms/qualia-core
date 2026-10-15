from copy import deepcopy

from qualia.transcription.completion import complete_speakers
from qualia.transcription.segments import subtitle_rows


def test_missing_times_use_segment_voice_without_changing_text_or_timing():
    words = [{'word': 'Uma', 'source_segment': 9, 'flags': ['unaligned_time']},
             {'word': 'resposta.', 'source_segment': 9, 'flags': ['unaligned_time']}]
    original = deepcopy(words)
    turns = [{'speaker': 'voice_C', 'start': 4., 'end': 7.}]
    result = complete_speakers(words, turns, [{'source_segment': 9, 'native_start': 5., 'native_end': 6.}])
    assert words == original
    assert [w['speaker'] for w in result] == ['voice_C', 'voice_C']
    assert all('start' not in w and w['speaker_review_required'] for w in result)


def test_completion_keeps_three_voices_and_does_not_propagate_new_guesses():
    words = [{'word': 'A', 'speaker': 'a', 'source_segment': 1},
             {'word': 'B', 'speaker': '', 'source_segment': 2},
             {'word': 'C', 'speaker': 'c', 'source_segment': 2},
             {'word': 'D', 'speaker': 'b', 'source_segment': 3}]
    result = complete_speakers(words, [])
    assert [w['speaker'] for w in result] == ['a', 'c', 'c', 'b']
    assert result[1]['speaker_before_completion'] == ''
    assert result[1]['speaker_completion_evidence']['acoustically_verified'] is False


def test_conflicting_neighbors_and_no_detected_voice_still_have_editable_labels():
    words = [{'word': 'A', 'speaker': 'a', 'start': 0., 'end': 1.},
             {'word': 'B', 'start': 2., 'end': 3.},
             {'word': 'C', 'speaker': 'c', 'start': 3.1, 'end': 4.}]
    assert complete_speakers(words, [])[1]['speaker'] == 'c'
    result = complete_speakers([{'word': 'Olá'}], [])
    assert result[0]['speaker']
    assert result[0]['speaker_completion_evidence']['basis'] == 'provisional_no_detected_voice'


def test_native_segment_cue_preserves_untimed_words_without_inventing_word_times():
    words = [{'word': 'Outra', 'speaker': 'Participant 3', 'source_segment': 8},
             {'word': 'voz.', 'speaker': 'Participant 3', 'source_segment': 8}]
    original = deepcopy(words)
    cues = subtitle_rows(words, native_segments=[{'source_segment': 8, 'native_start': 5., 'native_end': 5.2}])
    assert words == original
    assert len(cues) == 1
    assert cues[0]['text'] == 'Outra voz.' and cues[0]['speaker'] == 'Participant 3'
    assert (cues[0]['start'], cues[0]['end']) == (5., 5.2)
    assert cues[0]['flags'] == ['native_segment_timing']
