import math

import pytest

from qualia.transcription.speech import speech_boundaries, recognition_window, window_matches


def test_long_outer_noise_is_not_sent_but_padding_and_internal_gaps_are_preserved():
    result = speech_boundaries(100., [{"start": 20., "end": 25.}, {"start": 60., "end": 70.}])
    assert result == {"start": 15., "end": 75., "activity_found": True}


def test_short_outer_silence_does_not_change_input():
    assert speech_boundaries(100., [{"start": 8., "end": 94.}]) == {
        "start": 0., "end": 100., "activity_found": True}


def test_no_detected_speech_keeps_all_audio_instead_of_discarding_it():
    assert speech_boundaries(100., []) == {"start": 0., "end": 100., "activity_found": False}


def test_brief_late_voice_is_preserved_even_after_long_silence():
    result = speech_boundaries(100., [{"start": 2., "end": 10.}, {"start": 95., "end": 95.2}])
    assert result["end"] == 100.


@pytest.mark.parametrize("duration,policy", [(math.nan, None), (10., {"padding_seconds": -1, "min_trim_seconds": 10}),
                                            (10., {"padding_seconds": 5}), (10., {"padding_seconds": True, "min_trim_seconds": 10})])
def test_invalid_policies_are_refused(duration, policy):
    with pytest.raises(ValueError):
        speech_boundaries(duration, [], policy)


def test_legacy_full_audio_cache_does_not_match_shorter_window():
    data = {'audio_duration_seconds': 100.}
    policy = {'padding_seconds': 5., 'min_trim_seconds': 10.}
    window = recognition_window(1600000, [{'start': 2., 'end': 60.}], policy, 'diar-hash')
    assert not window_matches(data, window)
    data['recognition_window'] = window
    assert window_matches(data, window)
    assert not window_matches(data)  # Não apresentar áudio recortado como inteiro.


def test_full_input_is_reusable_when_activity_policy_does_not_change_samples():
    data = {'audio_duration_seconds': 100.}
    window = recognition_window(1600000, [{'start': 0., 'end': 99.}],
                                {'padding_seconds': 5., 'min_trim_seconds': 10.}, 'diar-hash')
    assert window_matches(data, window)
