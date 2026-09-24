/* Read-only artifact explorer. No inference, browser execution or HTML from artifacts. */
(() => {
  "use strict";
  const V2_POLICIES = [
    ["strong_only", "Strong model only", "Same call budget; stronger endpoint"],
    ["cheap_only", "Cheap model only", "Same call budget; cheaper endpoint"],
    [
      "escalate_on_failure",
      "Escalate on failure",
      "Cheap first; stronger after a failure",
    ],
    [
      "static_router",
      "Hand-written router",
      "Fixed, observable decision rules",
    ],
    ["adaptive", "ForgeRL adaptive", "Learned values; declared fallback"],
  ];
  const PILOT_POLICIES = [
    ...V2_POLICIES.slice(0, 4),
    ["adaptive", "Fitted-Q transfer", "Historical training only; shared VERIFY rule"],
    ["supervised_cost", "Supervised return", "Simpler observed-return baseline; shared VERIFY"],
  ];
  let POLICIES = V2_POLICIES;
  const resolveVersion = (query) => {
    const explicit = query.get("version");
    if (["v0.2", "v0.3-pilot1"].includes(explicit)) return explicit;
    return query.has("task") || query.has("run") ? "v0.2" : "v0.3-pilot1";
  };
  const CATEGORIES = {
    bug_fix: "Bug fixing",
    multi_file: "Multi-file change",
    feature: "Feature implementation",
    refactor: "Refactoring",
    failing_tests: "Failing tests",
    long_horizon: "Multi-requirement / long-horizon",
  };
  const SPLITS = {
    train: "Training",
    validation: "Validation",
    test: "Held-out test",
    external: "Source-derived",
  };
  const numeric = (value) =>
    typeof value === "number" && Number.isFinite(value);
  const count = (value) =>
    numeric(value) && value >= 0
      ? value.toLocaleString("en-US", { maximumFractionDigits: 0 })
      : "—";
  const mean = (value) =>
    numeric(value) && value >= 0
      ? value.toLocaleString("en-US", { maximumFractionDigits: 2 })
      : "—";
  const money = (value) =>
    numeric(value) && value >= 0
      ? `$${value.toFixed(value > 0 && value < 0.001 ? 6 : value < 1 ? 4 : 2)}`
      : "—";
  const percent = (value) =>
    numeric(value) && value >= 0 && value <= 1
      ? `${(value * 100).toFixed(1)}%`
      : "—";
  const duration = (value) =>
    numeric(value) && value >= 0
      ? value >= 60
        ? `${(value / 60).toFixed(1)} min`
        : `${value.toFixed(1)} s`
      : "—";
  const ratio = (passed, total) =>
    numeric(passed) &&
    numeric(total) &&
    total > 0 &&
    passed >= 0 &&
    passed <= total
      ? `${count(passed)} / ${count(total)}`
      : "—";
  const list = (value) => (Array.isArray(value) ? value : []);
  const record = (value) =>
    value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const readable = (value) => String(value || "").replaceAll("_", " ");
  const validId = (value) =>
    typeof value === "string" &&
    /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value);
  const serialize = (value) => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return "This artifact field could not be displayed.";
    }
  };
  const policyName = (id) =>
    (POLICIES.find((policy) => policy[0] === id) || [id, readable(id)])[1];
  function date(value, short = false) {
    if (!value) return "—";
    const parsed = new Date(numeric(value) ? value * 1000 : value);
    if (Number.isNaN(parsed.getTime())) return "—";
    return (
      new Intl.DateTimeFormat(
        "en-US",
        short
          ? {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
              timeZone: "UTC",
              hour12: false,
            }
          : {
              year: "numeric",
              month: "short",
              day: "numeric",
              timeZone: "UTC",
            },
      ).format(parsed) + (short ? " UTC" : "")
    );
  }
  function rateLimited(run) {
    return (
      ["failed", "error"].includes(run?.status) &&
      /\bHTTP 429\b/.test(run?.error || "")
    );
  }
  function retainedReserve(run) {
    return list(run.events)
      .filter((event) => event.kind === "error")
      .reduce((sum, event) => {
        const data = record(event.data);
        return (
          sum +
          (numeric(data.cost_usd) &&
          data.cost_usd > 0 &&
          (data.accounting_kind === "retained_reservation" ||
            (data.provider_reported_cost_usd === null &&
              record(data.request_config).provider &&
              /\bHTTP 429\b/.test(data.error || "")))
            ? data.cost_usd
            : 0)
        );
      }, 0);
  }
  function stateOf(run) {
    if (rateLimited(run))
      return { label: "Provider rate limit", className: "failed" };
    const statuses = {
      failed: "Infrastructure failure",
      error: "Infrastructure failure",
      interrupted: "Interrupted",
      budget_exhausted: "Budget stopped",
      cancelled: "Cancelled",
      canceled: "Cancelled",
      running: "Incomplete artifact",
      queued: "Incomplete artifact",
    };
    if (statuses[run.status])
      return { label: statuses[run.status], className: "failed" };
    if (run.solved === true) return { label: "Solved", className: "solved" };
    if (run.solved === false)
      return { label: "Not solved", className: "failed" };
    return { label: "Not graded", className: "" };
  }
  const helpers = {
    numeric,
    count,
    mean,
    money,
    percent,
    duration,
    ratio,
    validId,
    stateOf,
    date,
    resolveVersion,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;
  const $ = (id) => document.getElementById(id);
  const state = {
    benchmark: null,
    tasks: [],
    task: null,
    run: null,
    taskRequest: 0,
    runRequest: 0,
    loadRequest: 0,
    version: resolveVersion(new URL(window.location.href).searchParams),
    comparisonSplit: "test",
    replayCursor: null,
    replayTimer: null,
  };
  const base = new URL("./", window.location.href);
  const apiURL = (route) => new URL(`api/forgebench${state.version === "v0.3-pilot1" ? "/versions/v0.3-pilot1" : ""}${route}`, base).href;
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text != null) el.textContent = String(text);
    if (className) el.className = className;
    return el;
  };
  const setText = (id, text) => {
    $(id).textContent = text;
  };
  const announce = (text) => setText("announcer", text);
  async function request(route) {
    const response = await fetch(apiURL(route), {
      method: "GET",
      credentials: "omit",
      headers: { Accept: "application/json" },
    });
    if (!response.ok)
      throw new Error(
        `Recorded artifact unavailable (HTTP ${response.status}).`,
      );
    return response.json();
  }
  function status(id, label, className = "") {
    $(id).textContent = label;
    $(id).className = `status-label ${className}`;
  }
  function definition(target, entries, className) {
    const dl = typeof target === "string" ? $(target) : target;
    dl.replaceChildren();
    if (className) dl.className = className;
    for (const [label, value] of entries) {
      const entry = node("div");
      entry.append(node("dt", label), node("dd", value));
      dl.append(entry);
    }
  }
  function modelNames(models) {
    return [
      ...new Set(
        list(models)
          .map((model) =>
            typeof model === "string"
              ? model
              : model.model || model.id || model.name,
          )
          .filter((value) => typeof value === "string" && value),
      ),
    ];
  }
  function showBenchmark(benchmark) {
    state.benchmark = record(benchmark);
    $("result-artifact").href = apiURL("");
    const summary = comparisonRows(),
      coverage = record(benchmark.coverage),
      provenance = record(benchmark.provenance);
    const measured = summary.filter((row) => numeric(row.n) && row.n > 0);
    const labels = {
      not_run: "Not yet evaluated",
      partial: "Partial evaluation",
      completed: "Recorded evaluation",
      complete: "Recorded evaluation",
      failed: "Evaluation interrupted",
      unavailable: "Evidence unavailable",
    };
    status(
      "study-status",
      labels[benchmark.status] ||
        (measured.length ? "Recorded evaluation" : "Not yet evaluated"),
      benchmark.status === "partial"
        ? "partial"
        : measured.length
          ? "measured"
          : "",
    );
    setText("last-run", `Last benchmark run: ${date(benchmark.generated_at)}`);
    setText(
      "study-version",
      typeof benchmark.version === "string" ? benchmark.version : "—",
    );
    const actualModels = modelNames(
      benchmark.evaluated_models || benchmark.models,
    );
    setText(
      "model-count",
      actualModels.length ? count(actualModels.length) : "—",
    );
    setText(
      "evaluated-models",
      actualModels.length
        ? actualModels.join(" · ")
        : "No model evaluation recorded for this version.",
    );
    setText(
      "episode-count",
      numeric(coverage.completed)
        ? count(
            coverage.completed +
              (numeric(coverage.training_completed)
                ? coverage.training_completed
                : 0),
          )
        : list(benchmark.runs).length
          ? count(benchmark.runs.length)
          : "—",
    );
    setText(
      "episode-split",
      numeric(coverage.training_completed) && coverage.training_completed > 0
        ? `${count(coverage.completed)} evaluation · ${count(coverage.training_completed)} training`
        : "Recorded evaluation episodes",
    );
    const coverageParts = [];
    if (numeric(coverage.training_completed) && coverage.training_completed > 0)
      coverageParts.push(
        `${count(coverage.training_completed)} training trajectories are separately inspectable and excluded from the comparison.`,
      );
    if (numeric(coverage.completed) && numeric(coverage.planned))
      coverageParts.push(
        `${count(coverage.completed)} of ${count(coverage.planned)} planned episodes recorded.`,
      );
    else if (numeric(coverage.completed))
      coverageParts.push(
        `${count(coverage.completed)} episodes recorded; no planned denominator supplied.`,
      );
    if (numeric(coverage.missing) && coverage.missing > 0)
      coverageParts.push(
        `${count(coverage.missing)} planned episodes are missing.`,
      );
    else if (Array.isArray(coverage.missing) && coverage.missing.length)
      coverageParts.push(
        `${count(coverage.missing.length)} planned episodes are missing.`,
      );
    if (typeof coverage.description === "string")
      coverageParts.push(coverage.description);
    coverageParts.push(
      measured.length
        ? "Missing runs are not counted as successful. Repeated seeds are not independent tasks."
        : "The task catalog is available; no measured policy comparison is published yet.",
    );
    setText("coverage-copy", coverageParts.join(" "));
    const costBasis =
      provenance.cost_basis ||
      record(provenance.provider).cost_basis ||
      benchmark.cost_basis;
    if (typeof costBasis === "string") setText("cost-basis", costBasis);
    else if (costBasis && typeof costBasis === "object")
      setText(
        "cost-basis",
        Object.entries(costBasis)
          .map(
            ([key, value]) =>
              `${readable(key)}: ${typeof value === "string" ? value : serialize(value)}`,
          )
          .join(" · "),
      );
    if (state.version === "v0.3-pilot1") {
      setText("comparison-title", `Six policies. ${state.comparisonSplit === "test" ? "Primary test sample." : state.comparisonSplit === "validation" ? "Validation sample." : "Source-derived sample."}`);
      setText("comparison-note", "Each sample is shown separately. Primary success and cost are equally family-weighted; related task variants are not independent. VERIFY is a shared fixed rule, not a learned action. A single seed does not establish superiority.");
      setText("controller-explanation", "Six policies compare retry, repair, escalation, rollback and stopping. Both learned selectors use historical training only. Every policy shares the same verify-on-visible-green rule; VERIFY was not learned. Final hidden grading never guides a repair.");
    } else {
      setText("comparison-title", coverage.summary_split === "test" ? "Five policies. Held-out test split." : "Five policies. One protocol.");
      setText(
        "comparison-note",
        "Chart and table show held-out test episodes only. Overall coverage above includes validation. Hidden-test pass rate is per graded check; task success is per attempted episode. After-repair success is conditional on repeated attempts.",
      );
      setText("controller-explanation", "The policy can retry, repair, escalate, roll back or stop. Language-model weights remain unchanged. A learned controller uses training transitions; unseen states use a declared fallback.");
    }
    $("verify-column").hidden = state.version !== "v0.3-pilot1";
    $("comparison-split-control").hidden = state.version !== "v0.3-pilot1";
    const walkthroughs = record(benchmark.walkthroughs);
    $("walkthrough-entry").hidden = !walkthroughs.repair || !walkthroughs.verification_miss;
    if (numeric(coverage.evaluated_unique_tasks))
      coverageParts.push(
        `${count(coverage.evaluated_unique_tasks)} unique tasks evaluated.`,
      );
    setText("coverage-copy", coverageParts.join(" "));
    renderPolicies(summary);
    renderChart(summary);
    const limits = list(benchmark.limitations).filter(
      (value) => typeof value === "string" && value,
    );
    if (limits.length)
      $("study-limitations").replaceChildren(
        ...limits.map((item) => node("li", item)),
      );
    const provenanceEntries = [
      ["Protocol", provenance.protocol],
      ["Requested seeds", list(provenance.requested_seeds).join(", ") || null],
      ["Provider profile", record(provenance.provider).provider],
      [
        "Task manifest",
        provenance.task_manifest_sha256 || provenance.task_manifest_hash,
      ],
      [
        "Evaluated source",
        provenance.runtime_source_sha256 ||
          record(provenance.source_manifest).sha256,
      ],
      ["Controller", provenance.controller_selection],
    ].filter(([, value]) => typeof value === "string" && value);
    definition(
      "study-provenance",
      provenanceEntries.length
        ? provenanceEntries
        : [["Status", "No provenance artifact published for this version."]],
    );
    setText("full-provenance", serialize(provenance));
    let availableDownloads = 0;
    for (const [id, name] of [
      ["report-download", "technical-report.pdf"],
      ["results-download", "results.csv"],
      ["trajectories-download", "trajectories.jsonl"],
    ]) {
      const available = list(benchmark.downloads).includes(name);
      $(id).hidden = !available;
      if (available) {
        $(id).href = apiURL(`/download/${encodeURIComponent(name)}`);
        $(id).target = "_blank";
        $(id).rel = "noopener";
        availableDownloads++;
      } else $(id).removeAttribute("href");
    }
    $("artifact-downloads").hidden = availableDownloads === 0;
  }
  function comparisonRows() {
    return list(record(state.benchmark?.summary_by_split)[state.comparisonSplit] || state.benchmark?.summary);
  }
  function renderPolicies(summary) {
    const body = $("policy-table");
    body.replaceChildren();
    for (const [id, label, description] of POLICIES) {
      const row = summary.find((item) => item.policy === id),
        measured = !!row && numeric(row.n) && row.n > 0;
      const tr = node(
        "tr",
        null,
        `${measured ? "" : "unmeasured"} ${id === "adaptive" ? "adaptive" : ""}`.trim(),
      );
      const title = node("td");
      title.append(
        node("span", label),
        node("small", measured ? description : "Not evaluated"),
      );
      tr.append(title);
      const values = measured
        ? [
            count(row.n),
            percent(row.solve_rate),
            percent(row.hidden_test_pass_rate),
            money(row.mean_cost_usd),
            mean(row.mean_tokens),
            duration(row.mean_latency_s),
            mean(row.mean_tool_calls),
            mean(row.mean_steps),
            mean(row.mean_regressions),
            percent(row.success_after_repair_rate),
            percent(row.escalation_frequency),
          ]
        : Array(11).fill("—");
      for (const [index, value] of values.entries()) {
        const cell = node("td", value);
        if (measured && index === 2 && numeric(row.graded_runs))
          cell.append(
            node("small", `${count(row.graded_runs)} / ${count(row.n)} graded`),
          );
        if (measured && index === 4 && numeric(row.token_measured_episodes ?? row.token_measured_runs))
          cell.append(node("small", `${count(row.token_measured_episodes ?? row.token_measured_runs)} / ${count(row.n)} measured`));
        tr.append(cell);
      }
      if (state.version === "v0.3-pilot1") tr.append(node("td", measured ? mean(row.mean_verification_calls) : "—"));
      body.append(tr);
    }
  }
  function svgNode(tag, attrs = {}, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs))
      el.setAttribute(key, String(value));
    if (text != null) el.textContent = text;
    return el;
  }
  function renderChart(summary) {
    const eligible = POLICIES.map(([id, label], index) => ({
      ...summary.find((row) => row.policy === id),
      id,
      label,
      index: index + 1,
    })).filter(
      (row) =>
        numeric(row.n) &&
        row.n > 0 &&
        numeric(row.mean_cost_usd) &&
        row.mean_cost_usd >= 0 &&
        numeric(row.solve_rate) &&
        row.solve_rate >= 0 &&
        row.solve_rate <= 1,
    );
    const container = $("cost-chart");
    container.replaceChildren();
    $("chart-legend").replaceChildren();
    if (!eligible.length) {
      container.append(
        node(
          "p",
          "No comparable measurements yet. This chart will show recorded success and cost when experiments are published.",
          "empty-copy",
        ),
      );
      return;
    }
    const width = Math.max(
      280,
      Math.min(640, container.clientWidth || window.innerWidth - 80),
    );
    const svg = svgNode("svg", {
      viewBox: `0 0 ${width} 280`,
      role: "img",
      "aria-labelledby": "plot-title plot-desc",
    });
    svg.append(
      svgNode(
        "title",
        { id: "plot-title" },
        "Recorded task success versus accounted cost per task",
      ),
      svgNode(
        "desc",
        { id: "plot-desc" },
        eligible
          .map(
            (row) =>
              `${row.label}: ${percent(row.solve_rate)} success, ${money(row.mean_cost_usd)} accounted cost per task, ${row.n} episodes.`,
          )
          .join(" "),
      ),
    );
    const left = width < 420 ? 48 : 63,
      right = width - 23,
      top = 25,
      bottom = 231;
    const maxCost =
      Math.max(...eligible.map((row) => row.mean_cost_usd), 0.000001) * 1.18;
    for (let i = 0; i <= 4; i++) {
      const y = bottom - ((bottom - top) * i) / 4;
      svg.append(
        svgNode("line", {
          x1: left,
          x2: right,
          y1: y,
          y2: y,
          class: "chart-grid",
        }),
        svgNode(
          "text",
          { x: left - 11, y: y + 4, "text-anchor": "end", class: "chart-tick" },
          `${i * 25}%`,
        ),
      );
    }
    for (let i = 0; i <= 4; i++) {
      const x = left + ((right - left) * i) / 4;
      svg.append(
        svgNode(
          "text",
          { x, y: bottom + 21, "text-anchor": "middle", class: "chart-tick" },
          money((maxCost * i) / 4),
        ),
      );
    }
    svg.append(
      svgNode("line", {
        x1: left,
        x2: right,
        y1: bottom,
        y2: bottom,
        class: "chart-axis",
      }),
      svgNode("text", { x: left, y: 13, class: "chart-label" }, "Task success"),
      svgNode(
        "text",
        {
          x: (left + right) / 2,
          y: 276,
          "text-anchor": "middle",
          class: "chart-label",
        },
        width < 420 ? "Cost / task · USD" : "Mean accounted cost / task · USD",
      ),
    );
    for (const row of eligible) {
      const x = left + ((right - left) * row.mean_cost_usd) / maxCost,
        y = bottom - (bottom - top) * row.solve_rate;
      const point = svgNode("g", {
        class: "chart-point-group",
        tabindex: "0",
        role: "img",
        "aria-label": `${row.label}: ${percent(row.solve_rate)} success, ${money(row.mean_cost_usd)} per task`,
      });
      point.append(
        svgNode(
          "title",
          {},
          `${row.label} · ${percent(row.solve_rate)} · ${money(row.mean_cost_usd)}`,
        ),
        svgNode("circle", { cx: x, cy: y, r: 16, class: "point-ring" }),
        svgNode("circle", { cx: x, cy: y, r: 11, class: "chart-point" }),
        svgNode("text", { x, y, class: "chart-point-label" }, row.index),
      );
      svg.append(point);
      const item = node("li");
      item.append(
        node("span", row.index, "legend-number"),
        node("span", row.label),
      );
      $("chart-legend").append(item);
    }
    container.append(svg);
    setText(
      "chart-caption",
      "Each point is a recorded policy mean. Coincident points can overlap; the table retains every value. Costs include reported charges or conservative reservations, not credit-purchase fees.",
    );
  }
  function populateCatalog(tasks) {
    state.tasks = list(tasks).filter((task) => task && validId(task.id));
    setText("catalog-count", `${count(state.tasks.length)} tasks`);
    const families = new Set(
        state.tasks.map((task) => task.family).filter(Boolean),
      ),
      files = state.tasks.reduce(
        (total, task) => total + Object.keys(record(task.files)).length,
        0,
      );
    setText(
      "catalog-summary",
      `${count(state.tasks.length)} ${state.version === "v0.3-pilot1" ? "recorded tasks" : "authored tasks"} · ${count(families.size)} families${files ? ` · ${count(files)} source files` : ""}`,
    );
    const categories = [
      ...new Set(state.tasks.map((task) => task.category).filter(Boolean)),
    ];
    const filter = $("category-filter");
    filter.replaceChildren(new Option("All categories", ""));
    categories
      .sort(
        (a, b) =>
          Object.keys(CATEGORIES).indexOf(a) -
          Object.keys(CATEGORIES).indexOf(b),
      )
      .forEach((category) =>
        filter.append(
          new Option(CATEGORIES[category] || readable(category), category),
        ),
      );
    renderTaskList();
    const query = new URL(window.location.href).searchParams,
      requested = query.get("task");
    const initial =
      state.tasks.find((task) => task.id === requested) ||
      state.tasks.find(
        (task) => task.split === "test" && task.category === "long_horizon",
      ) ||
      state.tasks.find((task) => task.split === "test") ||
      state.tasks[0];
    if (initial) selectTask(initial.id, query.get("run"));
    else setText("task-title", "No task catalog is available");
  }
  function filteredTasks() {
    const search = $("task-search").value.trim().toLowerCase(),
      category = $("category-filter").value,
      split = $("split-filter").value;
    return state.tasks.filter(
      (task) =>
        (!category || task.category === category) &&
        (!split || task.split === split) &&
        (!search ||
          [
            task.id,
            task.title,
            task.family,
            task.summary,
            task.description,
            ...list(task.tags),
          ]
            .join(" ")
            .toLowerCase()
            .includes(search)),
    );
  }
  function renderTaskList() {
    const tasks = filteredTasks();
    setText(
      "filtered-count",
      `${count(tasks.length)} of ${count(state.tasks.length)} tasks`,
    );
    const container = $("task-list");
    container.replaceChildren();
    if (!tasks.length) {
      container.append(
        node("p", "No tasks match these filters.", "empty-copy"),
      );
      return;
    }
    for (const task of tasks) {
      const button = node("button", null, "task-option");
      button.type = "button";
      button.dataset.taskId = task.id;
      button.setAttribute("aria-current", String(state.task?.id === task.id));
      button.append(
        node("strong", task.title || task.id),
        node(
          "small",
          `${CATEGORIES[task.category] || readable(task.category)} · ${SPLITS[task.split] || readable(task.split)}`,
        ),
      );
      button.addEventListener("click", () => selectTask(task.id));
      container.append(button);
    }
  }
  async function selectTask(id, requestedRun = null) {
    if (!validId(id)) return;
    const requestNumber = ++state.taskRequest;
    ++state.runRequest;
    state.run = null;
    state.task = state.tasks.find((task) => task.id === id) || { id };
    for (const button of document.querySelectorAll(".task-option"))
      button.setAttribute("aria-current", String(button.dataset.taskId === id));
    document.querySelector(".task-detail").setAttribute("aria-busy", "true");
    showTask(state.task);
    clearRun("Loading this task’s recorded experiments…");
    try {
      const task = await request(`/tasks/${encodeURIComponent(id)}`);
      if (requestNumber !== state.taskRequest) return;
      state.task = task;
      showTask(task);
      populateRuns(task.id, requestedRun);
      announce(`Task selected: ${task.title}.`);
      const url = new URL(window.location.href);
      url.searchParams.set("task", id);
      url.searchParams.delete("run");
      history.replaceState({}, "", url);
    } catch (error) {
      if (requestNumber !== state.taskRequest) return;
      setText(
        "task-description",
        "The task details could not be loaded. Select the task again to retry.",
      );
      setText("source-code", error.message);
      clearRun("Task details unavailable.");
    } finally {
      if (requestNumber === state.taskRequest)
        document
          .querySelector(".task-detail")
          .setAttribute("aria-busy", "false");
    }
  }
  function showTask(task) {
    setText("task-title", task.title || task.id || "Loading task");
    setText(
      "task-context",
      [task.family, CATEGORIES[task.category] || readable(task.category)]
        .filter(Boolean)
        .join(" / ") || "Task brief",
    );
    status("task-split", SPLITS[task.split] || readable(task.split) || "—");
    setText(
      "task-description",
      task.description || task.summary || "Loading task description…",
    );
    setText(
      "task-criterion",
      task.success_criterion ||
        "No success criterion is available in this artifact.",
    );
    const files = record(task.files),
      names = Object.keys(files),
      selector = $("source-file");
    selector.replaceChildren();
    names.forEach((name) => selector.append(new Option(name, name)));
    selector.disabled = !names.length;
    if (!names.length) selector.append(new Option("No source files", ""));
    setText(
      "source-code",
      names.length ? files[names[0]] : "No source files supplied.",
    );
    const editable = list(task.allowed_edit_files).join(", ");
    setText(
      "source-note",
      `Entrypoint: ${task.entrypoint || "—"}.${editable ? ` Allowed edits: ${editable}.` : ""} Files are supplied as context; no autonomous file discovery is claimed.`,
    );
    const cases = list(task.public_cases || task.public_tests);
    setText(
      "visible-count",
      cases.length
        ? count(cases.length)
        : count(task.public_tests_count ?? task.public_cases_count),
    );
    $("visible-tests").replaceChildren(
      ...(cases.length
        ? cases.map((test) => node("li", test.name || "Visible check"))
        : [
            node(
              "li",
              "No visible test descriptions are present in this artifact.",
            ),
          ]),
    );
  }
  function runsForTask(id) {
    return [
      ...list(state.benchmark?.runs),
      ...list(state.benchmark?.training_runs),
    ].filter((run) => run.task_id === id && validId(run.id));
  }
  function populateRuns(taskId, requestedRun) {
    const runs = runsForTask(taskId),
      select = $("run-select");
    select.replaceChildren();
    if (!runs.length) {
      select.append(new Option("No recorded runs for this task", ""));
      select.disabled = true;
      clearRun("This task has not been evaluated in the published study.");
      return;
    }
    select.disabled = false;
    runs.forEach((run) =>
      select.append(
        new Option(
          `${run.phase === "train" ? "Training exploration" : policyName(run.policy)} · ${stateOf(run).label}${numeric(run.study_seed ?? run.seed) ? ` · study seed ${run.study_seed ?? run.seed}` : ""} · ${run.id.slice(0, 8)}`,
          run.id,
        ),
      ),
    );
    const selected =
      runs.find((run) => run.id === requestedRun) ||
      runs.find((run) => run.policy === "adaptive") ||
      runs[0];
    select.value = selected.id;
    selectRun(selected.id);
  }
  function clearRun(message) {
    stopReplay();
    state.replayCursor = null;
    $("replay-controls").hidden = true;
    state.run = null;
    $("run-context").hidden = true;
    $("next-recorded-seed").hidden = true;
    status("run-status", "Not evaluated");
    setText("run-caption", message);
    setText("run-title", "Inspect a recorded trajectory");
    definition("run-metrics", [
      ["Hidden tests", "—"],
      ["Accounted cost", "—"],
      ["Tokens", "—"],
      ["Latency", "—"],
    ]);
    setText("event-count", "0");
    $("trajectory").replaceChildren(node("li", message, "empty-copy"));
    setText("run-patch", "No recorded patch selected.");
    $("run-tests").replaceChildren(
      node("p", "No test evaluation selected.", "empty-copy"),
    );
    $("detail-metrics").replaceChildren();
    setText("failure-labels", "No recorded run selected.");
    $("final-file").replaceChildren(new Option("No candidate files", ""));
    $("final-file").disabled = true;
    setText("final-source", "No recorded candidate selected.");
    $("run-error").hidden = true;
    $("run-json").hidden = true;
    $("run-patch-download").hidden = true;
    setText(
      "run-provenance",
      "Every displayed event comes from the selected stored artifact.",
    );
  }
  async function selectRun(id) {
    if (!validId(id)) return;
    const number = ++state.runRequest,
      taskId = state.task?.id;
    clearRun("Loading the stored run…");
    status("run-status", "Loading artifact");
    try {
      const run = await request(`/runs/${encodeURIComponent(id)}`);
      if (number !== state.runRequest || taskId !== state.task?.id) return;
      if (run.task_id && run.task_id !== taskId)
        throw new Error("The stored run does not match this task.");
      state.run = run;
      showRun(run, id);
      announce(
        `Recorded run selected: ${policyName(run.policy)}. ${stateOf(run).label}.`,
      );
      const url = new URL(window.location.href);
      url.searchParams.set("task", taskId);
      url.searchParams.set("run", id);
      history.replaceState({}, "", url);
    } catch (error) {
      if (number !== state.runRequest) return;
      clearRun("The recorded run could not be loaded. Select a run to retry.");
      status("run-status", "Artifact unavailable", "unavailable");
      setText("run-error", error.message);
      $("run-error").hidden = false;
    }
  }
  function metricValue(run, field) {
    return run[field] ?? record(run.metrics)[field];
  }
  function showRun(run, id) {
    const metric = (key) => metricValue(run, key),
      result = stateOf(run),
      events = list(run.events || run.trajectory);
    const reserve = retainedReserve(run);
    const reserveOnly =
      reserve > 0 &&
      numeric(run.cost_usd) &&
      Math.abs(reserve - run.cost_usd) < 0.000001;
    const costLabel = reserveOnly ? "Budget reserve" : "Accounted cost";
    const context = [];
    if (rateLimited(run))
      context.push(
        "This historical request was rate-limited by the model provider (HTTP 429). The record is retained for audit; opening it does not make a new request to the model.",
      );
    if (rateLimited(run) && run.heldout_passed == null)
      context.push(
        "No final hidden-test evaluation was completed. A dash means unmeasured, not zero tests passed.",
      );
    if (reserve > 0)
      context.push(
        `${money(reserve)} was retained conservatively in the experiment budget because the failed request returned no verified billing amount. This reserve is not a confirmed charge.`,
      );
    if (run.verification_grader_disagreement_direction === "missed_failure")
      context.push("Supplemental public checks passed, but the final hidden grader found a failure. This recorded task remains not solved.");
    else if (run.verification_grader_disagreement_direction === "false_rejection")
      context.push("Supplemental checks and final grading disagree. Task success follows the original visible checks and final hidden grader; both signals are retained.");
    setText("run-context", context.join(" "));
    $("run-context").hidden = context.length === 0;
    const nextSeed =
      rateLimited(run) && numeric(run.seed)
        ? runsForTask(run.task_id)
            .filter(
              (item) =>
                item.policy === run.policy &&
                numeric(item.seed) &&
                item.seed > run.seed,
            )
            .sort((a, b) => a.seed - b.seed)[0]
        : null;
    $("next-recorded-seed").hidden = !nextSeed;
    if (nextSeed) {
      setText("next-recorded-seed", `View recorded seed ${nextSeed.seed}`);
      $("next-recorded-seed").onclick = () => {
        $("run-select").value = nextSeed.id;
        selectRun(nextSeed.id);
      };
    } else $("next-recorded-seed").onclick = null;
    status("run-status", result.label, result.className);
    setText(
      "run-title",
      `${policyName(run.policy)} / ${state.task?.title || run.task_title || run.task_id}`,
    );
    setText(
      "run-caption",
      `${run.split === "train" ? "Training rollout; excluded from leaderboard. " : ""}Stored artifact ${id}${numeric(run.seed) ? ` · Seed ${run.seed}` : ""} · ${date(run.created_at || run.started_at)}${run.stop_reason ? ` · ${readable(run.stop_reason)}` : ""}`,
    );
    definition("run-metrics", [
      [
        "Hidden tests",
        ratio(metric("heldout_passed"), metric("heldout_total")),
      ],
      [costLabel, money(metric("cost_usd"))],
      ["Tokens", count(metric("tokens"))],
      ["Latency", duration(metric("elapsed_s"))],
    ]);
    setText("event-count", count(events.length));
    renderEvents(events);
    $("replay-controls").hidden = !events.length;
    $("replay-step").max = String(Math.max(1, events.length));
    $("replay-step").value = "1";
    $("replay-next").disabled = false;
    setText("replay-position", `all ${count(events.length)} events`);
    setText("replay-status", "Playback only. No new model request.");
    renderDiff(
      typeof run.diff === "string"
        ? run.diff
        : typeof run.patch === "string"
          ? run.patch
          : "No patch was recorded.",
    );
    renderTests(run);
    const yesNo = (value) =>
      value === true ? "Yes" : value === false ? "No" : "—";
    definition("detail-metrics", [
      [
        "Task success",
        run.solved === true &&
        !["failed", "error", "interrupted", "budget_exhausted"].includes(
          run.status,
        )
          ? "Solved"
          : result.label,
      ],
      ["Visible tests", ratio(metric("public_passed"), metric("public_total"))],
      [
        "Hidden tests",
        ratio(metric("heldout_passed"), metric("heldout_total")),
      ],
      [costLabel, money(metric("cost_usd"))],
      ["Tokens", count(metric("tokens"))],
      ["Latency", duration(metric("elapsed_s"))],
      ["Tool calls", count(metric("tool_calls"))],
      ["Attempts", count(metric("steps") ?? metric("attempts"))],
      ["Visible regressions", count(metric("regressions_introduced"))],
      ["Reference-scope edit proxy", count(metric("unnecessary_edits"))],
      ["Success after repair", yesNo(metric("success_after_repair"))],
      ["Escalations", count(metric("escalations"))],
      ["Rollbacks", count(metric("rollbacks"))],
      ["All-action learned labels", count(metric("learned_decisions"))],
      ["All-action fallback labels", count(metric("fallback_decisions"))],
      ...(state.version === "v0.3-pilot1" ? [
        ["Supplemental VERIFY calls", count(metric("verification_calls"))],
        ["Final candidate supplemental checks", ratio(metric("verification_passed"), metric("verification_total"))],
        ["Supplemental / final disagreement", metric("verification_grader_disagreement") == null ? "Not measured" : metric("verification_grader_disagreement") ? readable(metric("verification_grader_disagreement_direction")) : "No"],
        ["VERIFY policy", "Shared fixed rule; not learned"],
      ] : []),
    ]);
    const failures = list(metric("failure_labels"));
    setText(
      "failure-labels",
      failures.length
        ? failures
            .map((item) =>
              typeof item === "string" ? readable(item) : serialize(item),
            )
            .join(" · ")
        : "No failure labels were recorded. Absence of a label is not evidence that a failure mode was tested.",
    );
    if (typeof run.error === "string" && run.error) {
      setText("run-error", run.error);
      $("run-error").hidden = false;
    }
    const finalNames = Object.keys(record(run.final_files));
    $("final-file").replaceChildren(
      ...finalNames.map((name) => new Option(name, name)),
    );
    $("final-file").disabled = !finalNames.length;
    if (!finalNames.length)
      $("final-file").append(new Option("No candidate files", ""));
    setText(
      "final-source",
      finalNames.length
        ? run.final_files[finalNames[0]]
        : "No final repository files recorded.",
    );
    const models = modelNames(run.models || run.model_ids);
    setText(
      "run-provenance",
      `Run ${id}${models.length ? ` · ${models.join(" → ")}` : ""}${run.token_accounting_complete === false || run.tokens_complete === false ? " · Token accounting incomplete." : ""}`,
    );
    $("run-json").href = apiURL(`/runs/${encodeURIComponent(id)}`);
    $("run-json").hidden = false;
    $("run-patch-download").href = apiURL(
      `/runs/${encodeURIComponent(id)}/patch`,
    );
    $("run-patch-download").hidden = false;
  }
  function renderEvents(events) {
    const container = $("trajectory");
    container.replaceChildren();
    if (!events.length) {
      container.append(
        node(
          "li",
          "This artifact contains no recorded trajectory events.",
          "empty-copy",
        ),
      );
      return;
    }
    events.forEach((event, index) => {
      const kind = ["error", "decision"].includes(event.kind) ? event.kind : "";
      const item = node("li", null, `trace-event ${kind}`),
        body = node("div"),
        heading = node("div", null, "trace-event-heading");
      item.append(
        node(
          "span",
          String(event.seq ?? index + 1).padStart(2, "0"),
          "trace-number",
        ),
      );
      heading.append(
        node(
          "h4",
          event.title || readable(event.kind || event.type) || "Recorded event",
        ),
      );
      if (event.at || event.timestamp) {
        const time = node("time", date(event.at || event.timestamp, true));
        heading.append(time);
      }
      body.append(heading);
      const data = record(event.data || event.payload);
      const summary = event.message || eventSummary(event.kind, data);
      if (summary) body.append(node("p", summary));
      if (Object.keys(data).length) {
        const details = node("details", null, "event-details");
        details.append(
          node("summary", "Inspect recorded data"),
          node("pre", serialize(data), "event-data"),
        );
        body.append(details);
      }
      item.append(body);
      item.dataset.eventIndex = String(index);
      container.append(item);
    });
  }
  function eventSummary(kind, data) {
    if (kind === "decision")
      return `Action: ${readable(data.action)} · Selection: ${readable(data.selection_source)}`;
    if (kind === "tests")
      return `${data.visibility === "hidden" ? "Final hidden" : data.visibility === "public_supplemental" ? "Supplemental public VERIFY" : "Original visible"} checks: ${ratio(data.passed, data.total)}${data.execution_error ? ` · ${data.execution_error}` : ""}`;
    if (kind === "tool_call")
      return `${data.tool || "Recorded tool"} · ${readable(data.visibility)} checks${data.orchestrated ? " · Harness-orchestrated execution" : ""}`;
    if (kind === "inference")
      return `${data.model || "Provider response"} · ${count(numeric(data.prompt_tokens) && numeric(data.completion_tokens) ? data.prompt_tokens + data.completion_tokens : null)} tokens · ${money(data.cost_usd)}`;
    if (kind === "context")
      return `${Object.keys(record(data.files)).length} supplied files · ${data.entrypoint || "Entrypoint not recorded"}`;
    if (kind === "model_switch")
      return `${data.from || "—"} → ${data.to || "—"}`;
    if (kind === "model" || kind === "retry")
      return `Attempt ${count(data.attempt)} · Model role: ${data.model_role || "—"}`;
    if (kind === "patch")
      return list(data.changed_files).length
        ? `Changed: ${data.changed_files.join(", ")}`
        : "No changed files recorded.";
    if (kind === "error")
      return data.error || data.note || "Inspect the recorded error payload.";
    if (kind === "complete")
      return `${readable(data.status)} · ${readable(data.stop_reason)}`;
    if (kind === "rollback")
      return data.note || "Restored the visible checkpoint.";
    if (kind === "prompt")
      return (
        data.success_criterion ||
        (list(data.prompt_messages).length
          ? `${data.prompt_messages.length} outbound messages · ${data.model_role || "Recorded model role"}`
          : "Recorded task prompt.")
      );
    return "";
  }
  function renderDiff(patch) {
    $("run-patch").replaceChildren(
      ...patch
        .split("\n")
        .map((line) =>
          node(
            "span",
            line,
            `diff-line ${line.startsWith("+++") || line.startsWith("---") ? "file" : line.startsWith("+") ? "add" : line.startsWith("-") ? "remove" : line.startsWith("@@") ? "hunk" : ""}`,
          ),
        ),
    );
  }
  function renderTests(run) {
    const evidence = record(run.evidence),
      publicEvent = list(run.events)
        .filter(
          (event) =>
            event.kind === "tests" &&
            !["hidden", "public_supplemental"].includes(record(event.data).visibility) &&
            Array.isArray(record(event.data).cases),
        )
        .at(-1),
      publicResult = record(
        evidence.public || run.public || run.public_result || publicEvent?.data,
      ),
      hiddenResult = record(
        evidence.hidden ||
          evidence.heldout ||
          run.hidden ||
          run.heldout ||
          run.hidden_result,
      );
    const container = $("run-tests");
    container.replaceChildren();
    const supplemental = list(run.events).find(event => event.seq === record(run.explorer).final_verification_event_seq && event.kind === "tests" && record(event.data).visibility === "public_supplemental");
    const groups = [
      [
        "Visible checks",
        publicResult,
        metricValue(run, "public_passed"),
        metricValue(run, "public_total"),
        false,
      ],
      [
        "Hidden checks",
        hiddenResult,
        metricValue(run, "heldout_passed"),
        metricValue(run, "heldout_total"),
        true,
      ],
    ];
    if (state.version === "v0.3-pilot1") groups.splice(1, 0, ["Supplemental public VERIFY", numeric(metricValue(run, "verification_passed")) ? record(supplemental?.data) : {}, metricValue(run, "verification_passed"), metricValue(run, "verification_total"), false]);
    for (const [label, result, passed, total, hidden] of groups) {
      const section = node("section", null, "test-group"),
        heading = node("h4", label);
      heading.append(
        node("span", ratio(passed ?? result.passed, total ?? result.total)),
      );
      section.append(heading);
      if (!hidden)
        for (const test of list(result.cases)) {
          const row = node("div", null, "test-row");
          row.append(
            node("p", test.name || "Visible check"),
            node(
              "span",
              test.passed === true
                ? "Pass"
                : test.passed === false
                  ? "Fail"
                  : "Not graded",
              test.passed === true
                ? "passed"
                : test.passed === false
                  ? "failed"
                  : "",
            ),
          );
          section.append(row);
        }
      section.append(
        node(
          "p",
          label === "Supplemental public VERIFY"
            ? numeric(passed) ? "Author-written public checks on the final candidate. Passing these is not the final success criterion; the hidden grader can still find a failure." : "The final candidate has no recorded supplemental result. Earlier candidate checks, if any, remain in the trajectory."
            : hidden
            ? numeric(passed ?? result.passed)
              ? "Final evaluation only. Hidden inputs and expected outputs are not shown in this explorer; the research source is public."
              : "No completed hidden evaluation recorded. This is not a zero pass rate."
            : list(result.cases).length
              ? "Visible failures may inform the next decision; earlier test executions remain in the trajectory."
              : "Individual visible outcomes are not present in this artifact; inspect the recorded test events.",
          "test-note",
        ),
      );
      container.append(section);
    }
  }
  function selectPanel(name, focus = false) {
    for (const tab of document.querySelectorAll(".inspector-tabs [role=tab]")) {
      const selected = tab.dataset.panel === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      $(`panel-${tab.dataset.panel}`).hidden = !selected;
      if (selected && focus) tab.focus();
    }
  }
  function stopReplay() {
    if (state.replayTimer) window.clearInterval(state.replayTimer);
    state.replayTimer = null;
    setText("replay-play", "Play recorded trace");
  }
  function replayAt(index) {
    const events = list(state.run?.events);
    if (!events.length) return;
    state.replayCursor = Math.max(0, Math.min(events.length - 1, index));
    for (const item of $("trajectory").children) {
      const n = Number(item.dataset.eventIndex);
      item.hidden = n > state.replayCursor;
      item.classList.toggle("replay-current", n === state.replayCursor);
    }
    $("replay-step").value = String(state.replayCursor + 1);
    setText("replay-position", `${state.replayCursor + 1} / ${events.length}`);
    setText("replay-status", `Recorded playback: ${events[state.replayCursor].title || readable(events[state.replayCursor].kind)}. No inference is running.`);
    $("replay-next").disabled = state.replayCursor >= events.length - 1;
    if (state.replayCursor >= events.length - 1) stopReplay();
  }
  $("replay-play").addEventListener("click", () => {
    if (state.replayTimer) { stopReplay(); return; }
    const events = list(state.run?.events);
    if (!events.length) return;
    replayAt(state.replayCursor === null || state.replayCursor >= events.length - 1 ? 0 : state.replayCursor);
    setText("replay-play", "Pause playback");
    state.replayTimer = window.setInterval(() => replayAt(state.replayCursor + 1), 1400);
  });
  $("replay-next").addEventListener("click", () => { stopReplay(); replayAt(state.replayCursor === null ? 0 : state.replayCursor + 1); });
  $("replay-step").addEventListener("input", () => { stopReplay(); replayAt(Number($("replay-step").value) - 1); });
  $("replay-all").addEventListener("click", () => {
    stopReplay(); state.replayCursor = null;
    for (const item of $("trajectory").children) { item.hidden = false; item.classList.remove("replay-current"); }
    setText("replay-position", `all ${count(list(state.run?.events).length)} events`);
    setText("replay-status", "All recorded events shown. No model request.");
    $("replay-next").disabled = false;
  });
  async function walkthrough(kind) {
    const target = record(record(state.benchmark?.walkthroughs)[kind]);
    if (!validId(target.task_id) || !validId(target.run_id)) return;
    $("task-search").value = ""; $("category-filter").value = ""; $("split-filter").value = "";
    renderTaskList();
    await selectTask(target.task_id, target.run_id);
    selectPanel(kind === "verification_miss" ? "tests" : "patch");
    $("run-title").scrollIntoView({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
  }
  $("walkthrough-repair").addEventListener("click", () => walkthrough("repair"));
  $("walkthrough-miss").addEventListener("click", () => walkthrough("verification_miss"));
  $("comparison-split").addEventListener("change", () => {
    state.comparisonSplit = $("comparison-split").value;
    showBenchmark(state.benchmark);
    announce(`Comparison sample: ${$("comparison-split").selectedOptions[0].textContent}.`);
  });
  $("study-select").addEventListener("change", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("version", $("study-select").value);
    url.searchParams.delete("task"); url.searchParams.delete("run");
    history.replaceState({}, "", url);
    init($("study-select").value);
  });
  $("filter-form").addEventListener("submit", (event) =>
    event.preventDefault(),
  );
  $("task-search").addEventListener("input", renderTaskList);
  $("category-filter").addEventListener("change", renderTaskList);
  $("split-filter").addEventListener("change", renderTaskList);
  $("source-file").addEventListener("change", () =>
    setText(
      "source-code",
      record(state.task?.files)[$("source-file").value] ??
        "No source file selected.",
    ),
  );
  $("final-file").addEventListener("change", () =>
    setText(
      "final-source",
      record(state.run?.final_files)[$("final-file").value] ??
        "No final file selected.",
    ),
  );
  $("run-select").addEventListener("change", () =>
    selectRun($("run-select").value),
  );
  const tabs = [...document.querySelectorAll(".inspector-tabs [role=tab]")];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectPanel(tab.dataset.panel));
    tab.addEventListener("keydown", (event) => {
      const next =
        event.key === "ArrowRight"
          ? (index + 1) % tabs.length
          : event.key === "ArrowLeft"
            ? (index - 1 + tabs.length) % tabs.length
            : event.key === "Home"
              ? 0
              : event.key === "End"
                ? tabs.length - 1
                : null;
      if (next !== null) {
        event.preventDefault();
        selectPanel(tabs[next].dataset.panel, true);
      }
    });
  });
  async function init(version = state.version) {
    const generation = ++state.loadRequest;
    ++state.taskRequest; ++state.runRequest;
    state.version = version; state.comparisonSplit = "test";
    POLICIES = version === "v0.3-pilot1" ? PILOT_POLICIES : V2_POLICIES;
    state.task = null; state.tasks = []; state.benchmark = null;
    clearRun("Loading this study’s recorded evidence…");
    $("study-select").value = version; $("comparison-split").value = "test";
    $("task-search").value = ""; $("category-filter").value = "";
    $("split-filter").replaceChildren(new Option("All splits", ""), ...(
      version === "v0.3-pilot1" ? [["test", "Primary test"], ["validation", "Validation"], ["external", "Source-derived"]] : [["train", "Training"], ["validation", "Validation"], ["test", "Held-out test"]]
    ).map(([value, label]) => new Option(label, value)));
    $("load-error").hidden = true;
    const url = new URL(window.location.href); url.searchParams.set("version", version); history.replaceState({}, "", url);
    const results = await Promise.allSettled([request(""), request("/tasks")]);
    if (generation !== state.loadRequest) return;
    if (results[0].status === "fulfilled") showBenchmark(results[0].value);
    else {
      showBenchmark({ status: "unavailable", summary: [], runs: [] });
      status("study-status", "Evidence unavailable", "unavailable");
      setText(
        "coverage-copy",
        "The results service could not be reached. No success or cost measurements can be shown.",
      );
    }
    if (results[1].status === "fulfilled")
      populateCatalog(results[1].value.tasks);
    else {
      setText(
        "task-list",
        "The task catalog could not be loaded. Reload the page to retry.",
      );
      setText("filtered-count", "Catalog unavailable");
      setText("catalog-summary", "Catalog unavailable");
      setText("task-title", "Task catalog unavailable");
    }
    if (results.some((result) => result.status === "rejected")) {
      setText(
        "load-error",
        "Some recorded evidence could not be loaded. Available artifacts remain inspectable; reload to retry.",
      );
      $("load-error").hidden = false;
    }
  }
  let resizeFrame;
  window.addEventListener("resize", () => {
    if (resizeFrame) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      if (state.benchmark) renderChart(comparisonRows());
    });
  });
  init();
})();
