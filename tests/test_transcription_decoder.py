"""Contrato do decoder: política, isolamento por áudio e preservação da saída."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import unittest

from qualia.transcription.decoder import decoder_params, decode_segments, transcription_policy


class DecoderTests(unittest.TestCase):
    def test_policy_does_not_carry_text_history_and_rejects_invalid_options(self):
        a = decoder_params()
        a['n_max_text_ctx'] = 12
        self.assertEqual(decoder_params(), {'no_context': True, 'n_max_text_ctx': 0})
        for value in [{'n_max_text_ctx': -1}, {'n_max_text_ctx': True}, {'no_context': 1},
                      {'initial_prompt': 'reference'}, 'invalid']:
            with self.assertRaises(ValueError):
                decoder_params(value)

    def test_each_audio_has_a_fresh_model_with_the_same_policy(self):
        instances = [MagicMock(), MagicMock()]
        for instance in instances:
            instance.transcribe.return_value = [SimpleNamespace(t0=0, t1=100, text='fala')]
        factory = MagicMock(side_effect=instances)
        for audio in ['waveform-a', 'waveform-b']:
            decode_segments(audio, 'large-v3', 'pt', model_factory=factory)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(instances[0].transcribe.call_args.args, ('waveform-a',))
        self.assertEqual(instances[1].transcribe.call_args.args, ('waveform-b',))
        for call in factory.call_args_list:
            self.assertEqual(call.kwargs['n_max_text_ctx'], 0)
            self.assertIs(call.kwargs['no_context'], True)
            self.assertEqual(call.kwargs['params_sampling_strategy'], 0)
            self.assertEqual(call.kwargs['n_threads'], 4)
        self.assertEqual(instances[0].transcribe.call_args.kwargs, {'language': 'pt'})

    def test_duplicate_text_and_invalid_native_times_survive_unchanged(self):
        model = MagicMock()
        model.transcribe.return_value = [SimpleNamespace(t0=20, t1=20, text=' fala '),
                                        SimpleNamespace(t0=20, t1=100, text=' fala ')]
        result = decode_segments('array', 'large-v3', 'pt', model_factory=MagicMock(return_value=model))
        self.assertEqual(result, [{'start': .2, 'end': .2, 'text': ' fala '},
                                  {'start': .2, 'end': 1., 'text': ' fala '}])

    def test_legacy_cache_is_not_mistaken_for_the_new_policy(self):
        self.assertIsNone(transcription_policy({'segments': []}))
        self.assertIsNone(transcription_policy({'decoder_params': {'no_context': 1, 'n_max_text_ctx': 0}}))
        self.assertIsNone(transcription_policy({'effective_decoder_params': {'no_context': True}}))
        self.assertEqual(transcription_policy({'effective_decoder_params': {
            'no_context': True, 'n_max_text_ctx': 0, 'language': 'pt'}}), decoder_params())
        self.assertNotEqual(transcription_policy({'effective_decoder_params': {
            'no_context': True, 'n_max_text_ctx': 16384}}), decoder_params())


if __name__ == '__main__':
    unittest.main()
