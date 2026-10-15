"""Validação dos exports com texto sem alinhamento e proveniência divergente."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from qualia.transcription.segments import assign_words, group_words, subtitle_rows, export_rows
from qualia.transcription.decoder import decoder_params

PATH = Path(__file__).resolve().parents[1]/'scripts/validate_transcript_benchmark.py'
spec = importlib.util.spec_from_file_location('transcription_validation',PATH)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ValidationTests(unittest.TestCase):
    def fixture(self, root):
        out = root/'run'
        out.mkdir()
        audio = root/'audio.wav'
        audio.write_bytes(b'synthetic-fixture')
        digest = validator.sha(audio)
        transcript = {'source_sha256':digest, 'audio_duration_seconds':2.,
                      'decoder_params':decoder_params(),
                      'segments':[{'start':0.,'end':1.,'text':'fala <tag> pendente'}]}
        def save(name,value):
            (out/name).write_text(json.dumps(value))
        save('s.transcription.json',transcript)
        words = [{'word':'fala','start':0.,'end':.3},
                 {'word':'<tag>','start':.3,'end':.6}, {'word':'pendente'}]
        turns = [{'start':0.,'end':2.,'speaker':'voice'}]
        assigned = assign_words(words,turns)
        save('s.alignment.json',{'native_transcript_sha256':validator.sha(out/'s.transcription.json'),
                                 'segments':[{'words':words}]})
        save('s.assigned-words.json',assigned)
        save('s.diarization.json',{'source_sha256':digest,'speaker_options':{},'detected_speakers':1})
        save('s.export.json',{'words':3,'native_repeat_runs':[]})
        save('s.review.json',[w for w in assigned if w['flags']])
        export_rows(group_words(assigned),out/'s.csv',out/'s.vtt',vtt_rows=subtitle_rows(assigned))
        return out, {'id':'s','audio':'audio.wav'}

    def test_unknown_word_survives_csv_and_html_text_survives_vtt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, case = self.fixture(root)
            report = validator.validate_case({'num_speakers':None},root,out,case)
            self.assertEqual(report['status'],'passed')
            self.assertEqual(report['words_without_time'],1)
            self.assertTrue(report['checks']['vtt_timed_text_preserved'])

    def test_changed_transcript_is_not_accepted_with_old_alignment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, case = self.fixture(root)
            path = out/'s.transcription.json'
            data = json.loads(path.read_text());data['extra']='changed'
            path.write_text(json.dumps(data))
            report = validator.validate_case({'num_speakers':None},root,out,case)
            self.assertEqual(report['status'],'failed')
            self.assertFalse(report['checks']['alignment_transcript_hash'])

    def test_changed_csv_text_and_fixed_speaker_count_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, case = self.fixture(root)
            path = out/'s.csv'
            path.write_text(path.read_text().replace('pendente','removed'))
            report = validator.validate_case({'num_speakers':2},root,out,case)
            self.assertFalse(report['checks']['csv_text_preserved'])
            self.assertFalse(report['checks']['automatic_speaker_count'])


if __name__=='__main__':
    unittest.main()
