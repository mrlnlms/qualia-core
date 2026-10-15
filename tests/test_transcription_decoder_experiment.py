"""Testes stdlib: nenhum modelo, áudio, NumPy ou torch é importado."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts/transcript_decoder_experiment.py'
spec = importlib.util.spec_from_file_location('decoder_experiment', PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class DecoderPreparationTests(unittest.TestCase):
    def test_windows_cover_each_sample_exactly_once_including_tail(self):
        self.assertEqual(runner.windows(25, 1, rate=10), [(0, 10), (10, 20), (20, 25)])
        self.assertEqual(runner.windows(25, 0), [(0, 25)])
        for args in [(0, 1), (10, -1), (10, .000001)]:
            with self.assertRaises(ValueError):
                runner.windows(*args)

    def test_global_times_preserve_text_and_do_not_deduplicate(self):
        local = [SimpleNamespace(t0=0, t1=100, text=' mesmo texto')] * 2
        self.assertEqual(runner.global_segments(local, 60),
                         [{'start': 60, 'end': 61, 'text': ' mesmo texto'}] * 2)

    def test_dry_run_never_opens_audio_or_creates_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {'model': 'large-v3', 'language': 'pt', 'output': 'absent',
                      'inputs': [{'id': 'sample', 'audio': 'does-not-exist.m4a'}],
                      'variants': [{'id': 'control', 'callback': False, 'chunk_seconds': 0, 'decoder': {}}]}
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(config))
            result = subprocess.run([sys.executable, str(PATH), '--manifest', str(manifest)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['status'], 'prepared_not_executed')
            self.assertFalse((root / 'absent').exists())

    def test_changed_sources_or_code_refuse_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'audio').write_bytes(b'fake fixture, not audio')
            config = {'inputs': [{'id': 'sample', 'audio': 'audio'}]}
            out = root / 'run'
            runner.prepare(config, root, out)
            runner.prepare(config, root, out)
            (root / 'audio').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                runner.prepare(config, root, out)

    def test_real_matrix_has_paired_controls_and_no_asr_reuse(self):
        config = {'model': 'large-v3', 'language': 'pt',
                  'inputs': [{'id': f'sample-{i}', 'audio': f'{i}.m4a'} for i in range(3)],
                  'variants': runner.default_variants()}
        runner.validate(config)
        self.assertEqual(len(config['inputs']), 3)
        self.assertEqual(len(config['variants']), 8)
        self.assertTrue(all('reuse_transcription' not in c for c in config['inputs']))
        for name in ['default', 'no-context', 'zero-text-context']:
            a, b = [v for v in config['variants'] if v['id'].startswith(name + '-')]
            self.assertEqual(a['decoder'], b['decoder'])
            self.assertNotEqual(a['callback'], b['callback'])
        bad = copy.deepcopy(config)
        bad['variants'][0]['decoder']['initial_prompt'] = 'not allowed'
        with self.assertRaises(ValueError):
            runner.validate(bad)

    def test_summary_leaves_missing_results_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            reports = runner.summarize({'variants': [{'id': 'v'}], 'inputs': [{'id': 'a'}]}, Path(folder))
            self.assertEqual(reports, [{'variant': 'v', 'input': 'a', 'status': 'pending'}])

    def test_selection_reuses_only_verified_automatic_diarization(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'audio').write_bytes(b'fixture')
            variant = runner.default_variants()[0]
            config = {'model': 'large-v3', 'language': 'pt', 'variants': [variant],
                      'inputs': [{'id': 'sample', 'audio': 'audio', 'reuse_diarization': 'diar.json'}]}
            out = root / 'experiment'
            runner.prepare(config, root, out)
            runner.save(out / variant['id'] / 'sample.transcription.json',
                        {'source_sha256': runner.sha(root / 'audio'), 'variant': variant})
            runner.save(root / 'diar.json', {'source_sha256': runner.sha(root / 'audio'),
                                           'speaker_options': {'num_speakers': 2}})
            with self.assertRaises(ValueError):
                runner.select(config, root, out, variant['id'], root / 'candidate.json')
            self.assertFalse((root / 'runs').exists())
            runner.save(root / 'diar.json', {'source_sha256': runner.sha(root / 'audio'),
                                           'speaker_options': {}})
            runner.select(config, root, out, variant['id'], root / 'candidate.json')
            candidate = runner.read(root / 'candidate.json')
            self.assertIsNone(candidate['num_speakers'])
            self.assertTrue(Path(candidate['inputs'][0]['audio']).is_absolute())
            self.assertEqual(runner.read(root / 'runs/2026-10-14-v3/sample.diarization.json')['speaker_options'], {})

    def test_selection_does_not_overwrite_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {'variants': [{'id': 'v'}], 'inputs': []}
            runner.prepare(config, root, root / 'run')
            target = root / 'existing.json'
            target.write_text('original')
            with self.assertRaises(ValueError):
                runner.select(config, root, root / 'run', 'v', target)
            self.assertEqual(target.read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
