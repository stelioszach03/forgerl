# Changelog

## v0.3 transfer pilot — 24 September 2026

- Complete 162 prespecified episodes under a committed freeze: six policies, 24 fresh authored tasks and three separately reported BSD-licensed source-derived mutation tasks.
- Fit the existing Q method and a simpler observed-return baseline on historical training transitions only; keep the shared verification rule explicitly unlearned.
- Publish every trace, failure, accounted cost, reconciled analysis and a six-page technical report with scientific figures. Primary test successes: strong 16/18, cheap 15/18, escalation 16/18, hand-written 15/18, fitted-Q 16/18, supervised 17/18. One seed and six test families do not establish superiority.
- Preserve all-action metrics and add a clearly post-run diagnostic to distinguish terminal STOP bookkeeping from nonterminal learned/fallback selections.
- Keep v0.2 data and public explorer intact; link the new pilot report separately. This is a research pilot, not the full v0.3 agenda or a preprint submission.

## Earlier v0.3 development foundation

- Add an opt-in supplemental public verification action, with candidate-hash binding, per-candidate/episode limits and explicit tool/time accounting; final hidden grading remains separate.
- Add two development-only fixtures, focused tests, a no-inference plan command and an unfrozen protocol draft/backlog. No new model evaluations or performance claims.
- Preserve released v0.2 task fixtures, behavior and evidence; reject reuse of the old learned controller in the new development harness.
- Audit the preserved three-seed training transitions without fitting a model or reading evaluation outcomes; record observed action support and missing behavior propensities instead of inventing off-policy evidence.

## v0.2.1

- Clarify historical HTTP 429 failures, unmeasured tests and retained budget reserves in the run inspector.
- Allow outcome-independent navigation to the next recorded seed; keep every original failure and benchmark value unchanged.
- Add bounded rate-limit backoff for new studies with a distinct protocol, explicit request accounting and the existing cost/token/attempt limits.

## v0.2.0 — completed experiments

- Add ForgeBench: 50 authored scenarios across ten miniature repository families, with fixed 30/10/10 family-disjoint splits and real-Docker starter/reference verification.
- Extend isolated execution to linked in-memory modules; preserve the v0.1 runner path.
- Add five routing policies and retry, repair, escalation, rollback and stopping decisions.
- Record actual prompts, files, patches, checks, errors and model/provider accounting; fit controllers on training transitions only.
- Separate read-only public evidence serving from operator-run research.
- Add a responsive task/trajectory explorer, comparison table, cost/success view and reproducible CSV/JSONL/figure/report tooling.
- Complete 300 evaluation and 180 training episodes across predeclared seeds 17, 29 and 43, retaining failures and their accounting.

## v0.1.0 — 2026-09-23

- Publish the bounded single-module repair pilot: 24 authored tasks, four policies and three requested seeds.
- Collect 144 prospective validation/test episodes and preserve the negative learned-controller comparison (11/18 held-out successes versus 18/18 for deliberate-only).
- Deploy rootless isolated execution, durable finite inference accounting, trace inspection, CI and operational verification.
