const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const script = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const task = {id: 'repair-slug', title: 'Slug normalization', family: 'text', split: 'train', difficulty: 'easy', tags: ['text', 'Text', 'python regression'], description: 'Preserve nonempty words.', source: 'def slug(value):\n    return "<img src=x onerror=alert(1)>"\n', public_tests_count: 2, public_tests: [{name: 'Empty words'}, {name: 'Repeated spaces'}]};
const meta = {version: 'test', live: {available: true}, policies: [{id: 'fixed', label: 'Fixed', description: 'A short budget.'}], links: {source: 'javascript:alert(1)'}, evidence_status: 'Not trained.'};
const completed = {id: 'run-1', status: 'completed', solved: false, mode: 'live', task_id: task.id, task_title: task.title, policy: 'fixed', public_passed: 2, public_total: 2, heldout_passed: 1, heldout_total: 2, steps: 1, tokens: 100, cost_usd: 0.001, elapsed_s: 2, created_at: '2026-09-23T00:00:00Z', diff: '--- a/solution.py\n+++ b/solution.py\n@@ -1 +1 @@\n-<script>alert(1)</script>\n+safe', final_source: 'def slug(value):\n    return value', evidence: {public: {cases: [{name: '<img onerror=alert(1)>', passed: true}]}}, events: [{seq: 1, kind: 'candidate', title: '<script>bad()</script>', message: 'Candidate evaluated.', at: '2026-09-23T00:00:01Z', data: {tokens: 100, secret: 'do-not-show'}}]};
const response = (body, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => body});
const settle = async () => { for (let i = 0; i < 16; i++) await new Promise(resolve => setImmediate(resolve)); };
function page(handler) {
  const dom = new JSDOM(html, {url: 'https://stelioszach.com/demos/forgerl/', runScripts: 'outside-only', pretendToBeVisual: true});
  dom.window.scrollTo = () => {};
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.fetch = handler;
  dom.window.eval(script);
  return dom;
}
function baseHandler(url) {
  const route = new URL(url).pathname;
  if (route.endsWith('/meta')) return response(meta);
  if (route.endsWith('/tasks')) return response({tasks: [task]});
  if (route.endsWith('/tasks/repair-slug')) return response(task);
  if (route.endsWith('/benchmark')) return response({status: 'not_run', summary: [], paired_runs: []});
  if (route.endsWith('/runs')) return response({runs: []});
  throw new Error(`Unexpected route ${route}`);
}

test('initial task data is text-safe, missing outcomes stay empty, unavailable benchmark makes no claims', async () => {
  const dom = page(async url => baseHandler(url));
  try {
    await settle(); const d = dom.window.document;
    assert.equal(d.getElementById('run-button').disabled, false);
    assert.equal(d.getElementById('task-source').querySelectorAll('img').length, 0);
    assert.match(d.getElementById('task-source').textContent, /<img src=x/);
    assert.equal(d.getElementById('metric-public').textContent, '—');
    assert.equal(d.getElementById('metric-cost').textContent, '—');
    assert.equal(d.getElementById('source-link').hasAttribute('href'), false);
    assert.match(d.getElementById('benchmark-body').textContent, /No benchmark measurements/);
    assert.deepEqual([...d.getElementById('task-tags').children].map(tag => tag.textContent), ['Text', 'Easy', 'Python regression']);
  } finally { dom.window.close(); }
});

test('run submission establishes a session, retries one expired CSRF token, and shows actual held-out failure', async () => {
  const calls = []; let attempts = 0; let sessions = 0;
  const dom = page(async (url, options) => {
    const route = new URL(url).pathname; calls.push({route, options});
    if (route.endsWith('/session')) { sessions++; return response({csrf_token: `token-${sessions}`}); }
    if (route.endsWith('/runs') && options.method === 'POST') { attempts++; assert.equal(options.headers['X-CSRF-Token'], `token-${attempts}`); assert.deepEqual(JSON.parse(options.body), {task_id: task.id, policy: 'fixed'}); return attempts === 1 ? response({detail: {message: 'CSRF expired'}}, 403) : response({id: 'run-1', status: 'queued', mode: 'live'}, 202); }
    if (route.endsWith('/runs/run-1')) return response(completed);
    return baseHandler(url);
  });
  try {
    await settle(); const d = dom.window.document;
    d.getElementById('run-form').dispatchEvent(new dom.window.Event('submit', {bubbles: true, cancelable: true}));
    await settle();
    assert.equal(sessions, 2); assert.equal(attempts, 2);
    assert.equal(d.getElementById('run-status').textContent, 'Not solved');
    assert.equal(d.getElementById('metric-public').textContent, '2 / 2');
    assert.equal(d.getElementById('metric-heldout').textContent, '1 / 2');
    assert.equal(d.getElementById('patch-code').querySelectorAll('script').length, 0);
    assert.match(d.getElementById('patch-code').textContent, /<script>alert/);
    assert.equal(d.getElementById('event-list').querySelectorAll('script').length, 0);
    assert.doesNotMatch(d.getElementById('event-list').textContent, /do-not-show/);
    assert.equal(d.getElementById('tests-content').querySelectorAll('img').length, 0);
    assert.equal(d.getElementById('download-patch').href, 'https://stelioszach.com/demos/forgerl/api/runs/run-1/patch');
    assert.equal(d.getElementById('tab-trace').getAttribute('aria-selected'), 'true');
  } finally { dom.window.close(); }
});

test('a disconnected backend cannot offer an executable run or invented results', async () => {
  const dom = page(async () => { throw new Error('Network unavailable'); });
  try { await settle(); const d = dom.window.document; assert.equal(d.getElementById('run-button').disabled, true); assert.equal(d.getElementById('global-alert').hidden, false); assert.match(d.getElementById('service-status').textContent, /unavailable/); assert.equal(d.getElementById('metric-cost').textContent, '—'); assert.equal(d.getElementById('benchmark-status').textContent, 'Unavailable'); }
  finally { dom.window.close(); }
});

test('keyboard tabs preserve one focus stop and expose only the selected inspector', async () => {
  const dom = page(async url => baseHandler(url));
  try {
    await settle(); const d = dom.window.document;
    d.getElementById('tab-patch').dispatchEvent(new dom.window.KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
    assert.equal(d.getElementById('tab-tests').getAttribute('aria-selected'), 'true');
    assert.equal(d.getElementById('panel-patch').hidden, true);
    assert.equal(d.getElementById('panel-tests').hidden, false);
    assert.equal([...d.querySelectorAll('[role=tab]')].filter(tab => tab.tabIndex === 0).length, 1);
  } finally { dom.window.close(); }
});

test('section navigation resets scroll immediately rather than inheriting smooth scrolling behind the sticky header', async () => {
  const dom = page(async url => baseHandler(url));
  try {
    await settle(); const d = dom.window.document;
    const scrolls = [];
    dom.window.scrollTo = options => scrolls.push({...options});
    d.querySelector('.top-nav [data-view="experiments"]').click();
    assert.equal(d.getElementById('experiments').hidden, false);
    assert.equal(d.getElementById('workbench').hidden, true);
    assert.deepEqual(scrolls.at(-1), {top: 0, left: 0, behavior: 'instant'});
    assert.equal(d.activeElement, d.getElementById('main'));
    dom.window.location.hash = '#methodology';
    await new Promise(resolve => dom.window.setTimeout(resolve, 10));
    assert.equal(d.getElementById('methodology').hidden, false);
    assert.deepEqual(scrolls.at(-1), {top: 0, left: 0, behavior: 'instant'});
  } finally { dom.window.close(); }
});
