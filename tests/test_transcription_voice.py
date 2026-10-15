from qualia.transcription.voice import supported_change, candidates
from qualia.transcription.voice import verify_turns
from copy import deepcopy
import numpy as np


def scores(a,b):
    return [{'speaker':a,'cosine_similarity':.5},{'speaker':b,'cosine_similarity':.1}]


def test_acoustic_change_requires_agreement_of_turn_and_native_context():
    assert supported_change('A',scores('B','A'),scores('B','A'))=='B'
    assert supported_change('A',scores('B','A'),scores('A','B')) is None


def test_near_ties_and_unsupported_original_voice_do_not_change_labels():
    tied=[{'speaker':'B','cosine_similarity':.11},{'speaker':'A','cosine_similarity':.09}]
    assert supported_change('A',tied,tied) is None
    assert supported_change('C',scores('B','A'),scores('B','A')) is None


def test_only_isolated_brief_nonoverlapping_turns_are_candidates():
    turns=[dict(start=0.,end=1.,speaker='A'),dict(start=1.5,end=2.1,speaker='A'),dict(start=3.,end=8.,speaker='B')]
    assert 1 in candidates(turns,turns)
    assert 1 not in candidates(turns,turns+[dict(start=1.6,end=2.,speaker='B')])


def test_full_verification_revises_voice_before_word_assignment_without_moving_turns():
    turns=[dict(start=0.,end=10.,speaker='A'),dict(start=12.,end=13.,speaker='A'),dict(start=20.,end=30.,speaker='B')]
    native=[dict(start=0.,end=10.,text='arbitrary'),dict(start=11.5,end=13.5,text='independent of these words')]
    original=deepcopy(turns)
    def vector(region):
        return np.array([1.,0.]) if region['end']<=10 else np.array([0.,1.])
    exclusive,regular,report=verify_turns(turns,turns,native,vector)
    assert turns==original
    assert exclusive[1]['speaker']==regular[1]['speaker']=='B'
    assert [(t['start'],t['end']) for t in exclusive]==[(t['start'],t['end']) for t in original]
    assert len(report['changes'])==1 and report['reference_transcript_input'] is False


def test_insufficient_reference_voice_is_preserved():
    turns=[dict(start=0.,end=1.,speaker='A')]
    revised,_,report=verify_turns(turns,turns,[],lambda region:None)
    assert revised==turns
    assert report['status']=='insufficient_long_voice_references'
