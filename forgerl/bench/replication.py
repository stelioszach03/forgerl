"""Prospectively frozen replication/VERIFY ablation on the exposed v0.3 catalog."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
from . import pilot
from .engine import run_episode, utc_now
from .study import CappedProvider, Writer, digest
from ..store import BudgetExceeded

PROTOCOL = 'forgebench-exposed-replication-verify-ablation-v1'
SEEDS = (31, 47, 73, 101)
STUDY_CAP = 3.0
MAX_SECONDS = 8 * 3600
ROOT = Path(__file__).resolve().parents[2]


class AblationEpisode(pilot.PilotEpisode):
    def __init__(self, *args, verify_enabled=True, **kwargs):
        if type(verify_enabled) is not bool:
            raise ValueError('Verification condition must be boolean')
        self.verify_enabled = verify_enabled
        super().__init__(*args, **kwargs)
        if not verify_enabled:
            self.max_verifications = 0

    def stop_after_visible_success(self):
        return not self.verify_enabled

    def legal_actions(self, state):
        actions = super().legal_actions(state)
        return actions if self.verify_enabled else tuple(a for a in actions if a != 'verify')

    async def step(self, action, selection_source='replication'):
        if not self.verify_enabled and action == 'verify':
            raise ValueError('VERIFY is disabled in this condition')
        return await super().step(action, selection_source)

    def result(self):
        out = super().result()
        out.update(version='v0.3-exposed-replication1',protocol=PROTOCOL,
                   evidence_scope='replication_on_previously_exposed_catalog',
                   verification_enabled=self.verify_enabled,
                   verification_policy='shared verify-on-green' if self.verify_enabled else 'no supplemental verification')
        return out


def plan():
    rows=[]
    for seed in SEEDS:
        for spec in sorted(pilot.all_specs(), key=lambda x:x.task.id):
            conditions=[(p,v) for p in pilot.POLICIES for v in (False,True)]
            random.Random(seed+int(hashlib.sha256(spec.task.id.encode()).hexdigest()[:8],16)).shuffle(conditions)
            for policy, enabled in conditions:
                rows.append({'design_id':f'{seed}:{spec.task.id}:{policy}:verify-{int(enabled)}',
                             'seed':seed,'task_id':spec.task.id,'policy':policy,'verify_enabled':enabled,
                             'family':spec.task.family,'original_split':spec.task.split})
    return {'protocol':PROTOCOL,'planned_episodes':len(rows),'study_order':rows,'seeds':list(SEEDS),
            'task_manifest_sha256':pilot.task_digest(),'study_cap_usd':STUDY_CAP,'maximum_wall_seconds':MAX_SECONDS,
            'maximum_model_calls_per_episode':6,'maximum_decisions':10,'max_output_tokens':4096,
            'maximum_tokens_per_episode':100000,'episode_cap_usd':1.0,'rate_limit_retries':2,
            'models':['openai/gpt-oss-20b','openai/gpt-oss-120b'],'provider':'coreweave/fp4','temperature':.2,
            'catalog_scope':'All27 tasks and families were previously inspected/published. No fresh holdout or new upstream issue claim.',
            'estimand':'Within each original primary family and seed, average paired success and accounted cost difference between shared VERIFY and no-VERIFY; report all six policies.',
            'analysis':'Descriptive family/seed summaries with every cell, failure, missing result and effect direction. Validation and source-derived slices remain separate. No significance, unseen-task or learned-verification claim.',
            'policy_training':'Frozen historical train-only controllers; no fitting/tuning on these outcomes.',
            'fairness':'Identical model-call/token/decision ceilings; VERIFY consumes its actual decision/CPU budget. Actual resource use need not be equal.',
            'order':'Fixed seed/task order; policy/verification conditions deterministically shuffled within task; order is frozen before calls.'}


def sources():
    paths=list((ROOT/'forgerl').rglob('*.py'))+[ROOT/'scripts/replicate_forgebench.py',ROOT/'requirements.lock',ROOT/'forgerl/bench/boltons_source.json']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def freeze(prior, commit, snapshot):
    pilot.validate_fixture_receipt(prior['fixture_receipt'])
    if os.environ.get('FORGEBENCH_EVALUATED_IMAGE') != prior['fixture_receipt']['sandbox_image']:
        raise ValueError('Existing validated executor image required')
    controllers=prior['controllers']; claimed=controllers['sha256']
    if digest({k:v for k,v in controllers.items() if k!='sha256'})!=claimed:
        raise ValueError('Historical controller hash mismatch')
    if len(commit)!=40:
        raise ValueError('Committed source required')
    value={'protocol':PROTOCOL,'frozen_at_utc':utc_now(),'source_commit':commit,'sources':sources(),
           'configuration':plan(),'controllers':controllers,'fixture_receipt':prior['fixture_receipt'],
           'provider_snapshot':snapshot,'prior_pilot_sha256':prior['sha256'],
           'scope':'New repeated execution and explicit ablation, not a new held-out sample or extension of the old dataset.'}
    value['sha256']=digest(value)
    return value


def verify(frozen):
    if frozen['sha256']!=digest({k:v for k,v in frozen.items() if k!='sha256'}):
        raise ValueError('Freeze hash mismatch')
    if frozen['configuration']!=plan() or frozen['sources']!=sources():
        raise ValueError('Frozen source/catalog/configuration changed')
    pilot.validate_fixture_receipt(frozen['fixture_receipt'])
    if os.environ.get('FORGEBENCH_EVALUATED_IMAGE')!=frozen['fixture_receipt']['sandbox_image']:
        raise ValueError('Executor image differs')


async def run(provider, output, frozen):
    verify(frozen)
    meta=provider.metadata()
    if meta.get('provider')!='openrouter' or meta.get('routing',{}).get('only')!=['coreweave/fp4'] or meta.get('routing',{}).get('allow_fallbacks') is not False:
        raise ValueError('Pinned provider required')
    bounded=CappedProvider(provider,STUDY_CAP)
    writer=Writer(output)
    manifest={'protocol':PROTOCOL,'freeze_sha256':frozen['sha256'],'started_at':utc_now(),'status':'running',
              'completed':0,'planned':len(plan()['study_order']),'budget_before':bounded.start_budget,
              'accounted_cost_delta_usd':0,'provider':meta,'active':None}
    writer.write('freeze.json',frozen);writer.write('manifest.json',manifest)
    specs={s.task.id:s for s in pilot.all_specs()}
    completed=set();deadline=asyncio.get_running_loop().time()+MAX_SECONDS
    try:
        for row in frozen['configuration']['study_order']:
            if bounded.remaining()<.001:raise BudgetExceeded('Campaign allowance exhausted')
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining<=0:raise TimeoutError('Study wall limit reached')
            episode=AblationEpisode(specs[row['task_id']],bounded,row['policy'],controllers=frozen['controllers'],
                verify_enabled=row['verify_enabled'],seed=row['seed'],max_steps=6,max_decisions=10,
                max_verifications=2,max_cost_usd=1.0,rate_limit_retries=2)
            manifest['active']={**row,'run_id':episode.id};writer.write('manifest.json',manifest)
            episode.event_callback=lambda event, ident=episode.id:writer.append('events.jsonl',{'run_id':ident,'event':event})
            result=await asyncio.wait_for(run_episode(episode,selector=episode.select),timeout=remaining)
            result['design']=row;writer.run(result,'exposed_replication')
            completed.add(row['design_id'])
            manifest.update(completed=len(completed),active=None,accounted_cost_delta_usd=bounded.spent())
            writer.write('manifest.json',manifest)
            print(json.dumps({'completed':len(completed),'planned':manifest['planned'],'cost':bounded.spent()}),flush=True)
            if result['status']=='budget_exhausted':raise BudgetExceeded('Episode/shared cap reached')
    except BaseException as exc:
        manifest['stop_reason']=type(exc).__name__
        if isinstance(exc,asyncio.CancelledError):manifest['stop_reason']='cancelled'
    finally:
        manifest.update(status='complete' if len(completed)==manifest['planned'] else 'incomplete',finished_at=utc_now(),
                        missing=[r for r in frozen['configuration']['study_order'] if r['design_id'] not in completed],
                        accounted_cost_delta_usd=bounded.spent())
        writer.write('manifest.json',manifest)
    return manifest
