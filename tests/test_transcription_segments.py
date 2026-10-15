import csv

from qualia.transcription.segments import (
    assign_words,
    group_words,
    subtitle_rows,
    export_rows,
    repeated_segment_runs,
    plain_text,
)


def test_change_of_speaker_splits_words_within_same_source_segment():
    words = [
        {"word": "Pergunta?", "start": 0.0, "end": 1.0, "source_segment": 0},
        {"word": "Resposta.", "start": 1.0, "end": 2.0, "source_segment": 0},
    ]
    turns = [
        {"speaker": "A", "start": 0.0, "end": 1.0},
        {"speaker": "B", "start": 1.0, "end": 2.0},
    ]
    assigned = assign_words(words, turns)
    assert [w["speaker"] for w in assigned] == ["A", "B"]
    assert [r["text"] for r in group_words(assigned)] == ["Pergunta?", "Resposta."]


def test_unknown_times_and_equal_voice_overlap_are_not_guessed():
    words = [
        {"word": "Sem tempo"},
        {"word": "Empate", "start": 0.0, "end": 1.0},
        {"word": "Sem voz", "start": 2.0, "end": 3.0},
    ]
    turns = [{"speaker": v, "start": 0.0, "end": 1.0} for v in ["A", "B", "C"]]
    assigned = assign_words(words, turns)
    assert [w["speaker"] for w in assigned] == ["", "", ""]
    assert "unaligned_time" in assigned[0]["flags"]
    assert "speaker_tie" in assigned[1]["flags"]
    assert "no_voice_overlap" in assigned[2]["flags"]


def test_three_speakers_are_preserved_without_reference_labels():
    words = [{"word": str(i), "start": float(i), "end": float(i + 1)} for i in range(3)]
    turns = [{**w, "speaker": f"voice-{i}"} for i, w in enumerate(words)]
    assert len(set(w["speaker"] for w in assign_words(words, turns))) == 3


def test_unknown_time_text_survives_csv_and_is_excluded_from_vtt(tmp_path):
    words = [
        {"word": 'Olá, "pesquisa"!', "start": 0.0, "end": 1.0, "speaker": "A"},
        {"word": "Não alinhada", "speaker": "", "source_segment": 1},
        {"word": "também.", "speaker": "", "source_segment": 1},
    ]
    rows = group_words(words)
    stats = export_rows(rows, tmp_path / "out.csv", tmp_path / "out.vtt")
    with (tmp_path / "out.csv").open(newline="", encoding="utf-8") as f:
        result = list(csv.DictReader(f))
    assert result[0]["Text"] == 'Olá, "pesquisa"!'
    assert result[1]["Text"] == "Não alinhada também."
    assert result[1]["Start Time"] == result[1]["End Time"] == ""
    assert stats == {"csv_rows": 2, "vtt_cues": 1, "csv_rows_without_time": 1}
    assert "Não alinhada" not in (tmp_path / "out.vtt").read_text()


def test_pause_and_unknown_voice_break_known_voice_group():
    words = [
        {"word": "A", "start": 0.0, "end": 1.0, "speaker": "x"},
        {"word": "B", "start": 3.0, "end": 4.0, "speaker": "x"},
        {"word": "C", "start": 4.0, "end": 5.0, "speaker": ""},
        {"word": "D", "start": 5.0, "end": 6.0, "speaker": "x"},
    ]
    assert len(group_words(words)) == 4


def test_concurrent_voices_are_flagged_even_with_exclusive_assignment():
    words = [{"word": "Sim", "start": 0.0, "end": 1.0}]
    exclusive = [{"speaker": "A", "start": 0.0, "end": 1.0}]
    regular = exclusive + [{"speaker": "B", "start": 0.2, "end": 0.8}]
    assigned = assign_words(words, exclusive, regular)
    assert assigned[0]["speaker"] == "A"
    assert "overlapping_voice_regions" in assigned[0]["flags"]


def test_subtitle_limits_do_not_change_csv_grouping_or_drop_words():
    words = [
        {"word": "palavra", "start": float(i), "end": float(i + 1), "speaker": "A"}
        for i in range(10)
    ]
    rows = group_words(words)
    cues = subtitle_rows(words, max_chars=25, max_duration=3.0)
    assert len(rows) == 1
    assert len(cues) > 1
    assert all(len(r["text"]) <= 25 and r["end"] - r["start"] <= 3.0 for r in cues)
    assert " ".join(r["text"] for r in rows) == " ".join(r["text"] for r in cues)


def test_unknown_voice_words_form_pending_block_and_overlapping_times_are_flagged():
    words = [
        {"word": "sem", "start": 0.0, "end": 1.0, "speaker": ""},
        {"word": "falante", "start": 0.9, "end": 2.0, "speaker": ""},
        {"word": "resposta", "start": 2.0, "end": 3.0, "speaker": "A"},
    ]
    rows = group_words(words)
    assert len(rows) == 2
    assert rows[0]["text"] == "sem falante"
    assert rows[0]["speaker"] == ""
    assert rows[0]["start"] == 0.0 and rows[0]["end"] == 2.0
    assert "overlapping_word_times" in rows[0]["flags"]


def test_repeat_audit_flags_run_without_modifying_source():
    import copy

    segments = [
        {"text": "Frase repetida.", "start": float(i), "end": float(i + 1)}
        for i in range(7)
    ]
    segments.append({"text": "Outra fala.", "start": 7.0, "end": 8.0})
    before = copy.deepcopy(segments)
    runs = repeated_segment_runs(segments)
    assert (
        runs[0]["count"] == 7
        and runs[0]["first_segment"] == 0
        and runs[0]["last_segment"] == 6
    )
    assert segments == before


def test_txt_joins_same_voice_across_pauses_but_preserves_dialogue_and_unknown_blocks():
    import copy

    rows = [
        {'speaker': 'A', 'text': 'Primeira frase.', 'start': 0., 'end': 1.},
        {'speaker': 'A', 'text': 'Depois da pausa.', 'start': 20., 'end': 21.},
        {'speaker': 'B', 'text': 'Resposta.'},
        {'speaker': 'A', 'text': 'Outra pergunta.'},
        {'speaker': '', 'text': 'Palavra sem voz.'},
        {'speaker': '', 'text': 'Outra sem voz.'},
        {'speaker': 'A', 'text': 'Continuação.'},
    ]
    original = copy.deepcopy(rows)
    assert plain_text(rows) == (
        'A\nPrimeira frase. Depois da pausa.\n\n'
        'B\nResposta.\n\nA\nOutra pergunta.\n\n'
        'Sem falante\nPalavra sem voz.\n\nSem falante\nOutra sem voz.\n\n'
        'A\nContinuação.\n')
    assert rows == original
