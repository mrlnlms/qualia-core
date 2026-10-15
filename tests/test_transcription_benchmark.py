"""A comparação não pode ocultar vozes extras ou assumir identidade dos rótulos."""

import csv
import importlib.util
import json
from pathlib import Path


def test_reference_mapping_is_one_to_one_and_baseline_labels_are_independent(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/transcript_benchmark.py"
    spec = importlib.util.spec_from_file_location("transcript_benchmark", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    out = tmp_path / "run"
    out.mkdir()
    refs = tmp_path / "reference.csv"
    with refs.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["Speaker", "Start Time", "End Time", "Text"]
        )
        writer.writeheader()
        for i, voice in enumerate(["Reference A", "Reference B", "Reference C"]):
            writer.writerow(
                {
                    "Speaker": voice,
                    "Start Time": f"00:00:0{i}.000",
                    "End Time": f"00:00:0{i+1}.000",
                    "Text": "reference text unused",
                }
            )
    words = [
        {"word": "a", "start": 0.0, "end": 0.8, "speaker": "Generated X"},
        {"word": "b", "start": 0.8, "end": 1.0, "speaker": "Extra voice"},
        {"word": "c", "start": 1.0, "end": 2.0, "speaker": "Generated Y"},
        {"word": "d", "start": 2.0, "end": 3.0, "speaker": "Generated Z"},
    ]
    (out / "sample.assigned-words.json").write_text(json.dumps(words))
    (out / "sample.export.json").write_text(json.dumps({"detected_speakers": 4}))
    baseline = [
        {"start": float(i), "end": float(i + 1), "speaker": f"Old voice {i}"}
        for i in range(3)
    ]
    (tmp_path / "baseline.json").write_text(json.dumps(baseline))
    config = {
        "inputs": [
            {
                "id": "sample",
                "audio": "arbitrary.wav",
                "reference": "reference.csv",
                "baseline": "baseline.json",
            }
        ]
    }
    runner.compare(config, tmp_path, out)
    report = json.loads((out / "comparison.json").read_text())[0]
    assert report["unmatched_generated_speakers"] == ["Extra voice"]
    assert len(set(report["comparison_label_mapping_only"].values())) == 3
    assert report["per_reference_speaker"]["Reference A"]["agreement_v2"] == 0.8
    assert all(
        v["agreement_v1_on_same_word_intervals"] == 1.0
        for v in report["per_reference_speaker"].values()
    )
