# ForgeRL: a bounded, evidence-first implementation plan

Prepared 23 September 2026. This is a design proposal, not an experiment report. No credentials were accessed and no paid resources were provisioned for this research task. The supplied brief is an aspirational project description: all performance numbers in it are illustrative and must not appear as measured results.

## Recommended scope

Build an inspectable coding-repair agent with a learned **controller** that chooses whether to stop or request another patch from one of two frozen language models. The substantive contribution is the integrated execution/evaluation system and an explicitly small controller experiment. Do not describe this as a new foundation model, LLM fine-tuning, GRPO, a validated world model, or a breakthrough. Model routing is established prior work; RouteLLM is an appropriate related-work reference, not evidence that this implementation works. [RouteLLM paper](https://arxiv.org/abs/2406.18665)

The existing portfolio VPS runs the application, durable job ledger, controller inference, sandbox supervisor, evidence files and dashboard. Runpod Public Endpoints supply bounded inference requests without renting a persistent GPU. This is feasible for the existing 4-vCPU/16-GB machine if sandbox concurrency is one and tasks stay small. These hardware values were verified by the root agent, not independently here.

### Stage 1 — working system and honest pilot

- Curated Python repair tasks with immutable source snapshots, visible tests, separately held evaluation tests, provenance, family IDs and difficulty notes.
- Actual model-generated source edits, restricted patch paths, actual test execution, finite call/CPU/memory/time budgets and an inspectable event trace.
- A small finite-horizon fitted-Q controller trained from real patch/test transitions. Model weights remain unchanged.
- A held-out, family-disjoint pilot comparing learned routing/stopping with reasonable fixed-model and heuristic baselines.
- Live public runs while an explicitly finite prepaid allowance remains. Recorded real runs and reproducible local evaluation remain available after allowance exhaustion.
- Public UI separates `live run`, `recorded trajectory`, `training`, `validation` and `held-out evaluation`. A cache hit is never presented as fresh inference.

### Stage 2 — strengthen research after the initial evidence

Expand task families and prospective repetitions, evaluate on pinned licensed real-repository tasks, compare other routing methods and publish reproducible artifacts. Only consider open-weight fine-tuning/GRPO after first measuring where the controller fails and authorizing a separate compute budget. A few dozen curated tasks cannot support general claims about autonomous software engineering or hiring-level capability. SWE-bench is an external repository-repair benchmark, not a name to attach to an unrelated in-house suite. [SWE-bench original paper](https://arxiv.org/abs/2310.06770)

## Providers and pricing: important verified discrepancy

| Candidate | Official endpoint | Verified pricing evidence | Recommendation |
|---|---|---|---|
| IBM Granite 4.0 H-Small | `https://api.runpod.ai/v2/granite-4-0-h-small/runsync` | Endpoint documentation says **$10 / 1M tokens**; main pricing page says **$1 / 1M**. These conflict. | Reserve at $10 / 1M until actual authenticated billing evidence resolves the discrepancy. Probe coding behavior before selecting. |
| GPT-OSS 120B | `https://api.runpod.ai/v2/gpt-oss-120b/runsync` | Endpoint documentation says **$10 / 1M tokens**. | Candidate second model; do not assume better task performance before the probe. |
| Qwen3 32B AWQ | `https://api.runpod.ai/v2/qwen3-32b-awq/runsync` | Endpoint documentation says **$10 / 1M tokens**. Its example response cost is arithmetically inconsistent with that rate. | Backup candidate, not an established cheaper tier. |

Sources: [Granite endpoint](https://docs.runpod.io/public-endpoints/models/granite-4), [GPT-OSS endpoint](https://docs.runpod.io/public-endpoints/models/gpt-oss-120b), [Qwen endpoint](https://docs.runpod.io/public-endpoints/models/qwen3-32b), [Runpod pricing](https://www.runpod.io/pricing).

The native endpoints document `cost`, token counts, provider execution time and queue delay. Prefer this response shape for the accounting ledger. Granite uses `input.messages` and nested `input.sampling_params`; Qwen and GPT-OSS native examples use `input.prompt` and `input.max_tokens`. Do not assume identical request schemas. Store the precise model identifier, request configuration and provider request ID. Keep a versioned adapter per endpoint. [Runpod request documentation](https://docs.runpod.io/public-endpoints/requests)

IBM's own model card identifies Granite 4.0 H-Small as a 32B-parameter model with 9B active parameters and Apache-2.0 licensing. Label providers by exact names and measured cost/latency, not unsupported "small/fast" and "large/strong" labels. Model-card training claims belong to IBM, not this project. [IBM model card](https://huggingface.co/ibm-granite/granite-4.0-h-small)

A self-hosted fallback is frozen Qwen2.5-Coder 1.5B/7B inference on a single temporary GPU, but it adds lifecycle/storage obligations and is unnecessary if public endpoints work. Both official model cards identify code-specialized instruct models and Apache-2.0 licensing. No performance advantage on our tasks has been established. [1.5B model](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct), [7B model](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct)

## Budget controls, not a promise of permanent free live inference

Root's allocation is **$12 initial experiments + $8 finite public reserve + $5 contingency = $25 maximum**. This is one-time spending authorization, not $25/month. A public key-free visitor experience must stop accepting paid work when the local reserve is exhausted; it can continue serving recorded evidence and free sandbox replay. Do not enable auto-top-up or rent idle GPUs.

Runpod's default account spending limit is **$80/hour**, not a project cap, and auto-pay can refill account credit. Therefore provider balance alone does not enforce this task's allowance. [Billing documentation](https://docs.runpod.io/accounts-billing/billing)

Implement a durable reservation ledger in SQLite/PostgreSQL with an atomic transaction before every billable attempt:

1. Compute an upper-bound request charge from the upper price, bounded prompt tokens and bounded completion tokens. If exact tokenizer compatibility is unknown, use a documented conservative byte-derived bound plus template overhead; do not use `characters / 4` as a hard bound.
2. Atomically require `settled_cost + outstanding_reservations + new_reservation <= stage_cap` and the overall $20 normal operating cap, leaving $5 unspent contingency.
3. Single in-flight request initially; timeout, malformed output and rejected patches still count as attempts and may cost money.
4. Settle with provider-reported cost while also recording token-derived expected cost. If cost is absent, retain the conservative reservation. An ambiguous network failure does not refund a reservation or trigger an automatic duplicate request.
5. Reconcile provider balance/usage at start, after calibration and at completion. If reported charges exceed expected bounds, close the live gate and investigate.
6. A public session limit alone is insufficient: enforce a global allowance, global concurrency and a request-rate ceiling. Never expose provider keys or provider control APIs to the browser.

GPU Pods are billed by time and stopped persistent disks can continue billing. Serverless custom workers charge startup and idle timeout as well as execution. This is why managed public endpoints are the preferred first implementation here. If any Pod is used later, export artifacts, verify checksums and terminate it; stopping alone is not a zero-cost guarantee. [Pod pricing](https://docs.runpod.io/pods/pricing), [Serverless pricing](https://docs.runpod.io/serverless/pricing)

## Concrete experiment under the $12 initial cap

These are proposed **maximum counts**, not completed runs. Stop or shrink the protocol if the reservation ledger cannot afford the next complete paired evaluation block.

### Task suite and split

Start with **24 tasks: 12 train, 6 validation, 6 final test**, grouped by defect family before any model calls. Use at least four train families and two distinct families for each evaluation split; if there are only six test tasks, explicitly report that the pilot is underpowered. Do not create train/test variants from the same faulty template and call that family generalization.

Useful controlled families include TTL boundary behavior, bounded-cache eviction, cursor pagination, retry/backoff parsing, interval overlap, timezone normalization, rate-window accounting and CSV escaping. Prefer compact multi-function modules rather than isolated arithmetic puzzles. Clearly label newly authored tasks as curated/synthetic engineering tasks, never real historical customer incidents.

Every task must pass these checks before spending:

- Original buggy snapshot fails at least one visible and one hidden test.
- Reference implementation passes all tests.
- Hidden tests contain specification-valid edge cases, not secret requirements.
- Tests are immutable, outside writable candidate paths, and are not copied into model context.
- Mutation checks cover at least "return constant", "skip validation" and the original bug.
- Record task manifest hash and split hash before training. No relabeling/removal of difficult tasks after results are visible.

### Calls and proposed upper bound

Use two models, maximum **three patch attempts** per episode. At most 2,750 combined billed tokens per call would cost $0.0275 at the conservative $10/1M rate; this is a planning bound only and must be enforced by actual input/output limits.

| Phase | Maximum model calls | Arithmetic at 2,750 tokens and $10/1M |
|---|---:|---:|
| Training: 12 tasks, full binary action tree to depth 3 | 168 | $4.62 |
| Validation: 6 tasks × 4 policies × up to 3 calls | 72 | $1.98 |
| Prospective final test: 6 tasks × 4 policies × up to 3 calls | 72 | $1.98 |
| Subtotal | 312 | $8.58 |

The remaining $3.42 within the $12 initial cap covers calibration, provider variance and minimal reruns. Do not spend it automatically. A full tree with 48 tasks would exceed this conservative budget and is not recommended. If visible tests pass early, still account for the stop decision; training branches can be pruned by a predeclared rule, not selected after seeing model quality.

Use 4–6 separate calibration tasks to verify response parsing, maximum length, run cost, latency and actual candidate-code quality. Calibration tasks belong to development, never final test. If one endpoint is unavailable or output quality is unusable, document the failed probe and use an explicitly single-model horizon experiment; do not fabricate routing evidence.

### Sequential decision process and real RL claim

An episode begins with source, an issue specification and a first visible-test result. Actions are `STOP`, `PATCH_MODEL_A`, `PATCH_MODEL_B`. Patch actions invoke an unchanged model with current source and the latest public test feedback; the resulting patch is validated and executed. `STOP` accepts the current candidate. Do not add a cosmetic `REPLAN` action unless it changes the actual prompt/state and has experimental coverage.

Controller features are limited to observable values: attempts remaining, visible-test pass fraction, syntax-valid flag, previous pass-fraction change, repeated-patch flag, previous model, candidate-size/diff-size buckets, observed latency/cost so far and failure category. Exclude task ID, split, reference source, hidden-test outcome, future branch results and hand-assigned difficulty labels. A task family may be logged for analysis but should not be a shortcut feature.

Train a finite-horizon **fitted-Q** controller from `(state, action, reward, next_state, terminal)` transitions collected in training only. A compact ridge regressor or small tree ensemble per remaining horizon is sufficient. Compute targets backwards:

`target = immediate_reward + (0 if terminal else max_available_action Q(next_state))`

The stop transition receives terminal hidden-test success; earlier patch rewards already account for incurred cost, so do not subtract that cost again. A patch transition receives its negative measured request cost (and a predeclared small test-step penalty); end-of-budget patch transitions also receive terminal success. Hidden tests may supply training rewards, but must never become an input feature or feedback to the coding model. Keep separate audit paths so this boundary is testable.

For example, start with terminal reward `1 if all hidden tests pass else 0`, cost penalty `lambda * USD`, and no dense pass-count bonus; choose lambda from a small predeclared validation grid. A dense visible-test reward can encourage public-test overfitting and should be an explicitly separate ablation. Save training transitions, Q parameters, feature definitions, seeds, hyperparameters and a policy fingerprint. Fitted-Q is established batch RL; use this description rather than implying token-level policy gradient or LLM fine-tuning. [Fitted-Q reference](https://jmlr.org/papers/volume6/ernst05a/ernst05a.pdf)

A controller with only one decision before a single request is a contextual bandit, not evidence of adaptive-horizon sequential RL. A table of hand-written routing rules is a heuristic, not a trained policy. If the learned model collapses to a simple rule, report that outcome.

### Baselines and fair evaluation

All policies receive the same allowed files, visible tests, per-call token caps, maximum three attempts and per-episode dollar ceiling:

1. Model A only, stop at visible-test success or budget.
2. Model B only, same rule.
3. Heuristic: start A, switch B after no public-test improvement, stop on public-test success or budget.
4. Frozen learned controller, no updates during evaluation.

Fixed-budget baselines should be competent; do not force them to waste 30 steps after solving a task merely to advertise savings. Equal **caps** do not mean equal spend: show both success and realized cost. Use identical task order/seed schedules where supported and randomize policy request order to reduce temporal provider effects.

Training tree replays are useful for debugging and policy fitting but are not prospective evaluation. Generate fresh trajectories on validation/test after fitting; never select successful samples from training trees as held-out live runs. If costs prevent fresh runs, label results `held-out tree replay` and do not claim prospective evidence.

## Evidence and publication requirements

Report counts and denominators before percentages: solved/attempted, final hidden-test success, public-test success, syntax failures, invalid patches, timeouts, provider errors, attempts, input/output tokens, reported USD cost, end-to-end wall time and provider processing/queue time. **Provider processing milliseconds are not GPU-seconds.** Never manufacture confidence percentages from Q-values.

Show per-task outcomes and differences, not only averages. Use paired bootstrap intervals grouped by task family where sample size permits, but with six held-out tasks describe them as descriptive uncertainty, not statistically established superiority. Include unsuccessful runs and a manifest of exclusions fixed before evaluation. Training compute/collection cost must be visible separately from per-episode serving cost; do not amortize training away silently.

Do not copy the brief's sample success rates, token savings, latency numbers, artificial trace lines or "thousands of trajectories". A suitable initial portfolio sentence, after implementation and verification, is:

> Built a budget-controlled coding-repair agent with isolated Python execution, inspectable model/tool traces and a finite-horizon controller trained from measured patch/test trajectories; evaluated against fixed-model and heuristic policies on a small family-disjoint task suite.

Add the actual suite size, date, measured results and limitations only after the corresponding report is generated. Any public "research" document should be a technical report or project methodology, clearly unpublished and unreviewed.

## Safety and deployment boundaries

The browser chooses a task ID and policy only. No arbitrary repository URL, uploaded executable, shell command, package installation or user-provided code is needed for this version. The model can modify a bounded list of source files; it cannot change tests or the runner.

Use an unprivileged disposable worker with no network, no secrets, read-only root, bounded tmpfs/workdir, CPU/memory/PID limits, timeout and process-tree cleanup. Container isolation reduces risk but is not an absolute sandbox guarantee. A web process must not hold an unrestricted Docker socket; put the tightly scoped execution interface in a separate service and enforce allowed images/flags. Root owns the deployment decision and actual hardening.

Retain source hashes, applied patch, stdout/stderr limits and exit status. Escape all model output in UI. Separate research/admin endpoints from public run endpoints. Budget exhaustion is a normal transparent state with recorded evidence available, not a provider error silently replaced by synthetic success.
