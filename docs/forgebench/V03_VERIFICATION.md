# v0.3 development foundation: verification receipt

Checked September 23, 2026 (New York); remote receipt time
`2026-09-24T00:20:32Z`. These are software and fixture checks, **not model benchmark
results**. No new model calls, research scores or paid inference were created.

## Local checks

`python -m pytest -q`: **265 passed, 79 skipped, 5 subtests passed**. The two
warnings are existing Starlette/httpx/AnyIO deprecations. Opt-in container tests
are skipped locally because the local Docker daemon is unavailable. Focused
support-audit tests subsequently passed **12/12** after adding source metadata.
`git diff --check` passed.

Focused coverage includes visible-green → new public verification failure →
repair; candidate-hash invalidation; duplicate verification denial; two-call and
decision caps; equal access for four non-learned policies; sandbox unavailability;
final-only hidden grading; no hidden feedback; old-controller rejection; and
unchanged v0.2 visible-success stopping. The old catalog still hashes to:

`ccb6b8e3996e067e24ecfb4b2f14d6ffb543380b10acb7bcfbc4f19d6b6f116b`

## Actual isolated fixture validation

The existing curated executor on the portfolio VPS ran only the two new fixture
tests, under the `forgerl-api` identity through its restricted Unix socket:

```sh
cd /srv/forgerl/verify-v03-stage
runuser -u forgerl-api -- env \
  PYTHONPATH=/srv/forgerl/verify-v03-stage \
  PYTHONDONTWRITEBYTECODE=1 \
  FORGERL_EXECUTOR_SOCKET=/run/forgebench-executor/executor.sock \
  FORGERL_DOCKER_TESTS=1 \
  /srv/forgerl/app/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_bench_v03.py -k inside_real_isolated_sandbox
```

Result: **2 passed, 15 deselected in 6.06 seconds**, exit 0. Each starter actually
failed visible checks; each reference passed original visible, supplemental and
final hidden suites. Each deliberately incomplete patch passed original visible
checks and failed new supplemental checks. Candidate code executed only through
the existing rootless, networkless Docker boundary.

The first invocation reached two passing assertions but pytest could not restore
the caller's `/root` working directory after dropping privileges. Repeating with
the explicit accessible staging directory above completed with exit 0. No
application, executor service, frozen v0.2 source or published artifact was changed.
The staging copy is separate from every live service path.

Validated staged source SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `forgerl/bench/v03.py` | `b1abd1ba6b689b4213f495c872fb5071a8e7419db1464a249977ab9ce373de03` |
| `forgerl/bench/engine.py` | `e947514a25ca3024202e70f9de71b003fd90c675f72ab7b542a2311004aa13ae` |
| `tests/test_bench_v03.py` | `dd49c891ceb3aaa32d0fd7e992ed22ec82046bc8571d8e795597715603cb23dc` |

## Historical training-support audit

`scripts/audit_training_support.py` analyzed only training `transitions.jsonl` and
`manifest.json` from seeds 17, 29 and 43. The separate
[audit JSON](v03-training-support.json) preserves their hashes/source IDs and
reports 200 transitions, 30 tasks, six families, 12 encoded states, 21 observed
state/action pairs and **200 missing behavior propensities**. No policy was
trained, no evaluation trajectories were read and no old report was overwritten.

Tests reject validation/test rows, test task IDs falsely labeled train, extra
hidden state fields, invalid propensity values, duplicate seeds and inconsistent
manifest counts. Strict propensity checking rejects these historical logs;
ordinary observational/supervised fitting remains possible but is not a causal
or off-policy performance estimate and requires fresh prospective evaluation.
