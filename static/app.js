'use strict';

// API data is rendered as text, never interpreted as markup or executable code.
const ForgeUI = (() => {
  const terminalStates = new Set(['complete', 'completed', 'succeeded', 'failed', 'error', 'cancelled', 'canceled', 'stopped', 'budget_exhausted', 'unavailable', 'solved', 'unsolved']);
  const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
  const count = value => number(value) === null ? '—' : value.toLocaleString('en-US', {maximumFractionDigits: 0});
  const cost = value => number(value) === null ? '—' : '$' + value.toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 4});
  const duration = value => number(value) === null ? '—' : value < 60 ? `${value.toFixed(1)}s` : `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
  const ratio = (passed, total) => number(passed) === null || number(total) === null || total === 0 ? '—' : `${count(passed)} / ${count(total)}`;
  const percentage = value => number(value) === null ? '—' : `${(value * 100).toFixed(1)}%`;
  const label = value => String(value ?? '').replace(/[_-]+/g, ' ').replace(/^\w/, ch => ch.toUpperCase());
  const isTerminal = status => terminalStates.has(String(status).toLowerCase());
  const isRunId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(value);
  const timestamp = value => typeof value === 'number' && value < 1e12 ? value * 1000 : value;
  function safeLink(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try { const url = new URL(value, typeof location === 'undefined' ? 'https://stelioszach.com/demos/forgerl/' : location.href); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; }
  }
  function errorMessage(body, fallback = 'The request could not be completed. Please try again.') {
    if (typeof body?.detail?.message === 'string') return body.detail.message;
    if (typeof body?.detail === 'string') return body.detail;
    return fallback;
  }
  function stateOf(run) {
    if (!run) return {text: 'Not run', className: ''};
    if (!isTerminal(run.status)) return {text: label(run.status || 'queued'), className: 'active'};
    if (run.solved === true) return {text: 'Solved', className: 'success'};
    if (run.solved === false) return {text: 'Not solved', className: 'failure'};
    return {text: label(run.status), className: ['failed', 'error'].includes(run.status) ? 'failure' : ''};
  }
  return {number, count, cost, duration, ratio, percentage, label, isTerminal, isRunId, timestamp, safeLink, errorMessage, stateOf};
})();

if (typeof module !== 'undefined' && module.exports) module.exports = ForgeUI;

if (typeof document !== 'undefined') (() => {
  const $ = id => document.getElementById(id);
  const state = {meta: null, tasks: [], task: null, taskEpoch: 0, run: null, runEpoch: 0, events: [], eventSeq: 0, pollTimer: null, pollFailures: 0, csrf: null, submitting: false, gallery: [], benchmark: null};
  const {count, cost, duration, ratio, percentage, label, isTerminal, isRunId, safeLink, errorMessage, stateOf} = ForgeUI;
  const api = path => new URL(`api/${path}`, new URL('./', location.href));
  const text = (id, value) => { $(id).textContent = value ?? ''; };
  function element(tag, className, content) { const el = document.createElement(tag); if (className) el.className = className; if (content !== undefined) el.textContent = content; return el; }
  function announce(message) { text('announcer', message); }
  function alertError(message) { $('global-alert').hidden = !message; text('global-alert', message); }
  function setLink(id, url) { const el = $(id); const safe = safeLink(url); el.hidden = !safe; if (safe) { el.href = safe; el.rel = 'noopener'; } else el.removeAttribute('href'); }
  function dateTime(value) { const d = new Date(ForgeUI.timestamp(value)); return Number.isNaN(d.valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}).format(d); }
  function eventTime(value) { const d = new Date(ForgeUI.timestamp(value)); return Number.isNaN(d.valueOf()) ? '' : d.toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'}); }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(api(path), {...options, credentials: 'same-origin', signal: controller.signal, headers: {'Accept': 'application/json', ...(options.headers || {})}});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { const error = new Error(errorMessage(body, response.status === 429 ? 'The public run limit has been reached. Inspect a recorded run while the limit resets.' : `The service returned an error (${response.status}). Please try again.`)); error.status = response.status; error.code = body?.detail?.code; throw error; }
      return body;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The service took too long to respond. Refresh to check whether your run was accepted before starting another.');
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function switchView(view, moveFocus = false) {
    if (!['workbench', 'experiments', 'methodology'].includes(view)) view = 'workbench';
    document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== view; });
    document.querySelectorAll('.top-nav [data-view]').forEach(link => { const active = link.dataset.view === view; link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); });
    // View navigation starts above the sticky header. "auto" inherits the
    // document's smooth scroll and can leave the new title behind that header.
    if (moveFocus) { $('main').focus({preventScroll: true}); window.scrollTo({top: 0, left: 0, behavior: 'instant'}); }
  }
  document.querySelectorAll('[data-view]').forEach(link => link.addEventListener('click', event => { event.preventDefault(); const view = link.dataset.view; history.replaceState(null, '', `${location.pathname}${location.search}#${view}`); switchView(view, true); }));
  window.addEventListener('hashchange', () => switchView(location.hash.slice(1), true));

  function selectTab(name, focus = false) {
    document.querySelectorAll('[data-tab]').forEach(button => { const active = button.dataset.tab === name; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; $(`panel-${button.dataset.tab}`).hidden = !active; if (active && focus) button.focus(); });
  }
  const tabs = [...document.querySelectorAll('[data-tab]')];
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => selectTab(button.dataset.tab));
    button.addEventListener('keydown', event => { let next; if (event.key === 'ArrowRight') next = (index + 1) % tabs.length; else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length; else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = tabs.length - 1; else return; event.preventDefault(); selectTab(tabs[next].dataset.tab, true); });
  });

  function renderSource(target, source) {
    target.replaceChildren();
    if (typeof source !== 'string' || !source.length) { target.textContent = 'Source is not available for this run.'; return; }
    source.split('\n').forEach((line, index) => { const row = element('span', 'source-line'); const lineNumber = element('span', 'line-no', String(index + 1)); lineNumber.setAttribute('aria-hidden', 'true'); row.append(lineNumber, document.createTextNode(line || ' ')); target.append(row); });
  }
  function renderTask(task) {
    text('task-title', task.title || task.id);
    text('task-description', task.description || task.summary || 'No task description is available.');
    text('task-split', task.split ? `${label(task.split)} split` : 'Curated task');
    text('task-filename', task.filename || 'solution.py');
    const taskLabels = new Map();
    for (const tag of [task.family, task.difficulty, ...(task.tags || [])].filter(Boolean)) {
      const display = label(tag).trim();
      const key = display.toLocaleLowerCase('en-US');
      if (key && !taskLabels.has(key)) taskLabels.set(key, display);
    }
    $('task-tags').replaceChildren(...[...taskLabels.values()].slice(0, 5).map(tag => element('span', 'tag', tag)));
    renderSource($('task-source'), task.source);
    const tests = task.public_tests || [];
    text('public-test-count', count(task.public_tests_count ?? tests.length));
    $('task-tests').replaceChildren();
    if (tests.length) tests.forEach(test => $('task-tests').append(element('li', '', typeof test === 'string' ? test : (test.description || test.name || 'Visible regression test'))));
    else $('task-tests').append(element('li', '', 'Case-level descriptions are not available. The run inspector will report the measured test counts.'));
  }
  async function loadTask(id) {
    const epoch = ++state.taskEpoch;
    state.task = null;
    updateRunButton();
    text('task-title', 'Loading task…');
    try { const task = await request(`tasks/${encodeURIComponent(id)}`); if (epoch !== state.taskEpoch) return; state.task = task; renderTask(task); }
    catch (error) { if (epoch !== state.taskEpoch) return; text('task-title', 'Task could not be loaded'); text('task-description', error.message); $('task-source').textContent = 'Select another task or reload the page to try again.'; }
    updateRunButton();
  }
  $('task-select').addEventListener('change', () => loadTask($('task-select').value));
  function updatePolicy() { const policy = state.meta?.policies?.find(item => item.id === $('policy-select').value); text('policy-description', policy?.description || 'Only curated tasks run in this workspace. No code upload or repository access.'); }
  $('policy-select').addEventListener('change', updatePolicy);
  function updateRunButton() {
    const running = state.run && !isTerminal(state.run.status);
    $('run-button').disabled = !state.meta?.live?.available || !state.task || !$('policy-select').value || $('policy-select').selectedOptions[0]?.disabled || state.submitting || !!running;
    $('run-button').querySelector('span').textContent = state.submitting ? 'Starting…' : running ? 'Run in progress' : 'Run repair';
  }
  function renderMeta(meta) {
    const oldPolicy = $('policy-select').value;
    state.meta = meta;
    $('service-indicator').className = `service-indicator ${meta.live?.available ? 'available' : 'unavailable'}`;
    text('service-status', meta.live?.available ? 'Live inference available' : 'Live inference unavailable');
    $('live-notice').hidden = !!meta.live?.available;
    text('live-notice', meta.live?.available ? '' : `${meta.live?.reason || 'Live model calls are currently unavailable.'} Recorded runs and experiment artifacts remain available to inspect.`);
    $('policy-select').replaceChildren();
    for (const policy of meta.policies || []) { const option = element('option', '', policy.label || label(policy.id)); option.value = policy.id; option.disabled = policy.available === false || (policy.id === 'adaptive' && meta.evidence_status === 'not_trained'); $('policy-select').append(option); }
    if ((meta.policies || []).some(policy => policy.id === oldPolicy)) $('policy-select').value = oldPolicy;
    if (!meta.policies?.length) { const option = element('option', '', 'No policies available'); option.value = ''; $('policy-select').append(option); }
    $('policy-select').disabled = !meta.policies?.length;
    updatePolicy();
    text('version-label', meta.version ? `ForgeRL · ${meta.version}` : 'ForgeRL');
    if (meta.evidence_status === 'not_trained') text('evidence-status', 'The adaptive controller is not trained. Live runs use the available baseline policies; no learned-policy improvement is claimed.');
    else if (meta.evidence_status === 'trained_controller') text('evidence-status', 'A trained controller artifact is loaded. Consult the recorded held-out comparisons to assess its measured performance and limitations.');
    else if (typeof meta.evidence_status === 'string') text('evidence-status', meta.evidence_status);
    else if (meta.evidence_status?.description) text('evidence-status', meta.evidence_status.description);
    setLink('source-link', meta.links?.source);
    setLink('methodology-source', meta.links?.methodology);
    updateRunButton();
  }
  async function loadMeta() { const meta = await request('meta'); renderMeta(meta); }

  function applyRunState(target, run) { const status = stateOf(run); target.textContent = status.text; target.className = `run-state ${status.className}`; }
  function renderPatch(diff) {
    const hasDiff = typeof diff === 'string' && diff.trim().length > 0;
    $('patch-code').hidden = !hasDiff; $('patch-empty').hidden = hasDiff;
    $('patch-code').replaceChildren();
    if (hasDiff) for (const line of diff.split('\n')) { let type = ''; if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ')) type = 'file'; else if (line.startsWith('+')) type = 'add'; else if (line.startsWith('-')) type = 'remove'; else if (line.startsWith('@@')) type = 'hunk'; $('patch-code').append(element('span', `diff-line ${type}`, line || ' ')); }
    if (!hasDiff && state.run) { $('patch-empty').querySelector('h3').textContent = isTerminal(state.run.status) ? 'No patch recorded.' : 'Waiting for a candidate.'; $('patch-empty').querySelector('p').textContent = isTerminal(state.run.status) ? 'This run has no recorded source change. Open the trace to inspect its outcome and stop reason.' : 'The repair trace will update as actual execution events arrive.'; }
  }
  function renderTests(run) {
    const container = $('tests-content'); container.replaceChildren();
    const publicResult = run.evidence?.public || run.evidence?.public_tests || run.evidence?.public_result;
    const groups = [{title: 'Public regression tests', passed: run.public_passed, total: run.public_total, cases: Array.isArray(publicResult?.cases) ? publicResult.cases : [], note: 'These checks are observable to the repair policy.'}, {title: 'Held-out checks', passed: isTerminal(run.status) ? run.heldout_passed : null, total: run.heldout_total, cases: [], note: 'Held-out inputs and expected outputs are excluded from the public interface and model prompt.'}];
    for (const group of groups) {
      const section = element('section', 'test-group'); const heading = element('h3', '', group.title); heading.append(element('span', '', ratio(group.passed, group.total))); section.append(heading);
      if (group.cases.length) group.cases.forEach(test => { const row = element('div', 'test-row'); row.append(element('p', '', test.name || 'Regression test'), element('span', `test-mark ${test.passed === true ? 'pass' : test.passed === false ? 'fail' : ''}`, test.passed === true ? 'PASS' : test.passed === false ? 'FAIL' : 'NOT RUN')); section.append(row); });
      else { const measured = ForgeUI.number(group.passed) !== null && ForgeUI.number(group.total) !== null && group.total > 0; section.append(element('p', 'test-note', measured ? `${count(group.passed)} of ${count(group.total)} checks passed. Individual case details are not exposed here.` : 'No completed evaluation recorded.')); }
      section.append(element('p', 'test-note', group.note)); container.append(section);
    }
  }
  function eventMetadata(event) {
    // Only small, documented measurements are presented. Never dump arbitrary provider payloads.
    const data = event.data || {};
    const fields = [['action', 'Action'], ['model', 'Model'], ['model_id', 'Model'], ['tokens', 'Tokens'], ['total_tokens', 'Tokens'], ['cost_usd', 'Cost'], ['elapsed_s', 'Time'], ['passed', 'Passed'], ['total', 'Total']];
    const seen = new Set();
    return fields.filter(([key, name]) => data[key] !== undefined && data[key] !== null && !seen.has(name) && seen.add(name)).map(([key, name]) => `${name}: ${key === 'cost_usd' ? cost(data[key]) : key === 'elapsed_s' ? duration(data[key]) : String(data[key]).slice(0, 120)}`);
  }
  function renderEvents() {
    text('trace-count', count(state.events.length));
    const list = $('event-list'); list.replaceChildren();
    if (!state.events.length) { list.append(element('li', 'empty-copy', 'No execution events have been recorded yet.')); return; }
    for (const event of state.events) {
      const item = element('li', 'event-row'); const heading = element('div', 'event-heading'); const time = element('time', '', eventTime(event.at)); if (event.at) time.dateTime = event.at; heading.append(element('h3', '', event.title || label(event.kind)), time); item.append(heading);
      if (event.message) item.append(element('p', '', event.message));
      const metadata = eventMetadata(event); if (metadata.length) { const detail = element('div', 'event-data'); metadata.forEach(value => detail.append(element('span', '', value))); item.append(detail); }
      list.append(item);
    }
  }
  function mergeEvents(events) {
    const bySeq = new Map(state.events.map(event => [event.seq, event]));
    for (const event of events || []) if (typeof event.seq === 'number') bySeq.set(event.seq, event);
    state.events = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
    state.eventSeq = state.events.length ? Math.max(state.eventSeq, ...state.events.map(event => event.seq)) : state.eventSeq;
    renderEvents();
  }
  function renderRun(run) {
    state.run = run;
    text('run-mode', run.mode === 'recorded' ? 'Recorded run' : run.mode === 'live' ? 'Live run' : 'Run evidence');
    text('result-title', run.task_title || state.tasks.find(task => task.id === run.task_id)?.title || 'Repair run');
    text('run-caption', `${label(run.policy || 'Policy')} · ${dateTime(run.created_at)} · ${run.id}`);
    applyRunState($('run-status'), run);
    text('metric-public', ratio(run.public_passed, run.public_total));
    text('metric-heldout', isTerminal(run.status) ? ratio(run.heldout_passed, run.heldout_total) : '—');
    text('metric-steps', count(run.steps)); text('metric-tokens', count(run.tokens)); text('metric-cost', cost(run.cost_usd)); text('metric-time', duration(run.elapsed_s));
    renderPatch(run.diff); renderSource($('final-source'), run.final_source); renderTests(run);
    if (Array.isArray(run.events)) mergeEvents(run.events);
    const reason = run.error || run.stop_reason;
    const costBasis = run.evidence?.cost_basis;
    text('run-explanation', (reason ? `Run outcome: ${String(reason).replace(/_/g, ' ')}` : isTerminal(run.status) ? 'Recorded test results apply to this candidate and task only.' : 'The run is executing. Events and measured results update automatically.') + (costBasis ? ` · Cost: ${costBasis}.` : ''));
    $('refresh-run').hidden = false;
    setLink('download-patch', run.diff ? api(`runs/${encodeURIComponent(run.id)}/patch`).href : null);
    setLink('download-trace', api(`runs/${encodeURIComponent(run.id)}/export`).href);
    $('download-patch').download = `${run.id}.patch`; $('download-trace').download = `${run.id}.json`;
    updateRunButton();
  }
  function stopPolling() { clearTimeout(state.pollTimer); state.pollTimer = null; }
  function schedulePoll(id, epoch) { stopPolling(); if (!document.hidden && epoch === state.runEpoch) state.pollTimer = setTimeout(() => pollRun(id, epoch), 1500); }
  async function pollRun(id, epoch) {
    if (epoch !== state.runEpoch || !isRunId(id)) return;
    try {
      const response = await request(`runs/${encodeURIComponent(id)}/events?after=${state.eventSeq}`);
      if (epoch !== state.runEpoch) return;
      mergeEvents(response.events);
      if (typeof response.next_seq === 'number') state.eventSeq = Math.max(state.eventSeq, response.next_seq);
      const run = await request(`runs/${encodeURIComponent(id)}`);
      if (epoch !== state.runEpoch) return;
      state.pollFailures = 0; renderRun(run);
      if (isTerminal(run.status)) { stopPolling(); announce(`Run finished: ${stateOf(run).text}.`); loadGallery().catch(() => {}); loadMeta().catch(() => {}); }
      else schedulePoll(id, epoch);
    } catch (error) {
      if (epoch !== state.runEpoch) return;
      state.pollFailures += 1;
      if (state.pollFailures < 3) schedulePoll(id, epoch);
      else { stopPolling(); text('run-explanation', 'Updates paused because the service could not be reached. Use Refresh selected run to reconnect; the run may still be executing.'); announce('Run updates paused. Refresh to reconnect.'); }
    }
  }
  async function inspectRun(id, {navigate = true} = {}) {
    if (!isRunId(id)) { alertError('The run link is not valid. Choose a run from the gallery.'); return; }
    stopPolling(); const epoch = ++state.runEpoch; state.events = []; state.eventSeq = 0; state.pollFailures = 0;
    if (navigate) { switchView('workbench'); const url = new URL(location.href); url.searchParams.set('run', id); url.hash = 'workbench'; history.replaceState(null, '', url); }
    alertError(''); text('result-title', 'Loading run…');
    document.querySelector('.result-pane').setAttribute('aria-busy', 'true');
    try {
      const run = await request(`runs/${encodeURIComponent(id)}`);
      if (epoch !== state.runEpoch) return;
      renderRun(run); renderGallery();
      if (run.task_id && state.tasks.some(task => task.id === run.task_id)) { $('task-select').value = run.task_id; await loadTask(run.task_id); }
      if (epoch !== state.runEpoch) return;
      if (!run.events?.length) { const response = await request(`runs/${encodeURIComponent(id)}/events?after=0`); if (epoch !== state.runEpoch) return; mergeEvents(response.events); }
      if (!isTerminal(run.status)) schedulePoll(id, epoch);
      announce(`Inspecting ${run.task_title || 'repair run'}. ${stateOf(run).text}.`);
    } catch (error) { if (epoch !== state.runEpoch) return; alertError(error.message); text('result-title', 'Run unavailable'); text('run-caption', state.run ? 'The last loaded run is shown below. Refresh to reconnect.' : 'Choose another run or refresh to try again.'); }
    finally { if (epoch === state.runEpoch) document.querySelector('.result-pane').setAttribute('aria-busy', 'false'); }
  }
  $('refresh-run').addEventListener('click', () => { if (state.run?.id) inspectRun(state.run.id, {navigate: false}); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopPolling(); else if (state.run && !isTerminal(state.run.status)) pollRun(state.run.id, state.runEpoch); });
  window.addEventListener('pagehide', stopPolling);

  async function ensureSession() { const session = await request('session', {method: 'POST'}); if (typeof session.csrf_token !== 'string') throw new Error('A secure run session could not be established. Reload the page and try again.'); state.csrf = session.csrf_token; }
  async function submitRun() {
    if (state.submitting || $('run-button').disabled) return;
    const taskId = $('task-select').value; const policy = $('policy-select').value;
    if (!state.tasks.some(task => task.id === taskId) || !state.meta?.policies?.some(item => item.id === policy)) return;
    state.submitting = true; updateRunButton(); alertError('');
    try {
      if (!state.csrf) await ensureSession();
      const send = () => request('runs', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf}, body: JSON.stringify({task_id: taskId, policy})});
      let created;
      try { created = await send(); } catch (error) { if (error.status !== 403) throw error; await ensureSession(); created = await send(); }
      if (!isRunId(created.id)) throw new Error('The service did not return a valid run identifier. Refresh recent runs before trying again.');
      renderRun({...created, task_id: taskId, task_title: state.task?.title, policy});
      selectTab('trace'); await inspectRun(created.id); announce('Repair submitted. The execution trace is open.');
      loadGallery().catch(() => {});
    } catch (error) { alertError(error.message); if ([429, 503].includes(error.status)) loadMeta().catch(() => {}); }
    finally { state.submitting = false; updateRunButton(); }
  }
  $('run-form').addEventListener('submit', event => { event.preventDefault(); submitRun(); });

  function renderGallery() {
    const gallery = $('run-gallery'); gallery.replaceChildren();
    if (!state.gallery.length) { gallery.append(element('p', 'empty-copy', 'No runs have been recorded yet. Once a repair executes, its outcome and trace will appear here.')); return; }
    for (const run of state.gallery) {
      if (!isRunId(run.id)) continue;
      const button = element('button', `gallery-run ${run.id === state.run?.id ? 'selected' : ''}`); button.type = 'button'; button.setAttribute('aria-label', `Inspect ${run.task_title || run.task_id}, ${label(run.policy)}, ${stateOf(run).text}`);
      const title = element('div', 'gallery-title'); title.append(element('strong', '', run.task_title || run.task_id), element('small', '', `${run.mode === 'recorded' ? 'RECORDED' : run.mode === 'live' ? 'LIVE' : 'RUN'} · ${dateTime(run.created_at)}`));
      const policy = element('div', 'gallery-cell gallery-policy'); policy.append(element('small', '', 'Decision policy'), document.createTextNode(label(run.policy)));
      const status = element('span'); applyRunState(status, run);
      const spend = element('div', 'gallery-cell gallery-cost'); spend.append(element('small', '', 'Est. cost'), element('span', 'number', cost(run.cost_usd)));
      const time = element('div', 'gallery-cell gallery-time'); time.append(element('small', '', 'Elapsed'), element('span', 'number', duration(run.elapsed_s)));
      const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); arrow.setAttribute('viewBox', '0 0 24 24'); arrow.setAttribute('aria-hidden', 'true'); const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', 'M5 12h14m-5-5 5 5-5 5'); arrow.append(path);
      button.append(title, policy, status, spend, time, arrow); button.addEventListener('click', () => { inspectRun(run.id); document.querySelector('.result-pane').scrollIntoView({behavior: 'auto', block: 'start'}); });
      gallery.append(button);
    }
  }
  async function loadGallery() { const response = await request('runs?limit=12'); state.gallery = Array.isArray(response.runs) ? response.runs : []; renderGallery(); }
  $('refresh-gallery').addEventListener('click', async () => { $('refresh-gallery').disabled = true; try { await loadGallery(); announce('Recent runs refreshed.'); } catch (error) { $('run-gallery').replaceChildren(element('p', 'empty-copy', error.message)); } finally { $('refresh-gallery').disabled = false; } });

  function renderBenchmark(benchmark) {
    state.benchmark = benchmark;
    const complete = benchmark.status === 'complete'; text('benchmark-status', complete ? 'Recorded evaluation' : 'Not run');
    text('benchmark-description', complete ? (benchmark.methodology?.description || 'Recorded policy outcomes on the authored task suite. See provenance and limitations before interpreting the comparison.') : 'No completed benchmark has been published. Solve rates, costs and policy improvements are not claimed.');
    const table = $('benchmark-body'); table.replaceChildren();
    if (complete && benchmark.summary?.length) for (const row of benchmark.summary) { const tr = element('tr'); [label(row.policy), count(row.n), count(row.solved), percentage(row.solve_rate), ForgeUI.number(row.mean_steps) === null ? '—' : row.mean_steps.toFixed(2), ForgeUI.number(row.mean_tokens) === null ? '—' : row.mean_tokens.toLocaleString('en-US', {maximumFractionDigits: 1}), cost(row.mean_cost_usd), duration(row.mean_latency_s)].forEach(value => tr.append(element('td', '', value))); table.append(tr); }
    else { const row = element('tr'); const cell = element('td', '', 'No benchmark measurements available. This table will show actual recorded outcomes when an evaluation is complete.'); cell.colSpan = 8; row.append(cell); table.append(row); }
    const pairs = $('paired-runs'); pairs.replaceChildren();
    if (!benchmark.paired_runs?.length) pairs.append(element('p', 'empty-copy', 'No paired evaluation runs are available yet. Individual public runs can be inspected in the workbench.'));
    else for (const task of benchmark.paired_runs) { const section = element('section', 'paired-task'); section.append(element('h3', '', task.task_title || task.task_id)); for (const run of task.runs || []) { const button = element('button', 'paired-run'); button.type = 'button'; button.append(element('strong', '', label(run.policy)), element('small', '', `${stateOf(run).text} · ${cost(run.cost_usd)} · ${count(run.tokens)} tokens`)); if (isRunId(run.id)) button.addEventListener('click', () => { inspectRun(run.id); window.scrollTo({top: 0, behavior: 'auto'}); }); else button.disabled = true; section.append(button); } pairs.append(section); }
    if (benchmark.limitations?.length) $('benchmark-limitations').replaceChildren(...benchmark.limitations.map(limit => element('li', '', typeof limit === 'string' ? limit : limit.description || JSON.stringify(limit))));
    const provenance = $('benchmark-provenance'); provenance.replaceChildren();
    const entries = Object.entries(benchmark.provenance || {}).filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value));
    if (!entries.length) entries.push(['status', complete ? 'No additional provenance provided.' : 'No evaluation artifact published.']);
    for (const [key, value] of entries) { const row = element('div'); row.append(element('dt', '', label(key)), element('dd', '', String(value))); provenance.append(row); }
  }

  async function initialize() {
    switchView(location.hash.slice(1));
    const results = await Promise.allSettled([loadMeta(), request('tasks'), loadGallery(), request('benchmark')]);
    if (results[0].status === 'rejected') { state.meta = null; $('service-indicator').className = 'service-indicator unavailable'; text('service-status', 'Service unavailable'); text('policy-description', 'The service could not be reached. Reload the page to try again.'); $('policy-select').replaceChildren(element('option', '', 'Service unavailable')); alertError('The workspace service could not be reached. No run has been started. Please reload to reconnect.'); }
    if (results[1].status === 'fulfilled') {
      state.tasks = Array.isArray(results[1].value.tasks) ? results[1].value.tasks : [];
      $('task-select').replaceChildren();
      state.tasks.forEach(task => { const option = element('option', '', task.title || task.id); option.value = task.id; $('task-select').append(option); });
      $('task-select').disabled = !state.tasks.length;
      if (state.tasks.length) await loadTask(state.tasks[0].id);
      else { $('task-select').append(element('option', '', 'No tasks available')); text('task-title', 'No tasks available'); text('task-description', 'The task catalog has not been published.'); $('task-source').textContent = 'No source loaded.'; }
    } else { $('task-select').replaceChildren(element('option', '', 'Tasks unavailable')); text('task-title', 'Task catalog unavailable'); text('task-description', 'The task service could not be reached. Reload the page to reconnect.'); $('task-source').textContent = 'No source loaded.'; }
    if (results[2].status === 'rejected') $('run-gallery').replaceChildren(element('p', 'empty-copy', 'Recorded runs could not be loaded. Use Refresh runs to try again.'));
    if (results[3].status === 'fulfilled') renderBenchmark(results[3].value);
    else { text('benchmark-status', 'Unavailable'); text('benchmark-description', 'The experiment service could not be reached. No measurements are shown.'); const row = element('tr'); const cell = element('td', '', 'Benchmark data is currently unavailable. Reload to try again.'); cell.colSpan = 8; row.append(cell); $('benchmark-body').replaceChildren(row); }
    const requestedRun = new URL(location.href).searchParams.get('run');
    if (requestedRun) await inspectRun(requestedRun, {navigate: false});
    updateRunButton();
  }
  initialize().catch(() => alertError('The workspace did not initialize correctly. Reload the page to reconnect.'));
})();
