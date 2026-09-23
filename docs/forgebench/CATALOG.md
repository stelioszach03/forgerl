# ForgeBench v0.2 catalog

ForgeBench contains **50 authored task scenarios across 10 miniature Python repository families**. Each family has five related variants; these are not 50 independent production repositories. The fixtures use two or three linked, flat modules and deterministic JSON inputs/outputs. They exercise practical contracts without installing dependencies, accessing a network, or executing arbitrary uploaded projects.

## Fixed split and scope

| Split | Families | Tasks |
| --- | --- | ---: |
| Train | billing, scheduling, inventory, permissions, delivery, publishing | 30 |
| Validation | analytics, workflows | 10 |
| Test | search, federation | 10 |

Families never cross splits. Variants share code and a reference solution within a family, so statistical analyses must account for this clustering. A task-level interval alone does not establish independence across the five variants. The split is declared before model experiments on this version; no claim of freedom from model pretraining contamination is made.

Categories are assigned to the primary maintenance scenario. Tasks can also require changes in several files. The catalog contains 10 bug_fix, 9 failing_tests, 10 feature, 10 long_horizon, 6 multi_file, 5 refactor.

`long_horizon` denotes an integrated **miniature multi-requirement stress task**: several interacting invariants must be recovered across modules. It is not evidence of hours-long autonomous work, industrial long-horizon capability, or real repository-scale issue resolution. Refactoring cases grade observable compatibility and consistency across facades; they do not prove improved architecture or enforce a particular helper layout.

## Success and evaluation boundary

Every task has an explicit behavioral specification, an intentionally faulty starter, a complete trusted reference, at least two visible checks, and at least four hidden edge/regression checks. Success requires passing both groups and respecting editable-file boundaries. The reference is used to validate authored fixtures, never as an agent input. A starter must fail at least one visible check. The same sandbox evaluates both the reference and model candidates.

This revision defines 100 visible and 211 hidden checks. Hidden means withheld from the model prompt and public API during an episode. This open-source repository contains the trusted fixture definitions for reproducibility; they are not a permanently secret independent test set. A model or person inspecting the benchmark source outside the controlled runner can discover them. Published benchmark reuse and contamination must be disclosed.

Expected outputs remain in the trusted grader outside the container. The runner receives only source files, entrypoint, names and test inputs. Hidden inputs are sent only to the isolated grading execution after routing decisions end, never to the coding provider. Public serializers exclude both hidden cases and reference files.

Fixture authoring uses explicit source mutations checked for a unique match. Structural tests parse embedded code but never execute it on the host. Behavioral validation is opt-in and requires the rebuilt `repository-v2` sandbox image:

```sh
python -m pytest -q tests/test_bench_tasks.py
FORGERL_DOCKER_TESTS=1 python -m pytest -q tests/test_bench_tasks.py
```

The ordinary test run reports the Docker tests as skipped; that is not evidence that golden execution passed. A release should publish the actual sandbox-validation receipt. The real-sandbox test checks 50 references against both case groups and verifies 50 visible failing reproductions.

## Task index

