# ForgeBench v0.3 implementation backlog

**Status update, September 24, 2026:** this is the original broad research plan,
not a list of prerequisites still blocking the recruiter demo. The separately
frozen [prospective transfer pilot](V03_PILOT_PROTOCOL.md) is complete: 162 real
episodes, six policies, eight new authored families and one licensed
source-derived family. It includes shared VERIFY, a train-only supervised
observed-return baseline, frozen provenance, actual analysis and a technical
report. The native versioned explorer now presents that evidence alongside v0.2,
with three test stages, recorded replay, downloads and separate samples; see
[recruiter serving and optional bounded trial](../RECRUITER_DEMO.md).

The pilot implements bounded versions of F03-01–08 and F03-11–12. It does **not**
complete adaptive learned verification, real upstream issue evaluation,
multi-seed external validation, causal/off-policy claims, the predeclared
ablations in F03-09, independent human failure annotation in F03-10, or a reviewed
research publication. The original estimates below are historical planning
ranges for that wider program and must not be reused as remaining-demo effort.

Effort ranges are engineering estimates, not wall-clock promises or permission to
spend. Evidence and acceptance gates take precedence over a target release date.
The current release is v0.2.1; its completed v0.2 evidence is already published.

| ID / priority | Work and current anchors | Dependencies | Acceptance and evidence | Effort |
| --- | --- | --- | --- | --- |
| F03-01 / P0 | Versioned catalog/experiment schema. `bench/tasks.py`, `bench/study.py:plan`, `scripts/aggregate_forgebench.py:_configuration_signature` currently assume v0.2 / five variants / five policies. | None | Separate v0.3 schema, protocol and feature version; frozen v0.2 hash remains `ccb6b8e…b6f116b`; aggregation refuses mixed versions/actions/providers and old controller reuse. Development namespace exists, production schema still pending. | 1–2 days |
| F03-02 / P0 | Expand independent families, not renamed variants. `bench/catalog/*`, `tests/test_bench_tasks.py`. | F03-01 | Target 18–25 substantively distinct families; reserve at least six new test families; provenance and dependency/near-duplicate review; each starter fails, each reference passes all suites in real Docker. Existing inspected test families count as development evidence in the next study. | 4–8 days |
| F03-03 / P0 | External-track source and redistribution gate. `RepoTask` currently has no upstream revision/license fields; all v0.2 fixtures are authored MIT. | F03-01 | Inventory immutable upstream repo/commit/issue references, source/test licenses, provenance of each patch, attribution and permitted redistribution; reject unclear licenses. Predeclare inclusion/exclusion before model runs; report selection bias and contamination risk. Do not claim a named external benchmark unless its actual protocol is followed. | 1–2 days |
| F03-04 / P1 | Bounded external-task adapter. Current `bench/sandbox.py` only allows eight flat pure-Python modules/40KB and no dependencies/network. | F03-03 | Import a small licensed subset compatible with that boundary, or separately design a reviewed executor rather than silently weakening it. Reproducible pinned inputs, failing reproduction, passing reference, hidden-final grading, no host execution; report how subset restrictions limit external generalization. | 2–4 days |
| F03-05 / P0 | VERIFY semantics and information boundary. `bench/v03.py` foundation and `tests/test_bench_v03.py` now exist. | F03-01 | Two development examples prove visible-green → supplemental-fail → repair; candidate hash + total cap; real isolated verification, counted decision/tool/time; same success rule across policies. Extend to the frozen catalog with no hidden inputs/results in feedback; audit author correlation and supplementary/hidden overlap. | Foundation implemented; 1–2 days to expand/audit |
| F03-06 / P1 | Train a simpler learned cost-sensitive policy beside fitted-Q. `bench/router.py:fit_q`, `bench/study.py` training transitions. A descriptive support audit is implemented; no policy is fitted. | F03-02, F03-05 | Same observable features/action set, train-only data, logged action probabilities/support, explicit unsupported-state fallback, frozen artifact digest; never fabricate counterfactual labels. Test deterministic fit/reload and unseen state behavior; report calibration/support and complexity. Missing historical propensity blocks importance-weighted off-policy claims, not ordinary supervised fitting. | 2–3 days |
| F03-07 / P0 | Freeze prospective study and budget. `docs/forgebench/V03_DRAFT.md`, `bench/study.py:plan`, durable `CappedProvider`. | F03-02–06 | Timestamped committed protocol before evaluation: hypotheses/estimands, fresh split, policy matrix, seeds/order, retry rules, equal action budgets, cost weight, provider/quantization, hashes, stop rules, missingness and multiplicity. CLI dry-run predicts complete matrix and worst-case spend without credentials. Draft must not be called preregistered. | 1 day |
| F03-08 / P1 | Measure verification value and small-sample uncertainty. `aggregate_forgebench.py:family_bootstrap`, `bench/study.py:summarize`. | F03-07 | Compare success/cost at family level; preserve provider failures in primary denominator and report a clearly secondary graded-only view. Record verification rate, incremental caught failures, repaired-after-verify, grader disagreement, extra tool/time and benefit per call; no broad claim just because six clusters exist. | 1–2 days |
| F03-09 / P1 | Predeclared ablations. Current policies share automatic visible-success stopping. | F03-06–08 | Budget-matched no-VERIFY, verify-on-green, adaptive verification, no-escalation and learned-vs-fallback comparisons selected before test; identical available observations and fair comparison budgets. Distinguish compute-for-verification from routing effects. | 1–2 days + bounded runs |
| F03-10 / P1 | Annotated failure analysis. Existing labels are observed proxies only. `engine.py:record_failure`, `failure_analysis.csv`. | F03-07 | Written annotation rubric, blinded independent review of a fixed stratified sample, agreement/adjudication record; localization/planning/context-loss remain unassigned when evidence insufficient. Never infer private chain of thought. | 1–2 days |
| F03-11 / P1 | Reproducible artifacts and read-only UI for v0.3. `bench/api.py`, `static/bench.*`, `scripts/report_forgebench.py`. | F03-08–10 | Version selector preserves v0.1/v0.2; distinguish original-visible/supplemental/final-hidden events and missing values; export provenance; report totals reconcile to immutable traces; mobile/accessibility checks; old URLs work; no public paid run path. | 1–2 days |
| F03-12 / P2 | Research report/preprint decision and maintenance. `MAINTENANCE.md`, versioned reports/releases. | F03-11 | All predeclared outcomes/negative findings and limitations reported, artifact hashes verified, PDF visually checked; preprint title/claims match actual study and receive author review. No publication/acceptance claim until it happens, no fabricated monthly activity. | 1–2 days |

Execution order: schema and task/source review → expanded fixtures plus VERIFY →
simple learned baseline → freeze protocol → bounded experiments → analysis and
release. Documentation/presentation work must not disguise an incomplete study.
