# ForgeBench v0.3 development draft

**Status: development only, not preregistered, not frozen, no v0.3 model experiments.**
The released v0.2 dataset remains 300 evaluation and 180 training episodes. The
v0.2.1 software release changes rate-limit handling for future runs; it does not
replace old results. Nothing in this document establishes a positive routing result.

Research question: when does adaptive routing add value over simple routing, and
when is additional verification more useful than escalating to a larger model?

## Implemented foundation

`forgerl/bench/v03.py` is an opt-in harness with two **development fixtures**, signed
temperature conversion and Unicode identifier deduplication. They are neither a
new 50-task catalog nor an evaluation split. Existing v0.2 tasks, catalog hash,
stopping rules and published artifacts are unchanged. The public dashboard still
serves the released v0.2 evidence and cannot run inference.

The additional `verify` action runs a separate supplemental public suite inside
the existing isolated executor. The suite is authored from the task specification;
it does not reuse original visible or hidden inputs. Its definitions are public in
source, and its inputs/expected values/results become feedback when the action is
invoked. The task authors also authored these checks: additional coverage is not
independent-author evidence or an unbiased oracle. This is not a second hidden
grader and not simply rerunning unchanged original tests.

A successful original visible suite no longer forces a v0.3 stop. A policy can
verify, then repair or escalate from the supplemental failure. Every candidate is
identified by its source hash. A candidate can be verified once, at most twice per
episode; restoring a prior candidate reuses only that candidate's recorded signal.
Verification consumes one routing decision and one real sandbox call, preserves
the existing model/cost/token caps, and records its duration and candidate hash.
Its model API cost is zero; local CPU time is measured but not converted into a
fictitious dollar figure. Changed candidates invalidate stale feedback.

Original visible tests plus the final hidden grader define success for **all**
policies. Supplemental failures are a separate metric; a disagreement with final
success is exposed. Making success depend on whether a policy invoked an optional
verifier would bias comparisons. Hidden grading still runs once after the full
routing sequence has ended, and hidden cases, scores and reference patches never
enter router state or provider feedback. Final failure cannot trigger another repair.

The development runner can use the four existing non-learned routing policies;
each has equal verifier access and budgets. Its default heuristic verifies a green
candidate, then uses the existing hand-written router. The old fitted-Q artifact
is rejected. No new learned policy, learned verification result or v0.3 performance
advantage is claimed.

```sh
python scripts/plan_forgebench_v03.py
python -m pytest -q tests/test_bench_v03.py tests/test_bench_engine.py
# Requires the existing, rebuilt rootless Docker sandbox:
FORGERL_DOCKER_TESTS=1 python -m pytest -q tests/test_bench_v03.py
```

The plan command has no execution switch, loads no credentials and makes no model
calls. Mocked transition tests are software checks, not research results. Real
container tests are opt-in; a skipped container check is not a verified fixture.
The [verification receipt](V03_VERIFICATION.md) records the passing local suite
and actual rootless-Docker checks of both new fixtures.

## Required before preregistration

Freeze a distinct v0.3 task manifest, new holdout families, public verifier suites,
external-source licenses and immutable revisions, policy implementations, source
and container hashes, model/provider/quantization configuration, study order,
seeds, retry protocol, identical policy budgets, and a finite spend ceiling.

Predeclare the primary estimands (success and accounted cost), cluster unit,
provider-failure handling, secondary verification metrics, exclusions, stopping
rules, comparison multiplicity and missing-run handling. Proposed verifier
comparisons must give every policy the same available observations, actions and
budgets, with policy-specific use allowed. Never tune on v0.2's already inspected
test families and describe them as fresh held-out evidence.

The smaller learned baseline is planned as a cost-sensitive contextual policy
using only observable state. Training must record exploration probabilities and
action support; unchosen actions are not labeled as failures. Training-only labels
may use terminal correctness after decisions, but no evaluation outcome may fit,
select or refit a policy. Any validation-based choice and hyperparameter search
must be declared before touching a fresh test split.

The [preserved-training support audit](v03-training-support.json) reads only the
three v0.2 training transition files and their manifests: 200 transitions from 30
training tasks in six families, 12 encoded states and 21 observed state/action
pairs out of 41 legal pairs in those observed bins. Six bins contain only one
observed action. None of the 200 rows logged a behavior action probability.
Missing propensities prevent supported importance-weighted off-policy claims from
these logs; they do not prohibit ordinary supervised/observational fitting. No
new policy was fitted or evaluated. The logs contain transitions from completed
graded training episodes only; failed training episodes remain in the original
archive. Input hashes and this selection boundary are retained in the audit.

```sh
python scripts/audit_training_support.py \
  --study 17=artifacts/forgebench/studies/seed17 \
  --study 29=artifacts/forgebench/studies/seed29 \
  --study 43=artifacts/forgebench/studies/seed43
```

Adding `--require-propensity` intentionally fails on those historical inputs.
The command does not read validation/test run files, keys or model APIs, and its
output goes to stdout. The original study artifacts and report are unchanged.

The frozen protocol will be a separate committed artifact after the following
[implementation backlog](V03_BACKLOG.md) is resolved. This draft is not that
artifact. A preprint remains conditional on sufficient evidence and review.
