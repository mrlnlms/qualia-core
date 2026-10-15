"""Associação e exportação por regras gerais, sem acesso a referências."""

import csv
import html
import math
import io
from pathlib import Path


def valid_interval(item):
    start, end = item.get("start"), item.get("end")
    return (
        isinstance(start, (int, float))
        and isinstance(end, (int, float))
        and math.isfinite(start)
        and math.isfinite(end)
        and 0 <= start < end
    )


def overlap(a, b):
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def repeated_segment_runs(segments, min_run=5):
    """Sinaliza texto idêntico consecutivo para revisão; não remove segmentos."""
    if min_run < 2:
        raise ValueError("min_run deve ser pelo menos 2")
    runs = []
    start = 0
    for i in range(1, len(segments) + 1):
        same = (
            i < len(segments)
            and " ".join(segments[i]["text"].split()).casefold()
            == " ".join(segments[start]["text"].split()).casefold()
        )
        if same:
            continue
        if i - start >= min_run:
            runs.append(
                {
                    "first_segment": start,
                    "last_segment": i - 1,
                    "count": i - start,
                    "text": segments[start]["text"],
                    "start": segments[start].get("start"),
                    "end": segments[i - 1].get("end"),
                }
            )
        start = i
    return runs


def assign_words(words, turns, regular_turns=None):
    """Atribui maior sobreposição; empate/ausência mantém falante desconhecido.

    Mantém campos de origem, texto e tempos. Não estima tempos ausentes.
    """
    result = []
    turns = [t for t in turns if valid_interval(t)]
    for word in words:
        row = {**word, "speaker": "", "flags": list(word.get("flags", []))}
        if not valid_interval(word):
            row["flags"].append("unaligned_time")
            result.append(row)
            continue
        scores = {}
        for turn in turns:
            value = overlap(word, turn)
            if value > 0:
                scores[turn["speaker"]] = scores.get(turn["speaker"], 0.0) + value
        ranked = sorted(scores, key=scores.get, reverse=True)
        row["speaker_overlap_seconds"] = scores
        if not ranked:
            row["flags"].append("no_voice_overlap")
        elif len(ranked) > 1 and math.isclose(
            scores[ranked[0]], scores[ranked[1]], abs_tol=1e-8
        ):
            row["flags"].append("speaker_tie")
        else:
            row["speaker"] = ranked[0]
            if len(ranked) > 1:
                row["flags"].append("word_crosses_speakers")
        if regular_turns is not None:
            concurrent = {
                t["speaker"]
                for t in regular_turns
                if valid_interval(t) and overlap(word, t) > 0
            }
            if len(concurrent) > 1:
                row["flags"].append("overlapping_voice_regions")
        result.append(row)
    return result


def group_words(words, max_gap=1.5):
    """Agrupa em ordem textual, quebrando na voz, pausa ou tempo desconhecido."""
    if max_gap < 0:
        raise ValueError("max_gap deve ser não negativo")
    rows = []
    for i, word in enumerate(words):
        text = word.get("word", "").strip()
        if not text:
            continue
        timed = valid_interval(word)
        previous = rows[-1] if rows else None
        join = (
            previous
            and timed
            and valid_interval(previous)
            and previous["speaker"] == word.get("speaker", "")
            and previous["start"] <= word["start"]
            and word["start"] - previous["end"] <= max_gap
        )
        # Consecutive unknown-time words can remain one textual pending block.
        join_pending = (
            previous
            and not timed
            and not valid_interval(previous)
            and previous.get("source_segment") == word.get("source_segment")
        )
        if join or join_pending:
            previous["text"] += " " + text
            if timed:
                if word["start"] < previous["end"]:
                    previous["flags"].append("overlapping_word_times")
                previous["end"] = max(previous["end"], word["end"])
            previous["word_indices"].append(i)
            previous["flags"] = sorted(set(previous["flags"] + word.get("flags", [])))
        else:
            rows.append(
                {
                    "start": word["start"] if timed else None,
                    "end": word["end"] if timed else None,
                    "speaker": word.get("speaker", ""),
                    "text": text,
                    "source_segment": word.get("source_segment"),
                    "word_indices": [i],
                    "flags": list(word.get("flags", [])),
                }
            )
    return rows