| Task | Category | Title |
| --- | --- | --- |
| `billing-credit-order` | `bug_fix` | Apply account credit after tax |
| `billing-tax-rounding` | `feature` | Implement half-up tax rounding |
| `billing-shared-validation` | `refactor` | Unify validation across billing facades |
| `billing-coupon-idempotency` | `failing_tests` | Make coupon replay idempotent |
| `billing-checkout-recovery` | `long_horizon` | Recover an integrated checkout pipeline |
| `scheduling-adjacent-bookings` | `bug_fix` | Respect half-open booking boundaries |
| `scheduling-availability-union` | `feature` | Compute free windows from nested bookings |
| `scheduling-resource-scope` | `multi_file` | Restore booking scope across two APIs |
| `scheduling-reject-empty-slots` | `failing_tests` | Reject zero-width calendar intervals |
| `scheduling-calendar-recovery` | `long_horizon` | Recover a room-calendar migration |
| `inventory-event-replay` | `bug_fix` | Deduplicate warehouse event retries |
| `inventory-atomic-reservations` | `feature` | Allocate repeated SKU lines atomically |
| `inventory-stock-projection` | `multi_file` | Align ledger replay and replenishment |
| `inventory-shipment-regression` | `failing_tests` | Restore outbound inventory accounting |
| `inventory-warehouse-recovery` | `long_horizon` | Recover the warehouse fulfillment flow |
| `permissions-deny-precedence` | `bug_fix` | Enforce deny precedence in policy evaluation |
| `permissions-segment-wildcards` | `feature` | Implement exact-depth resource wildcards |
| `permissions-role-inheritance` | `failing_tests` | Resolve inherited roles with cycle checks |
| `permissions-safe-export` | `multi_file` | Align tenant filtering and field projection |
| `permissions-policy-migration` | `long_horizon` | Recover a multi-tenant access-policy migration |
| `delivery-backoff-index` | `bug_fix` | Correct the first retry backoff |
| `delivery-rate-limit-retries` | `feature` | Implement rate-limit response scheduling |
| `delivery-queue-ordering` | `failing_tests` | Preserve due-time priority at the scheduling boundary |
| `delivery-idempotent-selection` | `refactor` | Centralize idempotent delivery selection |
| `delivery-delivery-recovery` | `long_horizon` | Recover webhook scheduling after a queue migration |
| `publishing-text-escaping` | `bug_fix` | Avoid double-escaping rendered CMS text |
| `publishing-partial-translations` | `feature` | Support intentionally empty localized fields |
| `publishing-feed-continuation` | `multi_file` | Publish scheduled posts with exclusive cursors |
| `publishing-shared-excerpts` | `refactor` | Normalize excerpt behavior across CMS facades |
| `publishing-cms-release` | `long_horizon` | Recover the CMS publishing and rendering pipeline |
| `analytics-window-boundary` | `bug_fix` | Prevent double-counting adjacent reporting windows |
| `analytics-partial-buckets` | `feature` | Include the final partial reporting bucket |
| `analytics-deduplicated-means` | `multi_file` | Align ingestion and fractional aggregations |
| `analytics-quantile-index` | `failing_tests` | Repair endpoint-safe interpolated quantiles |
| `analytics-reporting-recovery` | `long_horizon` | Recover a consistent reporting pipeline |
| `workflows-cycle-validation` | `bug_fix` | Reject cyclic workflow definitions |
| `workflows-readiness-gates` | `feature` | Require every prerequisite before scheduling |
| `workflows-failure-propagation` | `failing_tests` | Propagate failure through the entire workflow DAG |
| `workflows-canonical-order` | `refactor` | Restore deterministic coordinator ordering |
| `workflows-coordinator-recovery` | `long_horizon` | Recover workflow validation and execution readiness |
| `search-case-normalization` | `bug_fix` | Normalize document and query token case |
| `search-frequency-ranking` | `multi_file` | Implement frequency-aware deduplicated scoring |
| `search-label-semantics` | `feature` | Add conjunctive label filters and document facets |
| `search-ranked-pagination` | `failing_tests` | Preserve ranking across nonzero-offset pages |
| `search-search-release` | `long_horizon` | Recover the document discovery pipeline |
| `federation-clock-components` | `bug_fix` | Compare the union of replica clock components |
| `federation-tombstone-policy` | `feature` | Resolve concurrent tombstones deterministically |
| `federation-clock-join` | `refactor` | Make replica clock joins idempotent |
| `federation-strict-frontier` | `failing_tests` | Keep equal-clock versions on the causal frontier |
| `federation-replica-recovery` | `long_horizon` | Recover deterministic offline replica reconciliation |

## Versioning and growth

Current fixture-manifest SHA-256:

`ccb6b8e3996e067e24ecfb4b2f14d6ffb543380b10acb7bcfbc4f19d6b6f116b`

The manifest covers starter sources, reference sources, all cases, requirements, identifiers and split membership. Changes to any fixture require a new hash and a release note; results from different hashes must not be silently pooled. v0.1 data remains a separate benchmark version.

To grow toward 200+ tasks, add substantively new repository families and maintenance scenarios, validate references and failing reproductions in the isolated executor, record provenance, and freeze the next evaluation split before fitting a router. Do not inflate coverage by renaming a task or copying a one-line defect into nominally separate repositories. Monthly additions and new results should be recorded only when actually implemented and evaluated.
