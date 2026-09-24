# ForgeBench v0.3 prospective transfer pilot

**Draft pending review and an immutable freeze commit. No pilot model calls yet.**
This is a small pilot, not completion of the full v0.3 research backlog. Published
v0.2 source/data/results stay unchanged. All pilot outcomes, including negative
results and infrastructure failures, must be reported.

## Question and scope

Does historical train-only learned routing transfer to new miniature repository
families when every policy has the same additional verification rule? Compare
the existing fitted-Q method with a simpler supervised observed-return baseline,
strong-only, cheap-only, escalate-on-failure, and the hand-written router.

This does **not** test learned verification: the historical transitions contain
zero VERIFY actions. Every policy deterministically verifies a visible-green
candidate before stopping, once per immutable candidate, at most twice per run.
Supplemental failure can trigger repair/escalation. No hidden result is observed
until all decisions finish. Same original-visible + final-hidden success rule for
every policy; supplemental/grader disagreement is separately reported.

## Catalog and provenance

The original 50 tasks / 10 families are already inspected development material.
They are never called fresh holdout data. Fitting reads **only** original train
transitions (30 tasks / six families) from seeds 17, 29, and 43, not the old
validation/test trajectories. Six of the 10 development families therefore have
historical fitted data; the other four have no fitted labels.

New authored families each have three two-module repair variants:

| Split | Families | Tasks |
| --- | --- | --- |
| Validation, reporting only | binary protocol, geospatial overlap | 6 |
| Test, primary pilot evidence | graph dependencies, exact apportionment, interpolation, tabular joins, expression evaluation, edit distance | 18 |
| External source-derived, descriptive only | Boltons mathematical clipping/rounding | 3 |

Thus there are 18 authored families across previous development and fresh splits,
plus one separately reported source-derived family. Variants within a family
share a specification and are not independent clusters. Programs are compact,
pure Python with authored faults, not production repository issues or evidence
of hours-long autonomous coding. AI assisted their source, faults, and checks;
supplemental and final graders are not independently authored.

Each new task has original visible, two additional public, and 4–6 final withheld
cases with distinct request inputs. Reference implementations must pass every
suite in the existing isolated executor; every starter must fail original visible
checks. Two changed reference-scope modules are required for each task. These
checks confirm fixture consistency, not exhaustive correctness.

