const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../static/app.js');

test('absent measurements remain absent rather than appearing as zero', () => {
  for (const absent of [null, undefined, NaN, Infinity, '5']) {
    assert.equal(ui.count(absent), '—');
    assert.equal(ui.cost(absent), '—');
    assert.equal(ui.duration(absent), '—');
    assert.equal(ui.percentage(absent), '—');
  }
  assert.equal(ui.count(0), '0');
  assert.equal(ui.cost(0), '$0.0000');
  assert.equal(ui.ratio(0, 0), '—');
  assert.equal(ui.ratio(null, 3), '—');
  assert.equal(ui.ratio(0, 3), '0 / 3');
});

test('known outcomes distinguish terminal failure from live execution', () => {
  assert.deepEqual(ui.stateOf({status: 'running', solved: false}), {text: 'Running', className: 'active'});
  assert.deepEqual(ui.stateOf({status: 'complete', solved: false}), {text: 'Not solved', className: 'failure'});
  assert.deepEqual(ui.stateOf({status: 'completed', solved: true}), {text: 'Solved', className: 'success'});
  assert.equal(ui.isTerminal('error'), true);
  assert.equal(ui.isTerminal('queued'), false);
});

test('API-supplied links cannot execute a script or inject a data document', () => {
  assert.equal(ui.safeLink('javascript:alert(1)'), null);
  assert.equal(ui.safeLink('data:text/html,<script>alert(1)</script>'), null);
  assert.equal(ui.safeLink(''), null);
  assert.equal(ui.safeLink('https://github.com/stelioszach03'), 'https://github.com/stelioszach03');
});

test('invalid run identifiers cannot turn into API traversal paths', () => {
  assert.equal(ui.isRunId('../../session'), false);
  assert.equal(ui.isRunId('abc/patch'), false);
  assert.equal(ui.isRunId(''), false);
  assert.equal(ui.isRunId('4af88c0c-459b-4b03-b641-07daefcb8aac'), true);
});

test('human-readable API errors are retained without exposing arbitrary payloads', () => {
  assert.equal(ui.errorMessage({detail: {code: 'limit', message: 'Budget exhausted.'}}), 'Budget exhausted.');
  assert.equal(ui.errorMessage({detail: {secret: 'do-not-render'}}), 'The request could not be completed. Please try again.');
});

test('Unix-second timestamps from recorded experiments preserve their date', () => {
  const seconds = Date.parse('2026-09-23T00:00:00Z') / 1000;
  assert.equal(new Date(ui.timestamp(seconds)).toISOString(), '2026-09-23T00:00:00.000Z');
  assert.equal(ui.timestamp('2026-09-23T00:00:00Z'), '2026-09-23T00:00:00Z');
});
