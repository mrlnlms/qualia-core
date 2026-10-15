from qualia.transcription.comparison import align_words, tokens


def test_exact_word_distance_reports_substitution_insertion_and_deletion():
    result = align_words(['a','b','c','d'], ['a','x','c','y','d'])
    assert result['distance'] == 2
    assert result['substitute'] == 1 and result['insert'] == 1
    assert result['wer'] == .5
    assert align_words(['a','b'], ['a'])['delete'] == 1


def test_normalization_ignores_punctuation_and_case_but_preserves_accents_numbers_and_fillers():
    assert tokens('Olá, SIM! 12 aí...') == ['olá','sim','12','aí']
    assert align_words(tokens('Olá, SIM!'), tokens('olá sim'))['distance'] == 0
    assert align_words(tokens('é'), tokens('e'))['distance'] == 1


def test_empty_reference_has_no_rate_and_full_insertions_are_counted():
    result = align_words([], ['fala'])
    assert result['wer'] is None and result['insert'] == 1
    assert align_words(['fala'], [])['delete'] == 1
