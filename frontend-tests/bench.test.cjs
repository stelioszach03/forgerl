const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const helpers = require("../static/bench.js");
const html = fs.readFileSync(
  path.join(__dirname, "../static/bench.html"),
  "utf8",
);
const script = fs.readFileSync(
  path.join(__dirname, "../static/bench.js"),
  "utf8",
);
const task = {
  id: "ledger-01",
  title: "Reconcile ledger",
  family: "ledger",
  category: "multi_file",
  split: "test",
  description: "Handle partial settlements.",
  success_criterion: "Preserve settled entries and reject invalid amounts.",
  files: {
    "service.py": "from rules import valid\n",
    "rules.py":
      'def valid(value):\n    return "<img src=x onerror=alert(1)>"\n',
  },
  allowed_edit_files: ["service.py", "rules.py"],
  entrypoint: "service:run",
  public_cases: [{ name: "Partial settlement" }],
};
const another = {
  ...task,
  id: "dates-01",
  title: "Calendar boundaries",
  family: "dates",
  category: "bug_fix",
  split: "train",
};
const run = {
  id: "recorded-01",
  task_id: task.id,
  task_title: task.title,
  policy: "adaptive",
  seed: 17,
  status: "completed",
  solved: true,
  public_passed: 2,
  public_total: 2,
  heldout_passed: 5,
  heldout_total: 5,
  cost_usd: 0.008,
  tokens: 450,
  elapsed_s: 3.1,
  steps: 2,
  tool_calls: 4,
  regressions_introduced: 0,
  unnecessary_edits: null,
  success_after_repair: true,
  escalations: 1,
  learned_decisions: 1,
  fallback_decisions: 1,
  model_ids: ["actual-model"],
  created_at: "2026-09-23T01:00:00Z",
  diff: "--- a/rules.py\n+++ b/rules.py\n@@ -1 +1 @@\n-<script>alert(1)</script>\n+safe",
  final_files: { "service.py": "def run():\n    return True" },
  events: [
    {
      seq: 1,
      kind: "prompt",
      title: "<script>unsafe</script>",
      data: {
        prompt_messages: [
          { role: "user", content: "<img src=x onerror=alert(1)>" },
        ],
      },
    },
    {
      seq: 2,
      kind: "tests",
      title: "Visible checks completed",
      data: {
        passed: 2,
        total: 2,
        cases: [{ name: "<svg onload=alert(1)>", passed: true }],
      },
    },
    {
      seq: 3,
      kind: "model_switch",
      title: "Changed hosted model",
      data: { from: "cheap-model", to: "strong-model" },
    },
  ],
};
const notRun = {
  version: "0.2",
  status: "not_run",
  generated_at: null,
  models: [],
  summary: [],
  coverage: { planned: 0, completed: 0, missing: 0 },
  runs: [],
  provenance: { task_manifest_hash: "abc" },
};
const measured = {
  version: "0.2",
  status: "partial",
  generated_at: "2026-09-23T01:00:00Z",
  models: ["actual-model"],
  summary: [
    {
      policy: "adaptive",
      n: 1,
      solve_rate: 1,
      hidden_test_pass_rate: 1,
      mean_cost_usd: 0.008,
      mean_tokens: null,
      mean_latency_s: 3.1,
      mean_tool_calls: 4,
      mean_steps: 2,
      mean_regressions: 0,
      success_after_repair_rate: 1,
      escalation_frequency: 1,
    },
  ],
  coverage: {
    planned: 10,
    completed: 1,
    missing: [{ task_id: another.id }],
    evaluated_unique_tasks: 1,
    summary_split: "test",
  },
  runs: [run],
  provenance: {
    provider: {
      cost_basis: "Reported provider charge; failed calls retain reservations.",
    },
  },
};
const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});
const settle = async () => {
  for (let i = 0; i < 20; i++)
    await new Promise((resolve) => setImmediate(resolve));
};

