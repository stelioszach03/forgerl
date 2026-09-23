# ForgeRL

**An ongoing research platform for adaptive routing and coding-agent evaluation.**

[Evidence dashboard](https://stelioszach.com/demos/forgerl/) · [ForgeBench protocol](docs/forgebench/PROTOCOL.md) · [Task catalog](docs/forgebench/CATALOG.md) · [Operations](docs/forgebench/OPERATIONS.md) · [v0.1 pilot](docs/PILOT_FINDINGS.md)

| Research status | Evidence |
| --- | --- |
| Last completed benchmark | September 2026 · v0.1 pilot |
| Current catalog | ForgeBench v0.2 · 50 authored scenarios / 10 miniature repository families |
| Current evaluation | Three seeds predeclared: 17, 29, 43; v0.2 collection in progress |
| Models in the v0.2 protocol | GPT-OSS-20B and GPT-OSS-120B through a pinned OpenRouter provider |
| Latest published release | [v0.1.0](https://github.com/stelioszach03/forgerl/releases/tag/v0.1.0) |

ForgeRL asks when a bounded coding agent should retry, repair, escalate to another model, roll back an edit, or stop. ForgeBench is its versioned task suite. The research pipeline collects actual model proposals and isolated test results; the public product lets readers inspect the stored evidence without spending API credits.

This is a research engineering project, not a claim of a new state-of-the-art routing algorithm or proven long-horizon autonomy. The hosted language-model weights remain unchanged. A separate tabular fitted-Q controller learns from training trajectories.

## What runs

- **50 authored scenarios:** bug fixing, multi-file changes, features, behavioral refactoring, failing tests and multi-requirement stress tasks. Ten related families have fixed family-disjoint training/validation/test splits of 30/10/10.
- **Five policies:** strong-only, cheap-only, cheap-to-strong after failure, a hand-written router, and an offline learned router with explicit fallback on unsupported states.
- **Observable trajectories:** task and provider prompts, supplied files, actual harness tool calls, proposed patches, visible tests, errors, retries, model changes, rollback and final hidden grading. No private model reasoning is recorded.
- **Measured outcomes:** success, hidden-test pass rate, accounted cost, tokens, latency, tool calls, attempts, visible regressions, success after repair, escalation and a clearly labeled reference-scope edit proxy.
- **Inspectable product:** responsive leaderboard, cost/success plot, task explorer, source/diff/test views, downloadable complete runs and a separate v0.1 archive.
- **Reproducible artifacts:** frozen task/configuration/source/image hashes, per-seed controllers, original trajectories, CSV exports, scientific figures and report-generation scripts.

All 50 starter/reference fixture pairs have been checked in real rootless Docker: every starter exposes a visible failure, and each reference passes both visible and hidden checks. The [verification receipt](evidence/forgebench-catalog-verification.json) records those checks; fixture verification is **not** a model benchmark score.

## Read the evidence correctly

The current suite comprises **50 scenarios in 10 miniature repositories**, not 50 independent production repositories. Five variants share each family. A `long_horizon` tag means a small integrated task with multiple requirements; it does not demonstrate hours of autonomous work. Refactoring is checked behaviorally, without proving maintainability.

Hidden tests are withheld from model prompts and run only after routing ends. Their definitions are released with the source for reproducibility, so they are not a permanently private or contamination-resistant test set. Public test passes are never substituted for hidden-test success.

The v0.2 protocol freezes each controller before prospective evaluation. Validation does not tune its parameters; test results do not choose a favorable seed. Failed calls, uncertain charges, partial coverage and unmeasured values remain visible. Repeated seeds do not create new independent task families. With only two held-out families, the report does not assert a population-level confidence interval or broad superiority.

The archived v0.1 pilot recorded **11/18 held-out successes for its learned controller versus 18/18 for deliberate-only**, on six unique tasks across three seeds. That negative finding is preserved. V0.1 and v0.2 results are different experiments and must not be pooled.

## Research and public serving are separate

```text
Operator-run research
  frozen protocol → hosted model API → proposed edits
                       │                    │
               durable spend ledger   restricted executor broker
                                            │
                                 disposable rootless Docker
                                 no network / no host mounts
                                            │
                          actual trajectories + final grading
                                            │
                           immutable CSV / JSONL / figures
                                            │
Public VPS 24/7: Nginx → read-only FastAPI → evidence dashboard
```

The public site cannot start inference, accept repository uploads or invoke a shell. Model credentials stay in private systemd credentials on the research host. There is no permanently allocated GPU. OpenRouter controlled runs pin the provider endpoint and quantization and disable fallback; the development `:floor` profile is a separate treatment. Provider checkpoint revisions remain unspecified when the service does not expose them.

Limits are enforced at the provider key, persistent ledger, study and episode levels. Default episodes allow at most six model calls, ten routing decisions, two repeat actions, three invalid candidates and a conservative 100,000-token bound. Existing charges survive restarts. Credit purchase fees are not included in per-call inference accounting. There is no automatic budget reset.

Container isolation is the execution boundary; AST screening is additional validation. A container shares the host kernel and is not a microVM. Only curated, bounded pure-Python module collections are supported. See [architecture](ARCHITECTURE.md).

## Reproduce without spending

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m pytest -q
npm ci --ignore-scripts
npm run test:frontend
python scripts/forgebench.py --seed 17
```

The final command prints the complete plan without reading credentials or starting inference. To run real container checks:

```sh
docker build -t forgerl-sandbox:v2 sandbox
FORGERL_SANDBOX_IMAGE=forgerl-sandbox:v2 \
FORGERL_RUN_DOCKER_TESTS=1 FORGERL_DOCKER_TESTS=1 python -m pytest -q
```

Preview the read-only dashboard:

```sh
FORGERL_PUBLIC_INFERENCE=0 FORGERL_WORKER=0 \
  python -m uvicorn forgerl.app:app --host 127.0.0.1 --port 8000
```

Paid research is deliberately explicit and uses an **existing** durable ledger. Follow [the protocol](docs/forgebench/PROTOCOL.md) and [operations](docs/forgebench/OPERATIONS.md) rather than creating a fresh budget database or copying keys into a command.

```sh
python scripts/aggregate_forgebench.py \
  --study 17=artifacts/forgebench/studies/seed17 \
  --study 29=artifacts/forgebench/studies/seed29 \
  --study 43=artifacts/forgebench/studies/seed43 \
  --output artifacts/forgebench/v0.2
python scripts/report_forgebench.py --input artifacts/forgebench/v0.2 --pdf
```

Report generation requires Matplotlib and ReportLab; it makes no model calls. A generated technical report is not a peer-reviewed paper or an automatically submitted preprint.

## A living benchmark

See [the maintenance policy](docs/forgebench/MAINTENANCE.md) and [changelog](CHANGELOG.md). New families, model endpoints and ablations receive a new frozen protocol and release. Completed experiments determine the “last benchmark run” field; cosmetic commits and scheduled checks do not update it. The next target is broader task diversity and held-out families before scaling the task count toward 200+.

Code and authored benchmark fixtures are MIT licensed. Existing SZ branding is excluded; see [NOTICE](NOTICE).
