"""Auditoria textual: sinais de revisão, nunca autorização para remover palavras."""
import re


def internal_repetitions(segments, min_repeats=5, max_phrase_words=8):
    """Encontra ciclos de palavras dentro de cada segmento, sem deduplicação.

    Retém a maior extensão em ciclos sobrepostos. Repetição real e intencional
    também pode ser sinalizada; correção exige evidência adicional do áudio.
    """
    if type(min_repeats) is not int or min_repeats < 2:
        raise ValueError("min_repeats deve ser inteiro >= 2")
    if type(max_phrase_words) is not int or max_phrase_words < 1:
        raise ValueError("max_phrase_words deve ser inteiro positivo")
    results = []
    for index, segment in enumerate(segments):
        words = segment["text"].split()
        normalized = [re.sub(r"^\W+|\W+$", "", w.casefold()) for w in words]
        candidates = []
        for start in range(len(words)):
            for width in range(1, min(max_phrase_words, (len(words)-start)//min_repeats)+1):
                phrase = normalized[start:start+width]
                if not all(phrase):
                    continue
                if start >= width and normalized[start-width:start] == phrase:
                    continue
                repeats = 1
                end = start+width
                while normalized[end:end+width] == phrase:
                    repeats += 1
                    end += width
                if repeats >= min_repeats:
                    candidates.append((start, end, width, repeats))
        selected = []
        for start, end, width, repeats in sorted(candidates, key=lambda r: (-(r[1]-r[0]), r[0], r[2])):
            if any(start < right and end > left for left, right, _, _ in selected):
                continue
            selected.append((start, end, width, repeats))
        for start, end, width, repeats in sorted(selected):
            results.append({"segment": index, "first_word": start, "last_word": end-1,
                            "phrase": " ".join(words[start:start+width]), "repeats": repeats,
                            "start": segment.get("start"), "end": segment.get("end"),
                            "review_required": True})
    return results
