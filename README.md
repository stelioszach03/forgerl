# ForgeRL

**Inspect how a coding agent spends its next attempt.**

ForgeRL is a research workbench for bounded Python repair. A visitor selects an authored regression task, follows real model-generated edits and isolated test execution, and inspects the final patch, held-out checks and request accounting. A separately trained controller chooses between request configurations or stops; the hosted language-model weights stay unchanged.

[Open the demo](https://stelioszach.com/demos/forgerl/) · [Methodology](docs/METHODOLOGY.md) · [Pilot findings](docs/PILOT_FINDINGS.md) · [Operations](docs/OPERATIONS.md) · [Benchmark artifact](artifacts/benchmark.json)

## What is implemented

- **Repair episodes:** visible-test feedback, complete replacement modules, bounded attempts, final held-out grading and downloadable patch/JSON traces.
- **Controller experiment:** tabular fitted-Q learning from actual training transitions, compared with fixed short-budget, deliberate-only and heuristic policies.
- **Evidence workbench:** responsive source, patch, test and event views; recorded runs and explicit unavailable/partial states.
- **Finite inference spending:** durable SQLite reservations, separate research/public allowances and conservative accounting for uncertain requests.
- **Restricted execution:** a dedicated Unix-socket broker invokes disposable rootless-Docker containers in production. The web service has neither a Docker socket nor access to the executor account.

The current provider adapter uses Runpod-hosted IBM Granite 4.0 H-Small for the short configuration and GPT-OSS 120B for the extended configuration. Request names describe configured budgets; task performance is measured rather than assumed. No always-running GPU is required.

## Read the evidence correctly

The suite contains **24 authored tasks**, separated by family into **12 training, 6 validation and 6 test tasks**. It is a controlled repair pilot, not SWE-bench or arbitrary repository execution.

Three predeclared seeds—**17, 29 and 43**—repeat the study. Full coverage produces **18 evaluation episodes per policy on six unique held-out tasks from two families**. Seed repetitions are not additional independent tasks. Each seed trains its own controller; the production artifact is fixed to seed 17 before evaluating results. Hosted-model sampling is not guaranteed to be deterministic.

The [benchmark artifact](artifacts/benchmark.json) is the result source of record. Read its `status`, coverage, failures, per-task/seed rows and manifest hashes before comparing means. Missing work remains partial. The completed pilot recorded **11/18 held-out successes for the learned controller and 18/18 for deliberate-only**, across the same six tasks and three seeds; it did not establish an improvement over that baseline. See [pilot findings](docs/PILOT_FINDINGS.md) for the full comparison and failure analysis. The [methodology](docs/METHODOLOGY.md) explains training rewards, hidden-test separation, prospective evaluation and the limits of this small sample.

Cost estimates use a conservative common $10/million-token rate because the provider’s published Granite prices conflicted. Economic comparisons are conditional on that rate, not verified invoice savings.

Live inference uses a finite prepaid allowance. Recorded evidence remains useful when new model requests are paused or the allowance is exhausted; replay is labeled separately from fresh inference.

## System layout

```text
Browser
  │ same-origin HTTPS
Nginx → FastAPI + one queue worker → Runpod hosted inference
                │
                ├─ SQLite: jobs, events, persistent spending reservations
                ├─ frozen controller + published experiment artifacts
                └─ restricted Unix socket
                         │
                  dedicated executor UID
                         │
                  rootless Docker
                  no network · no host mounts · read-only filesystem
```

The API/data owner and executor use different Unix identities. Production containers run as an unprivileged user with CPU, memory, PID, output and wall-time limits. Expected test outputs stay in the trusted grader. Container isolation shares the host kernel; this is not a microVM boundary or a claim that arbitrary hostile code is safe.

## Run locally without inference

Use Python 3.12 and Node 24. Node is only needed for frontend development checks; the browser app itself has no bundled runtime dependencies.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m pytest -q
npm ci
npm run test:frontend
```

Preview the UI with the queue worker disabled:

```sh
FORGERL_WORKER=0 FORGERL_PUBLIC_ORIGIN=http://127.0.0.1:8000 \
  python -m uvicorn forgerl.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Without a signing key, provider credential and execution broker, fresh paid runs stay unavailable. Published artifacts can still be inspected if included in the checkout. This preview does not execute model code.

### Real sandbox acceptance

A configured Docker context is required for the explicitly enabled integration checks:

```sh
docker build -t forgerl-sandbox:v1 sandbox
FORGERL_RUN_DOCKER_TESTS=1 python -m pytest -q
```

These checks run the authored buggy modules, trusted reference implementations and bounded timeout/output fixtures. They do not call a model provider. The configured local Docker context may differ from production's rootless setup; deployment isolation is checked separately with `scripts/verify_isolation.py`.

CI runs Python checks with the Docker integration flag enabled on an ephemeral Ubuntu runner, plus locked Node frontend checks. No Runpod key, research execution or deployment credentials are configured in CI. DOM tests cover behavior and escaping; they do not replace visual browser inspection.

## Reproduce the controller study

The safe default prints the protocol and makes no provider request:

```sh
python scripts/research_run.py
```

Paid collection requires a configured private credential file, the shared persistent budget database and a working restricted executor. Use one operator process, preserve the ledger across all three seeds, and review the [operations guide](docs/OPERATIONS.md) first. Example configuration uses placeholders:

```sh
export RUNPOD_API_KEY_FILE=/path/to/private/provider-key
export FORGERL_DB=/path/to/persistent/forgerl.sqlite3
export FORGERL_EXECUTOR_SOCKET=/path/to/private/executor.sock
python scripts/research_run.py --execute-research --seed 17 --output evidence/seed17
python scripts/research_run.py --execute-research --seed 29 --output evidence/seed29
python scripts/research_run.py --execute-research --seed 43 --output evidence/seed43
python scripts/aggregate_studies.py \
  --study 17=evidence/seed17 --study 29=evidence/seed29 --study 43=evidence/seed43 \
  --output artifacts/benchmark.json
```

The same ledger enforces **$12 research + $8 public inference**, leaving **$5 reserve** from the original $25 allowance. These are one-time limits, not a monthly subscription. Costs use provider token counts and conservative pricing estimates, not invoices. Timeouts with uncertain billing retain their reservations. Do not use a new database to bypass exhausted limits.

Each study saves a manifest, raw JSONL trajectories, training transitions, a frozen controller and summary files. The aggregator checks split/policy identity, fingerprints and duplicate rows. It never substitutes the best-scoring seed for the predeclared production controller.

## Repository map

| Path | Purpose |
|---|---|
| `forgerl/tasks.py` | Authored tasks and public/held-out case separation |
| `forgerl/controller.py` | Observable-state encoding, baselines and tabular fitted-Q learning |
| `forgerl/orchestrator.py` | Actual model/test episodes and event traces |
| `forgerl/provider.py` / `store.py` | Provider adapter, durable queue and spending ledger |
| `forgerl/sandbox.py` / `sandbox/` | Restricted executor, Docker boundary and trusted grading |
| `forgerl/research.py` / `scripts/` | Collection, prospective evaluation, aggregation and deployment tools |
| `static/` | Dependency-free browser interface |
| `tests/` / `frontend-tests/` | Offline, execution-boundary and browser-behavior checks |

## License and attribution

Original code, authored task fixtures and documentation are available under the [MIT License](LICENSE). The SZ logo and personal branding are excluded; see [NOTICE](NOTICE) before reusing the interface. Hosted model weights are not distributed here and retain their respective upstream licenses and service terms.

Created by [Stelios Zacharioudakis](https://stelioszach.com/).
