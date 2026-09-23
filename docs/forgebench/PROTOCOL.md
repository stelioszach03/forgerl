# ForgeBench v0.2 protocol

ForgeBench evaluates a bounded closed-loop repository repair harness. These are original, authored miniature Python repositories, not real-world issue-resolution tasks. A `long_horizon` category stresses several linked requirements; its name does not establish real-world long-horizon ability. V0.1 artifacts remain a separate experiment and are not pooled with v0.2.

The initial expanded study predeclares three independent requested seeds: **17, 29 and 43**. All three results remain in the report. Each seed fits its controller on training tasks and evaluates the same fixed validation/test tasks; no seed is selected by test performance.

## Freeze before inference

The CLI defaults to planning. Paid execution requires `--execute-research`, an existing durable service ledger (`--db`), a private provider credential, a new evidence directory, and an available isolated executor. The script never creates a fresh spend ledger for a study. An exclusive ledger-adjacent lock prevents concurrent study processes. The study cap is enforced before each reservation, in addition to the persistent project cap. Unknown bills retain reservations. No cap renews automatically.

`plan.json` declares seed, catalog hash, task selection, five policies, call/decision budgets, training rollouts and study cost ceiling. The default includes all 30 training tasks and all 10 validation plus 10 test tasks. Lower `--train-per-family` or `--eval-per-family` selects lexicographic IDs within every family before inference; the report distinguishes catalog size from measured coverage. The default training plan uses two rollouts per training task, beginning with cheap then strong respectively. Subsequent legal actions use a seeded exploration policy. Hosted sampling seeds are requested; determinism is not guaranteed.

A `manifest.json` captures actual provider configuration and accounting. Provider settings are fixed by the selected profile; controlled OpenRouter and variable-provider development runs are different treatments. A production model checkpoint revision is not implied when the provider does not expose one. The source manifest records hashes of actual runtime files and the evaluated immutable sandbox image; aggregation rejects missing or incompatible provenance. Run the intended independent seeds in separately named directories and retain every result, including failures.

## Tasks and hidden tests

The 50-task catalog has ten families of five related variants, split 30/10/10 with no family crossing train, validation and test. Every task has a visible failing reproduction, explicit success criterion, reference implementation and hidden cases. Hidden means **withheld from the agent context during evaluation**, not secret forever: the reproducible source release contains the grading definitions. It is not a contamination-resistant private benchmark.

Flat modules are supplied as context. Imports execute only in a disposable networkless, read-only, non-root Docker container, with resource limits and no host mounts. Modules load in memory; code is never imported on the API or research host. Expected answers remain in the host grader. Protected files, source sizes, module names, AST constructs and import graphs are checked before execution. These checks supplement container isolation; the container, not the AST allowlist, is the security boundary. Every v0.2 case loads fresh local repository modules. Imported standard-library process state can persist between cases within the same grading container; this is not independent-process isolation for each case.

## Five policies and bounded actions

All policies receive identical files, visible tests, stopping rules and a maximum of six model requests and ten routing decisions. Output token ceilings match across model roles. A 100,000-token per-episode bound is checked before requests; explicit retry is capped at two additional calls, and malformed responses permit at most two subsequent attempts before stopping. Strong and cheap name configured roles, not universal model-quality claims.

- `strong_only`: start with the configured strong model, then repair with it.
- `cheap_only`: use the configured cheap model throughout.
- `escalate_on_failure`: begin cheap; after visible failure switch to strong and remain there.
- `static_router`: begin cheap; repair, escalate after stagnation or two attempts, and roll back visible regressions when a better checkpoint exists.
- `adaptive`: choose among empirically supported state/action fitted-Q values; explicitly use the static router for untrained artifacts or unseen states/actions.

`retry` requests another candidate from the current model; `repair` adds a focused instruction to preserve passing visible behavior; `escalate` selects the strong model; `rollback` restores the best visible checkpoint without a model call; `stop` terminates. A starting strong call is not counted as an escalation. A proposed switch rejected by prompt preflight or reservation is not an actual escalation; a response or charged failed request is counted. Malformed edits and candidates rejected by AST/protected-file checks share a three-invalid-response cap. Rollback is available only after a strict visible-score regression and at most once. All policies stop at full visible-test success or exhausted bounds. Hidden tests run once after all routing decisions; hidden failure never causes another repair.

