import copy
from collections import Counter
from types import SimpleNamespace
import pytest
from forgerl.bench import pilot,replication
from forgerl.bench.engine import run_episode


def test_balanced_exposed_matrix_and_no_old_seed_replacement():
    plan=replication.plan();rows=plan['study_order']
    assert len(rows)==1296 and len({r['design_id'] for r in rows})==1296
    assert set(plan['seeds'])=={31,47,73,101}
    assert 'previously inspected' in plan['catalog_scope']
    counts=Counter((r['seed'],r['policy'],r['verify_enabled']) for r in rows)
    assert set(counts.values())=={27} and len(counts)==48
    assert plan==replication.plan() and plan['study_cap_usd']==3


class Provider:
    def __init__(self,candidates):self.candidates=iter(candidates);self.feedback=[]
    async def generate(self,task,files,feedback,action,**kwargs):
        self.feedback.append(copy.deepcopy(feedback))
        return SimpleNamespace(files=next(self.candidates),model='mock',prompt_tokens=10,completion_tokens=10,
             total_tokens=20,cost_usd=.001,elapsed_s=.001,request_id='mock',finish_reason='stop',prompt_messages=[],response_text='mock')


@pytest.mark.asyncio
@pytest.mark.parametrize('policy',pilot.POLICIES)
async def test_verify_intervention_catches_visible_green_while_control_stops(policy):
    spec=pilot.all_specs()[0]
    partial=dict(spec.task.reference_files)
    name=next(iter(partial));partial[name]+='\n# deliberately wrong fixture candidate\n'
    for enabled in (False,True):
        seen=[]
        def evaluator(task,files,hidden=False):
            supplemental=task.public_cases==spec.verification_cases
            good=files==task.reference_files or (files==partial and not supplemental and not hidden)
            cases=task.hidden_cases if hidden else task.public_cases
            seen.append((hidden,supplemental))
            return {'passed':len(cases) if good else 0,'total':len(cases),'cases':[], 'elapsed_s':.001,'execution_error':None}
        provider=Provider([partial,spec.task.reference_files])
        episode=replication.AblationEpisode(spec,provider,policy,verify_enabled=enabled,evaluator=evaluator)
        result=await run_episode(episode,selector=episode.select)
        assert result['solved']==enabled
        assert result['attempts']==(2 if enabled else 1)
        assert result['verification_calls']==(2 if enabled else 0)
        assert sum(hidden for hidden,_ in seen)==1 and seen[-1][0]
        assert all(c['name'] not in str(provider.feedback) for c in spec.task.hidden_cases)
        assert result['evidence_scope']=='replication_on_previously_exposed_catalog'
        if not enabled:assert all(not supplementary for _,supplementary in seen)


@pytest.mark.asyncio
async def test_disabled_condition_cannot_call_verify_directly():
    episode=replication.AblationEpisode(pilot.all_specs()[0],Provider([]),'cheap_only',verify_enabled=False)
    with pytest.raises(ValueError,match='disabled'):await episode.step('verify')


def test_invalid_condition_rejected():
    with pytest.raises(ValueError,match='boolean'):
        replication.AblationEpisode(pilot.all_specs()[0],Provider([]),'cheap_only',verify_enabled='false')
