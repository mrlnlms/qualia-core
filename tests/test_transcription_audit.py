"""Sinalização geral de repetição interna, sem apagar fala ou inferir verdade."""
from copy import deepcopy

import pytest

from qualia.transcription.audit import internal_repetitions


def test_finds_repeated_phrase_inside_one_segment_without_changing_text():
    source = [{"start": 12., "end": 34., "text": "Olá. " + "teste de som " * 7}]
    original = deepcopy(source)
    result = internal_repetitions(source)
    assert source == original
    assert len(result) == 1
    assert result[0]["segment"] == 0
    assert result[0]["phrase"] == "teste de som"
    assert result[0]["repeats"] == 7
    assert result[0]["first_word"] == 1
    assert result[0]["last_word"] == 21


def test_natural_short_repetitions_are_not_flagged():
    assert internal_repetitions([{"text": "Não, não, não. Tudo bem. Tchau, tchau."}]) == []


def test_long_intentional_repetition_is_only_a_review_signal():
    source = [{"text": "sim " * 8}]
    result = internal_repetitions(source)
    assert result[0]["repeats"] == 8
    assert result[0]["review_required"] is True
    assert source[0]["text"] == "sim " * 8


def test_ignores_case_and_edge_punctuation_but_preserves_original_phrase():
    source = [{"text": "Olá, mundo! olá mundo OLÁ MUNDO olá mundo olá mundo"}]
    result = internal_repetitions(source)
    assert len(result) == 1
    assert result[0]["repeats"] == 5
    assert result[0]["phrase"] == "Olá, mundo!"


def test_separated_runs_in_same_segment_are_both_retained():
    text = "um dois " * 5 + "pausa entre " + "três quatro " * 5
    result = internal_repetitions([{"text": text}])
    assert [r["repeats"] for r in result] == [5, 5]


@pytest.mark.parametrize("options", [{"min_repeats": 1}, {"max_phrase_words": 0}, {"min_repeats": True}])
def test_invalid_detection_limits_are_refused(options):
    with pytest.raises(ValueError):
        internal_repetitions([], **options)
