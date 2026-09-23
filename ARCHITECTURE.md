# ForgeRL architecture

ForgeRL v0.2 separates a private research executor from a public evidence reader. ForgeBench is its versioned benchmark, not a second product.

## Versioned experiments

The original v0.1 modules (`tasks.py`, `controller.py`, `orchestrator.py`, `research.py`) and artifacts remain an independent archived pilot. The v0.2 implementation lives under `forgerl/bench/`. Its exact behavior and limits are specified in [PROTOCOL.md](docs/forgebench/PROTOCOL.md). The initial implementation was frozen at commit `abadaff9ed014314ec14188701d13f7f09b3f443`; each study hashes the actual runtime files and immutable sandbox image independently of Git.

`tasks.py` defines the 50-scenario catalog and a deliberate public projection that excludes reference implementations and hidden cases. Family-disjoint splits are fixed before inference. `provider.py` builds a whitelist-based prompt, requests a bounded JSON files mapping, pins controlled OpenRouter routing, and stores actual usage cost or conservative reservations in the existing durable ledger. It never sends the full task dataclass to a provider.

`engine.py` supplies repository context, runs visible checks, obtains candidate edits and lets `router.py` choose retry, repair, escalation, rollback or stop. Files supplied by the harness are labeled as context, not autonomous inspections. Hidden grading and the reference-scope edit proxy occur only after the policy stops. `study.py` collects train-only transitions, fits and freezes the controller, then runs validation/test prospectively. Five policies share bounds. Errors and missing measurements are retained.

## Execution boundary

The API and research processes never execute generated source. `bench/sandbox.py` validates bounded flat module maps and transmits only candidate source and test inputs through the Unix broker in `forgerl/sandbox.py`. Trusted expected answers remain outside the execution payload. `sandbox/runner.py` loads modules in memory inside a disposable rootless Docker container. The container has no network or host mounts, a read-only filesystem, UID65534, dropped capabilities, no-new-privileges and CPU/memory/PID/time/output limits.

Local repository modules are reloaded for each v0.2 case; imported standard-library state can persist within a container. AST/import screening is defense in depth. It is not a guarantee that Python introspection or transitive standard-library capabilities are impossible. The container and its limits are the boundary; the host kernel is shared.

## Public evidence surface

`bench/api.py` exposes only GET endpoints for published metadata, task descriptions, source, complete stored runs and patches. Artifact identifiers are constrained, symlink targets rejected, loads bounded and hidden/internal fields scrubbed. `app.py` disables public inference by default, does not initialize a worker or provider session in read-only mode, and retains the archived v0.1 read endpoints. `static/bench.*` renders data as text and uses no third-party runtime scripts.

The public backend can remain online without a model credential, GPU, active experiment or renewed credit balance. Updating an artifact changes the presentation; it does not rerun a model. Source hashes, configuration hashes, task hashes, exact provider settings and original trace hashes tie the displayed comparison to its measured evidence.

## Accounting and publication

The original SQLite ledger remains the spend authority. Reservations are committed before network calls and retained if billing is unknown. OpenRouter supplies a separate non-renewing key limit; episode and study caps provide additional bounds. A study never resets or clones the research ledger to obtain a new allowance.

The aggregator verifies compatible protocols, providers, task/runtime hashes and unique task/policy/seed identities. It retains all three predeclared seeds, including absent or failed runs. Statistical summaries use held-out tasks; training/validation are distinct. Related variants are clustered by family, and the two-family test split cannot support broad population inference.

Operational separation and deployment checks are documented in [OPERATIONS.md](docs/forgebench/OPERATIONS.md). No fault-tolerance or distributed-compute claim is made for a single VPS.