The source-derived track extracts actual `clamp`, `ceil`, `floor` function bodies
from [Boltons mathutils at immutable revision
4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d](https://github.com/mahmoud/boltons/blob/4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d/boltons/mathutils.py).
The [BSD-3-Clause license](https://github.com/mahmoud/boltons/blob/4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d/LICENSE)
permits redistribution with retained notices; original copyright, conditions and
disclaimer are embedded in the extracted source and the vendored JSON snapshot.
Imports are reconstructed in a flat module; the JSON adapter, faults and checks
are new. No upstream tests are copied. `Bits`, `binascii`, and unsupported
constructs are excluded without broadening executor permissions. This track is
not SWE-bench, a historical bug issue, upstream endorsement, or a complete run of
the upstream test suite. Public-source contamination is unknown.

## Training, support and policy freeze

Both learned methods use the exact validated, completed historical **training**
transitions. Historical infrastructure-failed training episodes supply no labels
and remain in their original archive. State/action support and this selection
bias are disclosed. Behavior probabilities were not logged; there is no
importance-weighted or causal off-policy evaluation claim.

Fitted-Q is fitted with gamma=0.9, 100 iterations, minimum 12 transitions, using
the original state encoder and legal action masks. The simpler baseline groups
actually observed state/actions and regresses the mean realized discounted
return, working backwards through each completed training episode. The logged
reward is terminal actual task success minus five times that action's accounted
API cost; future rewards discount by 0.9. It has no Bellman bootstrapping, model
training, invented reward, unchosen-action label, hyperparameter search, or
validation selection. Unsupported states/actions fall back explicitly to the
same hand-written policy. Ties follow the fixed original action order.

The original $1 per-episode cap is retained because the historic state encoding
bins remaining dollars at $0.25; shrinking it to $0.05 would manufacture unseen
states for all initial decisions. An **independent $1 total pilot limit** still
preflights every reservation through the original durable research ledger.
VERIFY is never selected by either trained artifact. When a supplemental failure
exists, the routing signal combines its observed pass count with the original
visible count. This changes observation coverage, so report supported learned
versus fallback decisions; do not claim the old controller learned new signals.

## Fixed execution

One requested seed: **17**. All 27 tasks × six policies = **162 episodes**:
108 primary test, 36 validation, 18 source-derived external. Validation is reported
without model/policy selection. Task order is lexicographic; per-task policy order
is deterministically shuffled from seed 17 + the first eight hexadecimal digits
of SHA256(task_id). Full order is recorded in the frozen JSON plan.

OpenRouter GPT-OSS-20B and GPT-OSS-120B, pinned `coreweave/fp4`, no fallback;
temperature 0.2, max output 4,096 tokens for both. Requested seeds are not a
determinism guarantee. A public endpoint-catalog GET snapshot confirms advertised
availability and supported settings without an inference preflight. Hosted
checkpoint revisions remain unavailable; this is not self-hosted reproducibility.

Equal policy caps: six actual provider requests (including HTTP 429 retries), ten
routing decisions, 100,000 tokens (unknown usage conservatively bounded), two
supplemental verifications, two retry actions, one rollback, $1 per episode.
Existing bounded HTTP 429 retry protocol: at most two retries, 30/60 second delay,
respect Retry-After up to 60 seconds, stop rather than retry early if longer.
Same pinned provider/model, no selective successful replacements. A retained
unknown-charge reservation is labeled accounted cost, not a confirmed invoice.

The total study hard cap is **$1**, additionally subject to existing research,
global and provider-key limits, with no reset. No public inference endpoint or
GPU is used. A ledger flock prevents overlapping Forge studies. Each run/event
is durable and any missing matrix entries are recorded if execution stops.

## Prespecified analysis

Primary estimands are equally family-weighted (six fresh authored test families)
task success and accounted API cost per attempted episode. Within family, average
the three task variants. Show per-task outcomes and paired per-family differences
for learned methods versus each baseline, plus all six success/cost points.
Report all comparisons without selecting a favorable winner. This single-seed,
six-cluster pilot is descriptive: no population confidence intervals or
statistical significance claims. The external family and two validation families
are separate descriptive tables, never pooled into the primary sample.

Primary denominator retains attempted provider/infrastructure failures as
unsolved. Provide a clearly secondary graded-only view conditional on successful
infrastructure, not a replacement headline. Unattempted budget-stop cells are
missing; report coverage rather than calling them model failures. No outcome-based
exclusions, retries beyond the fixed protocol, reruns, or post-hoc tuning.

Secondary metrics: hidden-test pass fraction among graded episodes, accounted
cost and confirmed-charge coverage, tokens with measurement coverage, total
latency, tool calls, requests, regressions, reference-scope unnecessary-edit
proxy, escalation/repair rates, verification usage and CPU time, visible-green
candidates caught by supplemental checks, success after such a failure, final
grader disagreement, learned-action and explicit fallback coverage. These are
observed metrics, not private reasoning or causal failure diagnoses.

Verifier/grader disagreement is bidirectional for the final candidate: a passed
supplemental suite followed by final failure is `missed_failure`; supplemental
failure followed by final success is `false_rejection`. If either signal is
unmeasured (including failed final infrastructure), disagreement is null, not
false. Both directions and the measured denominator are reported.

## Freeze gates and commands

Before any paid call: inspect all 27 fixture contracts, pass actual rootless
Docker reference/starter checks, fit and hash historical train-only artifacts,
review this protocol, record source/catalog/provider/container hashes, commit
the code and then commit the separately generated timestamped freeze artifact.
The execution CLI rejects a changed runtime, catalog, configuration or controller.

```sh
python scripts/pilot_forgebench.py  # plan only, no credentials or paid path
python scripts/pilot_forgebench.py --fit-controllers \
  --training-root artifacts/forgebench/studies --output /new/controllers.json
FORGERL_EXECUTOR_SOCKET=/run/forgebench-executor/executor.sock \
python scripts/pilot_forgebench.py --verify-fixtures --output /new/fixtures.json
# Only after reviewed source commit and real fixture receipt:
python scripts/pilot_forgebench.py --freeze --source-commit FULL_COMMIT_SHA \
  --controllers /new/controllers.json --fixture-receipt /new/fixtures.json \
  --provider-snapshot docs/forgebench/v03-pilot-provider-snapshot.json \
  --output /new/frozen-protocol.json
# Only from that exact frozen runtime, using the original existing ledger:
python scripts/pilot_forgebench.py --execute-research \
  --frozen-protocol /new/frozen-protocol.json \
  --db /var/lib/forgerl/forgerl.sqlite3 --output /new/immutable-run-directory
```

Remaining full v0.3 work includes broader external real-issue compatibility,
prospective exploratory training with logged propensities and VERIFY support,
budget-matched verification ablations, more seeds, independently reviewed failure
annotations and a report that does not overstate pilot generalization.
