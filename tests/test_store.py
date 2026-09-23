from concurrent.futures import ThreadPoolExecutor

import pytest

from forgerl.store import AdmissionError, BudgetExceeded, Store


def test_concurrent_reservations_cannot_overspend(tmp_path):
    store=Store(tmp_path/'state.sqlite3')
    store.CAPS={'research':200_000,'public':100_000}
    def reserve(_):
        try:return store.reserve('research','test',100_000)
        except BudgetExceeded:return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted=list(pool.map(reserve,range(8)))
    assert sum(x is not None for x in accepted)==2
    assert store.budget('research')['remaining_usd']==0


def test_unknown_provider_outcome_retains_budget_across_restart(tmp_path):
    path=tmp_path/'state.sqlite3';store=Store(path)
    ident=store.reserve('research','test',80_000)
    store.settle(ident,None)
    assert Store(path).budget('research')['charged_usd']==0.08
    with pytest.raises(ValueError):store.settle(ident,0)


def test_actual_token_estimate_releases_unused_reservation(tmp_path):
    store=Store(tmp_path/'state.sqlite3');ident=store.reserve('research','test',80_000)
    store.settle(ident,1000,{'total_tokens':100})
    assert store.budget('research')['charged_usd']==0.001


def test_unexpected_higher_usage_disables_further_inference(tmp_path):
    store=Store(tmp_path/'state.sqlite3');ident=store.reserve('research','test',1000)
    store.settle(ident,2000)
    assert store.budget('research')['disabled']
    with pytest.raises(BudgetExceeded):store.reserve('public','test',1000)


def test_queue_limits_and_restart_do_not_replay_spent_run(tmp_path):
    store=Store(tmp_path/'state.sqlite3')
    first=store.admit('task','fixed','session','ip')
    store.admit('task','fixed','session','ip')
    with pytest.raises(AdmissionError):store.admit('task','fixed','session','ip')
    assert store.claim()['id']==first
    store.recover()
    assert store.run(first)['status']=='interrupted'
    assert store.claim()['id']!=first


def test_public_run_projection_never_exposes_identifiers(tmp_path):
    store=Store(tmp_path/'state.sqlite3');ident=store.admit('task','fixed','private_session_hash','private_ip_hash')
    row=store.run(ident)
    assert 'session_hash' not in row and 'ip_hash' not in row


def test_durable_ordered_events(tmp_path):
    store=Store(tmp_path/'state.sqlite3');ident=store.admit('task','fixed','s','i')
    for i in range(3):store.add_event(ident,{'kind':'test','data':i})
    assert [x['seq'] for x in store.events(ident,1)]==[2,3]
