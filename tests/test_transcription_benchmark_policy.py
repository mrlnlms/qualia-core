"""O runner não pode aceitar ASR legado como resultado da política corrigida."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import unittest

PATH = Path(__file__).resolve().parents[1]/'scripts/transcript_benchmark.py'
spec = importlib.util.spec_from_file_location('benchmark_policy',PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class BenchmarkPolicyTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)
        (root/'recording.wav').write_bytes(b'fixture')
        out = root/'run';out.mkdir()
        case = {'id':'sample','audio':'recording.wav'}
        config = {'model':'large-v3','language':'pt','inputs':[case]}
        data = {'source':'recording.wav','source_sha256':runner.sha(root/'recording.wav'),
                'model':'large-v3','language':'pt','segments':[],
                'effective_decoder_params':{'no_context':True,'n_max_text_ctx':0}}
        return root,out,config,data

    def guard(self):
        return patch.dict('sys.modules', {'pywhispercpp.model': SimpleNamespace(
            Model=MagicMock(side_effect=AssertionError('Nenhum modelo pode ser carregado neste teste')))} )

    def test_old_cache_without_policy_is_refused_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder, self.guard():
            root,out,config,data = self.fixture(folder)
            data.pop('effective_decoder_params')
            target=out/'sample.transcription.json'
            original=json.dumps(data);target.write_text(original)
            with self.assertRaises(ValueError):
                runner.transcribe(config,root,out)
            self.assertEqual(target.read_text(),original)

    def test_candidate_with_verified_policy_is_copied_without_inference(self):
        with tempfile.TemporaryDirectory() as folder, self.guard():
            root,out,config,data = self.fixture(folder)
            candidate=root/'candidate.json';candidate.write_text(json.dumps(data))
            config['inputs'][0]['reuse_transcription']='candidate.json'
            config['inputs'][0]['reuse_transcription_sha256']=runner.sha(candidate)
            runner.transcribe(config,root,out)
            copied=runner.native(out/'sample.transcription.json')
            self.assertEqual(copied['segments'],data['segments'])
            self.assertEqual(copied['reused_sha256'],runner.sha(candidate))

    def test_incompatible_policy_and_changed_candidate_hash_are_refused(self):
        with tempfile.TemporaryDirectory() as folder, self.guard():
            root,out,config,data = self.fixture(folder)
            candidate=root/'candidate.json'
            data['effective_decoder_params']['n_max_text_ctx']=16384
            candidate.write_text(json.dumps(data))
            config['inputs'][0]['reuse_transcription']='candidate.json'
            with self.assertRaises(ValueError):
                runner.transcribe(config,root,out)
            data['effective_decoder_params']['n_max_text_ctx']=0
            candidate.write_text(json.dumps(data))
            config['inputs'][0]['reuse_transcription_sha256']='wrong-hash'
            with self.assertRaises(ValueError):
                runner.transcribe(config,root,out)
            self.assertFalse((out/'sample.transcription.json').exists())

    def test_missing_declared_candidate_never_falls_back_to_default_inference(self):
        with tempfile.TemporaryDirectory() as folder, self.guard():
            root,out,config,data = self.fixture(folder)
            config['inputs'][0]['reuse_transcription']='missing.json'
            with self.assertRaises(ValueError):
                runner.transcribe(config,root,out)

    def test_new_recording_uses_explicit_policy_and_preserves_duplicate_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root,out,config,data = self.fixture(folder)
            segments=[{'start':0.,'end':1.,'text':'igual'}, {'start':1.,'end':2.,'text':'igual'}]
            with patch.object(runner,'decode_segments',return_value=segments,create=True) as decode:
                with patch.object(runner,'audio_array',return_value=[0.]*32000):
                    with self.guard():
                        runner.transcribe(config,root,out)
            result=runner.native(out/'sample.transcription.json')
            self.assertEqual(result['segments'],segments)
            self.assertEqual(result['decoder_params'],{'no_context':True,'n_max_text_ctx':0})
            self.assertEqual(decode.call_args.kwargs['params'],result['decoder_params'])

    def test_speech_boundaries_select_audio_before_decoding_and_restore_global_times(self):
        with tempfile.TemporaryDirectory() as folder:
            root,out,config,data = self.fixture(folder)
            config['speech_boundary_policy']={'padding_seconds':5.,'min_trim_seconds':10.}
            diar={'source_sha256':runner.sha(root/'recording.wav'),'speaker_options':{},
                  'regular':[{'start':20.,'end':21.,'speaker':'voice'}]}
            (out/'sample.diarization.json').write_text(json.dumps(diar))
            raw=[{'start':.2,'end':.8,'text':'fala preservada'}]
            with patch.object(runner,'audio_array',return_value=[0.]*(40*16000)):
                with patch.object(runner,'decode_segments',return_value=raw) as decode:
                    runner.transcribe(config,root,out)
            result=runner.native(out/'sample.transcription.json')
            self.assertEqual(len(decode.call_args.args[0]),11*16000)
            self.assertEqual(result['audio_duration_seconds'],40.)
            self.assertEqual(result['segments'],[{'start':15.2,'end':15.8,'text':'fala preservada'}])
            self.assertEqual(result['recognition_window']['start_sample'],15*16000)

    def test_cropped_cache_cannot_be_reused_without_its_input_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root,out,config,data=self.fixture(folder)
            data['audio_duration_seconds']=40.
            data['recognition_window']={'start_sample':0,'end_sample':26*16000}
            target=out/'sample.transcription.json';target.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                runner.transcribe(config,root,out)


if __name__=='__main__':
    unittest.main()
