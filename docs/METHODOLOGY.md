# ForgeRL methodology

ForgeRL investigates a narrow question: can a controller allocate a small number of language-model patch attempts using visible test feedback? The application edits curated Python tasks, executes the candidates in isolation, and records patches, tests, token use, cost and latency. This document describes the implemented protocol. Numerical results are evidence only when accompanied by a completed run manifest and raw traces.

## Scope of the claim

The language-model weights are frozen. Learning applies to the controller's choice of `fast`, `deliberate` or `stop`; it is not LLM fine-tuning, GRPO, a new foundation model, or demonstrated general autonomous software engineering. Action names describe request configurations, not a verified capability ordering. The maximum is three patch requests per episode. Task complexity, the restricted execution interface and this short horizon limit generalization.

This is a curated engineering-task suite, not SWE-bench. Its tasks illustrate regression problems with explicit specifications and edge cases. Related work includes [RouteLLM](https://arxiv.org/abs/2406.18665) for learned model routing, [batch fitted-Q learning](https://jmlr.org/papers/volume6/ernst05a/ernst05a.pdf) for control from transitions, and [SWE-bench](https://arxiv.org/abs/2310.06770) for an external repository-repair evaluation setting. The existence of those methods is not evidence of ForgeRL performance or novelty.

## Data separation

Each task has a stable ID, defect family and split. A validation step rejects duplicate IDs and families that appear in more than one split before model requests are made. The intended pilot has 12 training, 6 validation and 6 test tasks. The exact executed set is stored in `manifest.json`; missing work stays visible as incomplete coverage.

The model sees the issue, candidate source and public-test feedback. Reference implementations and held-out expected outputs are not model inputs. Hidden tests measure whether a patch generalizes beyond the visible examples; they do not establish universal correctness. Hidden test outcomes may label rewards during training, but never enter the controller's state features. Validation and final-test outcomes are never used to update the policy.

All variants of one defect family stay within one split. This guards against one obvious form of leakage; it does not prove that a pretrained model has never seen a similar programming pattern.

## Collecting real controller transitions

Training explores both patch configurations from each visited state, up to a depth of three. A branch is a fresh clone of source and history and shares only the provider's durable budget ledger. Every generated candidate is actually tested. Branches stop at visible-test success, the request cap or an execution/provider failure. The visible-test success stop is a shared scaffold rule, not a learned achievement.

At each visited training state, an independent copy is also evaluated as a STOP candidate using trusted hidden tests. STOP labels need no additional model inference. Those hidden outcomes produce rewards; they are not sent back as coding feedback. No hand-authored solution is substituted for a model patch.

A transition records observable state, action, immediate reward, next observable state, terminal flag, task ID, split and branch route. Invalid model output is represented by the actual failed patch/test outcome. Infrastructure failures are retained in raw traces and mark collection partial; they are not silently converted into usable learning labels.

The return uses terminal hidden-test success (one for all tests passing, zero otherwise) and a penalty on the conservatively estimated request cost. For a nonterminal patch:

`reward = -cost_weight * incremental_request_cost_usd`

For a terminal patch, terminal success is added. STOP receives only terminal success, because earlier transition rewards already charged the cost. The default `cost_weight` is 5.0 and is recorded before collection. No confidence percentage is inferred from a Q-value.

## Policy learning and frozen evaluation

The controller fits Q-values from training transitions, using observable public-test progress, remaining attempts and request cost/budget information. Task identifiers and hidden outcomes are excluded from the state encoding. Controller parameters, training diagnostics and a SHA-256 fingerprint are saved.

The same frozen artifact is evaluated on validation and final-test tasks. In this first protocol validation is a separately reported diagnostic split; no hyperparameter search or post-validation retraining is performed. Future tuning must use a new versioned protocol and keep final test untouched.

Four policies receive the same source, tests, request cap and provider limits:

1. **Fixed fast:** use the fast configuration, stopping at visible-test success or the cap.
2. **Deliberate only:** use the deliberate configuration with the same stop rule.
3. **Heuristic:** use the documented controller heuristic based on visible progress.
4. **Adaptive:** use the frozen learned controller.

Every validation/test run starts a fresh episode and makes its own prospective provider requests. Training-tree replay is not reused as final-test inference. Policy order is deterministically shuffled per task to reduce systematic order effects. A recorded seed is a requested sampling configuration, not a promise of bitwise provider reproducibility.

Fixed policies are permitted to stop when their visible tests pass. The comparison does not force an already successful baseline to waste calls. Equal caps do not imply equal realized cost; both outcome and spending are reported.

## Measurement and uncertainty

The report includes solved/attempted counts, success rate, requests, tokens, estimated USD cost, wall-clock latency and provider/execution failures. Failures remain in the attempted-run denominator. Tasks that could not be attempted because the allowance ran out are listed as missing; they are not counted as successful or silently dropped. A partial run cannot become a complete benchmark merely because its surviving runs look good.

Per-policy success intervals use the Wilson binomial interval. Task variants may be correlated, so these intervals are descriptive. Paired success-rate differences compare the same task IDs. A family-cluster bootstrap interval is shown only when at least three paired families exist; otherwise it is omitted with an explicit explanation. With six held-out tasks, neither an interval nor a point estimate supports a broad superiority claim.

Training collection cost is separate from evaluation/serving cost. Shared prefixes in the branch tree are not billed repeatedly in collection totals, but individual trajectory records show their full accumulated history. Provider-call wall time is **not GPU time**. Current USD values use provider-reported token usage multiplied by the conservative published rate; they are estimates, not invoices. Request failures with uncertain billing retain a conservative cost reservation.

## Evidence files

Each execution uses a new directory and writes:

- `manifest.json`: protocol, task/split hash, caps, seeds, timestamps, frozen policy fingerprint and completion status.
- `raw-runs.jsonl`: training branches, stop audits, prospective runs and failures, with the underlying episode traces.
- `transitions.jsonl`: training-only controller transitions.
- `controller.json`: learned artifact; optional separate diagnostics when supplied by the fitter.
- `training-summary.json`: per-task collection completeness and costs.
- `benchmark.json`: test results, separate validation results, per-task comparisons and limitations.

The CLI prints a plan by default. `--execute-research` explicitly activates provider calls; it never raises the durable research spending cap. The provider ledger atomically reserves funds before each request. When the finite allowance ends, live requests stop and recorded evidence remains available. A historical trace or sandbox replay is clearly labeled and is not presented as a fresh model run.

## Cost and deployment boundaries

Runpod's public model endpoint documentation currently lists $10 per million tokens for the configured candidates. Its main pricing page conflicts for Granite, so reservations conservatively use the higher figure until actual billing reconciles it. The account-wide Runpod limit is not the project budget. [Granite endpoint pricing](https://docs.runpod.io/public-endpoints/models/granite-4), [Runpod billing](https://docs.runpod.io/accounts-billing/billing)

The public app selects curated task IDs. It does not accept unrestricted repository execution. Candidate tests run in a constrained worker with no provider key and no network access. Provider access, budget accounting and the executor control interface stay server-side. These measures reduce risk; they are not a guarantee that arbitrary hostile code is safe on shared infrastructure.

## Predeclared three-seed study

Protocol addition fixed at **2026-09-23 03:46:42 UTC**, after endpoint/executor smoke checks and before the three-seed study. The smoke checks established service behavior; they are development observations and are excluded from the benchmark. The task catalog, splits, collection algorithm, reward, hyperparameters and comparison policies remain as described above.

Run the entire pilot using controller/model-request seeds **17, 29 and 43**, in that order. Each seed independently collects training transitions, fits a controller, and prospectively evaluates the same validation and test task families. Provider nondeterminism means these are requested seed replicates, not guaranteed deterministic executions. All three runs share the existing **$12 total research cap**; no extra allowance is created. If the budget prevents finishing, publish the partial coverage and failures without selecting favorable runs or replacing seeds.

The production controller is **always the seed-17 artifact**, chosen before evaluation. If that artifact is missing or untrained, production adaptive selection remains unavailable; do not substitute whichever other seed scores highest.

At full coverage, each policy has **18 held-out evaluation episodes: six unique tasks from two families, repeated at three seeds**. These are not 18 independent tasks. Pair each policy outcome using both task ID and seed, and retain the original task ID alongside that comparison key. Report unique-task count, family count, requested/completed replicates and coverage explicitly.

The aggregate publishes episode means and all task/seed outcomes. It does not attach an ordinary binomial confidence interval to the 18 correlated episodes. With only two held-out families, a meaningful family-cluster confidence interval is not estimated. Variation across these replicates describes this small pilot; it is not evidence of broad superiority.

The aggregate records each source manifest's SHA-256 hash, the raw evidence file hash, controller fingerprint, split identity and completion state. A missing or incomplete seed marks the combined study partial. The original seed studies remain available independently, including failures and costs.
