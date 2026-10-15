"""Limites externos por atividade de voz; sem tocar no texto reconhecido."""
import math

from .segments import valid_interval


DEFAULT_SPEECH_BOUNDARIES = {"padding_seconds": 5., "min_trim_seconds": 10.}


def speech_boundaries(duration, turns, policy=None):
    """Preserva margens e pausas internas; só evita sobras externas longas.

    Sem evidência de voz, mantém o áudio inteiro. A diarização pode deixar de
    detectar fala baixa; estes limites não comprovam ausência de fala humana.
    """
    policy = DEFAULT_SPEECH_BOUNDARIES if policy is None else policy
    if set(policy) != set(DEFAULT_SPEECH_BOUNDARIES):
        raise ValueError("Política de limites de voz desconhecida.")
    for value in [duration, *policy.values()]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Duração e margens devem ser finitas e não negativas.")
    activity = [t for t in turns if valid_interval(t) and t["start"] < duration]
    if not activity:
        return {"start": 0., "end": duration, "activity_found": False}
    start = max(0., min(t["start"] for t in activity)-policy["padding_seconds"])
    end = min(duration, max(t["end"] for t in activity)+policy["padding_seconds"])
    if start < policy["min_trim_seconds"]:
        start = 0.
    if duration-end < policy["min_trim_seconds"]:
        end = duration
    return {"start": start, "end": end, "activity_found": True}


def recognition_window(samples, turns, policy, diarization_sha256, rate=16000):
    bounds = speech_boundaries(samples/rate, turns, policy)
    return {"start_sample": max(0, math.floor(bounds["start"]*rate)),
            "end_sample": min(samples, math.ceil(bounds["end"]*rate)),
            "source_samples": samples, "sample_rate": rate,
            "activity_found": bounds["activity_found"], "policy": dict(policy),
            "diarization_sha256": diarization_sha256}


def window_matches(data, expected=None):
    """Cache sem janela explícita só equivale ao áudio inteiro."""
    actual = data.get("recognition_window")
    if actual is None and expected is None:
        return True
    samples = round(data["audio_duration_seconds"]*16000)
    if expected is None:
        return actual is None or (actual["start_sample"] == 0 and actual["end_sample"] == samples)
    if actual is None:
        return expected["start_sample"] == 0 and expected["end_sample"] == samples
    return actual == expected