test("a recorded 429 distinguishes rate limiting and unconfirmed budget reserve; next seed is replay only", async () => {
  const failed = {
    ...run,
    status: "failed",
    solved: false,
    seed: 17,
    error: "Model provider returned HTTP 429",
    heldout_passed: null,
    tokens: null,
    tokens_complete: false,
    cost_usd: 0.001332,
    events: [
      {
        kind: "error",
        data: {
          error: "Model provider returned HTTP 429",
          cost_usd: 0.001332,
          provider_reported_cost_usd: null,
          request_config: { provider: { only: ["coreweave/fp4"] } },
        },
      },
    ],
  };
  const next = { ...failed, id: "recorded-seed29", seed: 29 };
  const later = { ...run, id: "recorded-seed43", seed: 43 };
  const { dom, d, calls } = page(
    { ...measured, runs: [failed, later, next] },
    (route) =>
      route.endsWith(`/runs/${failed.id}`)
        ? response(failed)
        : route.endsWith(`/runs/${next.id}`)
          ? response(next)
          : undefined,
  );
  try {
    await settle();
    assert.equal(
      d.getElementById("run-status").textContent,
      "Provider rate limit",
    );
    assert.match(d.getElementById("run-metrics").textContent, /Budget reserve/);
    assert.match(
      d.getElementById("run-context").textContent,
      /not a confirmed charge/i,
    );
    assert.match(d.getElementById("run-context").textContent, /historical/i);
    assert.match(d.getElementById("next-recorded-seed").textContent, /29/);
    d.getElementById("next-recorded-seed").click();
    await settle();
    assert.equal(d.getElementById("run-select").value, next.id);
    assert.equal(
      d.getElementById("run-status").textContent,
      "Provider rate limit",
    );
    assert.ok(calls.every((call) => call.options.method === "GET"));
  } finally {
    dom.window.close();
  }
});
function page(benchmark = notRun, custom, suffix = "") {
  const calls = [];
  const dom = new JSDOM(html, {
    url: `https://stelioszach.com/demos/forgerl/bench.html${suffix || "?version=v0.2"}`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.fetch = async (url, options) => {
    const route = new URL(url).pathname;
    calls.push({ route, options });
    if (custom) {
      const result = await custom(route, options);
      if (result !== undefined) return result;
    }
    if (route.endsWith("/forgebench")) return response(benchmark);
    if (route.endsWith("/tasks")) return response({ tasks: [task, another] });
    if (route.endsWith(`/tasks/${task.id}`)) return response(task);
    if (route.endsWith(`/tasks/${another.id}`)) return response(another);
    if (route.endsWith(`/runs/${run.id}`)) return response(run);
    throw new Error(`Unexpected route ${route}`);
  };
  dom.window.eval(script);
  return { dom, calls, d: dom.window.document };
}

test("ForgeBench missing measurements remain absent, zero stays measured, invalid identifiers stay rejected", () => {
  for (const value of [null, undefined, "0", NaN, Infinity, -1]) {
    assert.equal(helpers.money(value), "—");
    assert.equal(helpers.count(value), "—");
    assert.equal(helpers.percent(value), "—");
  }
  assert.equal(helpers.money(0), "$0.0000");
  assert.equal(helpers.percent(0), "0.0%");
  assert.equal(helpers.ratio(null, 5), "—");
  assert.equal(helpers.ratio(0, 5), "0 / 5");
  for (const value of ["../tasks", "foo/bar", "", "a?b"])
    assert.equal(helpers.validId(value), false);
  assert.equal(
    helpers.stateOf({ status: "failed", solved: true }).label,
    "Infrastructure failure",
  );
});

test("not-run catalog shows five explicitly unmeasured policies and never starts inference or creates a session", async () => {
  const { dom, d, calls } = page();
  try {
    await settle();
    assert.equal(
      d.getElementById("study-status").textContent,
      "Not yet evaluated",
    );
    assert.equal(d.getElementById("catalog-count").textContent, "2 tasks");
    assert.equal(
      d.getElementById("last-run").textContent,
      "Last benchmark run: —",
    );
    assert.equal(d.querySelectorAll("#policy-table tr").length, 5);
    assert.equal(d.querySelectorAll("#policy-table tr.unmeasured").length, 5);
    assert.match(
      d.getElementById("cost-chart").textContent,
      /No comparable measurements/,
    );
    assert.equal(d.getElementById("cost-chart").querySelector("svg"), null);
    assert.equal(d.getElementById("run-select").disabled, true);
    assert.equal(d.getElementById("run-json").hidden, true);
    assert.ok(
      calls.every(
        (call) =>
          call.options.method === "GET" && call.options.credentials === "omit",
      ),
    );
    assert.ok(calls.every((call) => !call.route.includes("session")));
  } finally {
    dom.window.close();
  }
});

test("measured coverage, held-out scope, model names and accounted charges come from the artifact", async () => {
  const { dom, d } = page(measured);
  try {
    await settle();
    assert.equal(
      d.getElementById("study-status").textContent,
      "Partial evaluation",
    );
    assert.match(
      d.getElementById("coverage-copy").textContent,
      /1 of 10 planned episodes/,
    );
    assert.match(
      d.getElementById("coverage-copy").textContent,
      /1 planned episodes are missing/,
    );
    assert.match(
      d.getElementById("coverage-copy").textContent,
      /1 unique tasks evaluated/,
    );
    assert.match(
      d.getElementById("comparison-title").textContent,
      /Held-out test split/,
    );
    assert.equal(
      d.getElementById("evaluated-models").textContent,
      "actual-model",
    );
    assert.equal(
      d.getElementById("cost-basis").textContent,
      measured.provenance.provider.cost_basis,
    );
    assert.equal(
      d.querySelectorAll("#cost-chart .chart-point-group").length,
      1,
    );
    assert.match(
      d.getElementById("plot-desc").textContent,
      /100.0% success, \$0.0080/,
    );
    const row = d.querySelector("#policy-table .adaptive");
    assert.equal(
      row.children[5].textContent,
      "—",
      "Unknown mean token count is not zero.",
    );
    assert.equal(d.querySelectorAll("#policy-table .unmeasured").length, 4);
  } finally {
    dom.window.close();
  }
});

test("task files, actual prompts, patches and final files render as inert text; tests use persisted test events", async () => {
  const { dom, d } = page(measured);
  try {
    await settle();
    d.getElementById("source-file").value = "rules.py";
    d.getElementById("source-file").dispatchEvent(
      new dom.window.Event("change"),
    );
    assert.match(d.getElementById("source-code").textContent, /<img src=x/);
    assert.equal(
      d.getElementById("source-code").querySelectorAll("img").length,
      0,
    );
    assert.equal(
      d.getElementById("trajectory").querySelectorAll("script, img").length,
      0,
    );
    assert.match(
      d.getElementById("trajectory").textContent,
      /cheap-model → strong-model/,
    );
    assert.match(d.getElementById("trajectory").textContent, /prompt_messages/);
    assert.equal(
      d.getElementById("run-patch").querySelectorAll("script").length,
      0,
    );
    assert.match(d.getElementById("run-patch").textContent, /<script>alert/);
    assert.equal(
      d.getElementById("run-tests").querySelectorAll("svg").length,
      0,
    );
    assert.match(
      d.getElementById("run-tests").textContent,
      /<svg onload=alert/,
    );
    assert.match(d.getElementById("final-source").textContent, /def run/);
    assert.match(
      d.getElementById("detail-metrics").textContent,
      /Reference-scope edit proxy—/,
    );
    assert.equal(
      d.getElementById("run-json").href,
      "https://stelioszach.com/demos/forgerl/api/forgebench/runs/recorded-01",
    );
  } finally {
    dom.window.close();
  }
});

test("category, split and search filters compose without conflating task selection with evaluation coverage", async () => {
  const { dom, d } = page(measured);
  try {
    await settle();
    d.getElementById("split-filter").value = "train";
    d.getElementById("split-filter").dispatchEvent(
      new dom.window.Event("change"),
    );
    assert.equal(d.querySelectorAll(".task-option").length, 1);
    assert.match(d.getElementById("task-list").textContent, /Calendar/);
    d.querySelector(".task-option").click();
    await settle();
    assert.equal(d.getElementById("task-title").textContent, another.title);
    assert.equal(d.getElementById("run-select").disabled, true);
    assert.match(
      d.getElementById("trajectory").textContent,
      /has not been evaluated/,
    );
    d.getElementById("task-search").value = "no matching task";
    d.getElementById("task-search").dispatchEvent(
      new dom.window.Event("input"),
    );
    assert.equal(d.querySelectorAll(".task-option").length, 0);
    assert.match(d.getElementById("filtered-count").textContent, /0 of 2/);
    assert.equal(d.getElementById("episode-count").textContent, "1");
  } finally {
    dom.window.close();
  }
});

test("all inspector tabs support arrow, home and end keys with one focus stop", async () => {
  const { dom, d } = page();
  try {
    await settle();
    d.getElementById("tab-trajectory").dispatchEvent(
      new dom.window.KeyboardEvent("keydown", {
        key: "ArrowRight",
        bubbles: true,
      }),
    );
    assert.equal(
      d.getElementById("tab-patch").getAttribute("aria-selected"),
      "true",
    );
    assert.equal(d.getElementById("panel-trajectory").hidden, true);
    d.getElementById("tab-patch").dispatchEvent(
      new dom.window.KeyboardEvent("keydown", { key: "End", bubbles: true }),
    );
    assert.equal(
      d.getElementById("tab-metrics").getAttribute("aria-selected"),
      "true",
    );
    assert.equal(
      [...d.querySelectorAll("[role=tab]")].filter((tab) => tab.tabIndex === 0)
        .length,
      1,
    );
    assert.equal(d.activeElement, d.getElementById("tab-metrics"));
  } finally {
    dom.window.close();
  }
});

test("unavailable benchmark does not erase an available catalog or invent success", async () => {
  const { dom, d } = page(notRun, (route) => {
    if (route.endsWith("/forgebench")) throw new Error("offline");
  });
  try {
    await settle();
    assert.equal(
      d.getElementById("study-status").textContent,
      "Evidence unavailable",
    );
    assert.equal(d.getElementById("load-error").hidden, false);
    assert.equal(d.getElementById("task-title").textContent, task.title);
    assert.equal(d.querySelector("#cost-chart svg"), null);
    assert.equal(d.querySelectorAll("#policy-table .unmeasured").length, 5);
  } finally {
    dom.window.close();
  }
});

test("provider failures remain ungraded failures, with retained cost and no invented zero hidden pass rate", async () => {
  const failed = {
    ...run,
    status: "failed",
    solved: false,
    heldout_passed: null,
    tokens: null,
    tokens_complete: false,
    error: "Hosted endpoint returned no response.",
    events: [
      {
        kind: "error",
        title: "Request failed",
        data: { error: "Hosted endpoint returned no response." },
      },
    ],
  };
  const { dom, d } = page({ ...measured, runs: [failed] }, (route) =>
    route.endsWith(`/runs/${run.id}`) ? response(failed) : undefined,
  );
  try {
    await settle();
    assert.equal(
      d.getElementById("run-status").textContent,
      "Infrastructure failure",
    );
    assert.match(
      d.getElementById("run-metrics").textContent,
      /Hidden tests—Accounted cost\$0.0080Tokens—/,
    );
    assert.match(
      d.getElementById("run-tests").textContent,
      /No completed hidden evaluation recorded/,
    );
    assert.equal(d.getElementById("run-error").hidden, false);
    assert.match(
      d.getElementById("run-provenance").textContent,
      /Token accounting incomplete/,
    );
  } finally {
    dom.window.close();
  }
});

test("a slow previous task request cannot replace the newly selected task or its run", async () => {
  let release;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const { dom, d } = page(measured, (route) =>
    route.endsWith(`/tasks/${task.id}`) ? pending : undefined,
  );
  try {
    await settle();
    [...d.querySelectorAll(".task-option")]
      .find((button) => button.dataset.taskId === another.id)
      .click();
    await settle();
    release(response(task));
    await settle();
    assert.equal(d.getElementById("task-title").textContent, another.title);
    assert.equal(d.getElementById("run-select").disabled, true);
    assert.equal(d.getElementById("run-json").hidden, true);
  } finally {
    dom.window.close();
  }
});

test("task and run deep links restore a stored experiment without a paid request", async () => {
  const { dom, d, calls } = page(
    measured,
    undefined,
    "?task=ledger-01&run=recorded-01",
  );
  try {
    await settle();
    assert.equal(d.getElementById("run-status").textContent, "Solved");
    assert.equal(d.getElementById("run-select").value, run.id);
    assert.ok(calls.every((call) => call.options.method === "GET"));
  } finally {
    dom.window.close();
  }
});

test("training trajectories are inspectable without entering held-out comparison metrics", async () => {
  const training = {
    ...run,
    id: "training-01",
    task_id: another.id,
    policy: "exploration",
    split: "train",
    phase: "train",
    study_seed: 17,
    seed: 8123,
  };
  const data = {
    ...measured,
    training_runs: [training],
    coverage: { ...measured.coverage, training_completed: 1 },
  };
  const { dom, d, calls } = page(data, async (route) =>
    route.endsWith("/runs/training-01") ? response(training) : undefined,
  );
  try {
    await settle();
    assert.equal(d.getElementById("episode-count").textContent, "2");
    assert.match(
      d.getElementById("coverage-copy").textContent,
      /training trajectories.*excluded/,
    );
    d.querySelector(`[data-task-id="${another.id}"]`).click();
    await settle();
    assert.equal(d.getElementById("run-select").disabled, false);
    assert.match(
      d.getElementById("run-select").textContent,
      /Training exploration.*study seed 17/,
    );
    assert.doesNotMatch(
      d.getElementById("policy-table").textContent,
      /exploration/i,
    );
    assert.ok(
      calls.every(
        (call) => !call.options?.method || call.options.method === "GET",
      ),
    );
  } finally {
    dom.window.close();
  }
});

test("tiny measured costs retain precision and artifact downloads appear only when published", async () => {
  assert.equal(helpers.money(0.000093), "$0.000093");
  const { dom, d } = page({
    ...measured,
    downloads: ["technical-report.pdf", "results.csv"],
    provenance: {
      ...measured.provenance,
      source_manifest: { files: { "module.py": "actual-hash" } },
    },
  });
  try {
    await settle();
    assert.equal(d.getElementById("artifact-downloads").hidden, false);
    assert.match(
      d.getElementById("report-download").href,
      /\/api\/forgebench\/download\/technical-report.pdf$/,
    );
    assert.equal(d.getElementById("trajectories-download").hidden, true);
    assert.doesNotMatch(
      d.getElementById("study-provenance").textContent,
      /module.py/,
    );
    assert.match(d.getElementById("full-provenance").textContent, /module.py/);
  } finally {
    dom.window.close();
  }
});