def timestamp(value):
    ms = round(value * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def plain_text(rows):
    """Une falas consecutivas da mesma voz, mantendo ordem e texto integral.

    Pausas e tempos desconhecidos não limitam parágrafos no TXT. Blocos sem voz
    conhecida permanecem separados: ausência de rótulo não identifica a pessoa.
    """
    groups = []
    for row in rows:
        if not row['text']:
            continue
        speaker = row.get('speaker') or ''
        if speaker and groups and groups[-1]['speaker'] == speaker:
            groups[-1]['text'] += ' ' + row['text']
        else:
            groups.append({'speaker': speaker, 'text': row['text']})
    blocks = [f"{g['speaker'] or 'Sem falante'}\n{g['text']}" for g in groups]
    return '\n\n'.join(blocks) + ('\n' if blocks else '')


def export_text(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plain_text(rows), encoding='utf-8')


def subtitle_rows(words, max_chars=84, max_duration=6.0, max_gap=1.5, native_segments=None):
    """Legendas curtas derivadas de palavras; mantém as mesmas vozes/texto."""
    if max_chars < 1 or max_duration <= 0 or max_gap < 0:
        raise ValueError("Limites de legenda inválidos")
    if native_segments is not None:
        sources = {s.get('source_segment', i): s for i, s in enumerate(native_segments)}
        output, pending = [], []
        for i, word in enumerate(words):
            if valid_interval(word):
                pending.append(word)
                continue
            if pending:
                output.extend(subtitle_rows(pending, max_chars, max_duration, max_gap))
                pending = []
            source = sources.get(word.get('source_segment'), {})
            region = {'start': source.get('native_start', source.get('start')),
                      'end': source.get('native_end', source.get('end'))}
            if not valid_interval(region):
                continue
            if (output and 'native_segment_timing' in output[-1].get('flags', [])
                    and output[-1]['source_segment'] == word.get('source_segment')
                    and output[-1]['speaker'] == word.get('speaker', '')):
                output[-1]['text'] += ' '+word['word']
                output[-1]['word_indices'].append(i)
            else:
                output.append(dict(region, speaker=word.get('speaker', ''), text=word['word'],
                                   source_segment=word.get('source_segment'), word_indices=[i],
                                   flags=['native_segment_timing']))
        if pending:
            output.extend(subtitle_rows(pending, max_chars, max_duration, max_gap))
        return output
    chunks = []
    current = []
    for word in words:
        if not valid_interval(word):
            if current:
                chunks.extend(group_words(current, max_gap))
                current = []
            continue
        if current:
            text = " ".join(w["word"] for w in current + [word])
            if (
                word.get("speaker") != current[-1].get("speaker")
                or word["start"] - current[-1]["end"] > max_gap
                or word["start"] < current[-1]["end"]
                or word["end"] - current[0]["start"] > max_duration
                or len(text) > max_chars
            ):
                chunks.extend(group_words(current, max_gap))
                current = []
        current.append(word)
    if current:
        chunks.extend(group_words(current, max_gap))
    return chunks


def export_rows(rows, csv_path, vtt_path, vtt_rows=None):
    """CSV preserva texto sem tempo com células vazias; VTT requer intervalo."""
    csv_path, vtt_path = Path(csv_path), Path(vtt_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    contents, stats = render_rows(rows, vtt_rows)
    csv_path.write_bytes(contents['csv'].encode('utf-8'))
    vtt_path.write_text(contents['vtt'], encoding='utf-8')
    return stats


def render_rows(rows, vtt_rows=None):
    """Same export contract in memory, also used for human speaker corrections."""
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['Speaker', 'Start Time', 'End Time', 'Text'])
    writer.writeheader()
    for row in rows:
        timed = valid_interval(row)
        writer.writerow({'Speaker': row['speaker'], 'Text': row['text'],
                         'Start Time': timestamp(row['start']) if timed else '',
                         'End Time': timestamp(row['end']) if timed else ''})
    cues = ["WEBVTT", ""]
    count = 0
    for row in rows if vtt_rows is None else vtt_rows:
        if not valid_interval(row):
            continue
        text = html.escape(row["text"])
        if row["speaker"]:
            text = f'<v {html.escape(row["speaker"])}>{text}</v>'
        cues += [f'{timestamp(row["start"])} --> {timestamp(row["end"])}', text, ""]
        count += 1
    return {'csv': stream.getvalue(), 'vtt': '\n'.join(cues)+'\n'}, {
        "csv_rows": len(rows),
        "vtt_cues": count,
        "csv_rows_without_time": sum(not valid_interval(r) for r in rows),
    }