Training transitions are accepted only from explicitly labeled training tasks with completed grading. Fitted Q uses a terminal correctness reward minus five times observed dollar cost. Inputs are visible pass fraction, attempts/remaining calls, current role, visible improvement, rollback state and remaining-budget bin. Task identity, family, hidden score and reference patch are not features. The learned artifact is hashed and frozen before validation/test. Validation is reported without modifying parameters; test results do not select or refit the controller. Sparse coverage is reported, including learned and fallback decision counts. Hosted model weights are never updated.

## Trajectories

Actual task prompts, supplied files, provider messages, visible response text, model identity and request configuration, token/cost observations, unified patches, sandbox calls, visible tests, errors, retries, switches, rollbacks and final grading are recorded. No private chain of thought is requested or stored. `events.jsonl` is flushed after every event, and full `runs/<id>.json` files are atomically written after episodes. Completed episodes, controller transitions and manifests are durable. An interruption can leave a partial trace; it does not fabricate a completion.

Files are **supplied context**, not evidence that the model independently read files. The `tool_calls` metric counts actual harness-orchestrated sandbox evaluations, including baseline and final grading. This is a model-only closed-loop repair agent, not an unrestricted shell/tool agent.

## Measurements

Task success requires all visible and hidden checks with completed grading. Success rate includes every attempted episode, including infrastructure/provider failures as unsuccessful attempts; missing planned episodes remain missing. Hidden-test pass rate covers graded hidden cases only, with graded-run coverage shown. Token counts are null when provider accounting is unknown. Cost uses the profile's stated basis: provider-reported API cost when available, or an explicitly labeled conservative token estimate. Neither includes arbitrary claims about GPU time or account purchase fees.

Metrics include cost, tokens, wall latency, sandbox calls, attempts, previously passing visible cases made failing, success after a second-or-later attempt, and cheap-to-strong escalation frequency. `unnecessary_edits` is a **post-decision reference-scope proxy**: modified files outside the reference patch's changed-file set. Alternative valid edits can count; this does not prove edits were unnecessary. The reference patch never enters the model prompt or routing observation.

Failure labels are observed proxies: repeated identical candidate, visible regression, invalid candidate, rejected execution, and visible-pass/hidden-fail. Localization, planning, context loss and causal over-editing remain unassigned without external annotation. A leaderboard cannot justify those causal attributions by itself.

Success-vs-cost comparisons must state coverage and provider cost basis. Paired differences average seeds within task, then bootstrap task-level differences; seeds are not independent tasks. With only two held-out families and related within-family variants, task intervals are conditional descriptive summaries, not reliable population-level confidence claims. No family interval or broad superiority claim is supported by this small benchmark.

## Run and inspect

```bash
python scripts/forgebench.py --seed 17 --max-cost-usd 5
python scripts/forgebench.py --execute-research --db /var/lib/forgerl/forgerl.sqlite3 \
  --provider openrouter --seed 17 --max-cost-usd 5 \
  --output artifacts/forgebench/v0.2-seed17
```

The public application reads published artifacts only. Browsers cannot start research, submit repositories or consume paid inference. Publication must retain partial coverage and provenance; configured models are not described as evaluated until real requests appear in the evaluation traces.


## Aggregate and reproduce the report

After the predeclared studies finish, combine their immutable artifacts. Missing seeds remain planned and mark the aggregate partial; do not replace a failed seed with a favorable rerun.

```bash
python scripts/aggregate_forgebench.py \
  --study 17=artifacts/forgebench/studies/seed17 \
  --study 29=artifacts/forgebench/studies/seed29 \
  --study 43=artifacts/forgebench/studies/seed43 \
  --output artifacts/forgebench/v0.2
python scripts/report_forgebench.py --input artifacts/forgebench/v0.2 --pdf
```

Aggregation uses only the standard library and project modules. Figures require Matplotlib; PDF rendering additionally requires ReportLab. The report generator was layout-checked with Matplotlib 3.11.2 and ReportLab 4.5.1. Re-render the final PDF with Poppler and inspect every page before publishing. The report is a technical software artifact, not a peer-reviewed paper or an arXiv submission.

The aggregate exports results CSV, per-event/full-run trajectories, observed failure-proxy counts, family-aware paired differences and provenance hashes. Source trajectory hashes and published-file hashes are both recorded. Test and validation summaries remain separate. No family interval is emitted with fewer than three observed held-out families. The four figures show success versus accounted cost, observed failure proxies, actual routing decisions and success by authored task category.
