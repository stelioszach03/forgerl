# Exposed-catalog replication and VERIFY ablation

Prepared24September2026. This is a new finite experiment on previously inspected and published v0.3 tasks. It is not a fresh holdout, real-upstream-issue benchmark, a trained verification policy or a pooled extension of the old pilot. No model outcomes have been observed for this new run at protocol preparation.

## Question and matrix

Does the shared supplemental VERIFY intervention change task success, failure detection and cost across six fixed routing policies on this exposed catalog, and how variable are the observations across requested seeds?

Use the unchanged27tasks (18original primary test,6original validation,3licensed source-derived mutations), six original policies, seeds31/47/73/101 and two conditions: shared verify-on-visible-green versus no supplemental verification. The matrix is27×6×4×2=1,296episodes. Each policy/condition pair has the same original inputs, public checks, final grader and provider. Previously observed outcomes are never included as these new repetitions.

Historical fitted-Q and supervised-return controllers are copied byte-for-byte from the frozen original training-only artifacts; no fitting or tuning uses these outcomes. All language-model weights remain unchanged. No-VERIFY terminates on original visible success and cannot invoke or receive supplemental checks. VERIFY follows the existing shared rule, up to two candidate-specific checks. Final hidden grading happens once after routing stops in both conditions. Missing hidden grading is missing, not a failed or passed hidden test.

Both conditions have six actual model requests (including the existing at-most-two bounded429retries), ten decision steps,100,000conservatively bounded tokens and the original$1episode cap required by historical state bins. VERIFY consumes actual decisions/tool time. Maximum resource ceilings are matched, not actual resource usage. Provider is unchanged GPT-OSS20B/120B through coreweave/fp4, fallback disabled, temperature0.2,4,096output tokens. Requested seeds are not a guarantee of provider determinism or independence.

Within each seed/task, shuffle the twelve policy/condition combinations using the documented deterministic seed+task hash; freeze the complete order. Time/order and shared provider load can still confound results. Keep the original validation and source-derived samples separate from the primary family slice.

## Finite cost and execution

A timestamped JSON freeze contains all evaluated source hashes, committed source revision, task/controller hashes, existing validated rootless-Docker fixture receipt/image and a fresh public provider-endpoint snapshot. Before execution the driver verifies source/config/task/image identity. This additional run shares the existing durable ledger and exclusive Forge study lock, with a$3study cap and eight-hour wall limit. It never resets any research/global/provider-key limit or changes the public trial budget. Public trial spending is conservatively included in the study ledger delta; exact per-call charges also remain in trajectories.

Run in a separate protected VPS working directory with the existing private executor and model credential. Generated candidate code runs only in the existing constrained rootless container. Original studies/public service files are not replaced. The driver requires a new output directory; there is no automatic paid retry/restart of an uncertain interrupted study. Every active cell ID is durable before execution, with streamed events and completed run files. On interruption, planned missing cells and the active identity remain in the manifest, without inventing final outcomes. A supervisor independently limits wall time and the three-hour monitor inspects progress.

The plan is not a promise that all cells fit a worst-case allowance. Budget/provider/infrastructure stops remain explicit; unused cells do not become failures. Successful-looking outcomes never trigger selective repeats.

## Analysis fixed before calls

Report all six policies, both conditions and all four requested seeds. Within each original primary family, average its three related variants for each seed/condition; report paired VERIFY-minus-control changes in task success and accounted API cost. Then report equally family-weighted summaries and per-seed ranges. Preserve family and individual task tables; do not treat1,296 correlated episodes as1,296 independent tasks. No population significance or broad superiority claim follows from six exposed primary families and requested model seeds.

Report actual hidden-test pass fractions and coverage, model calls/tokens/cost coverage, latency, verification count/CPU time, caught visible-green failures, repaired-after-verification and supplemental/final-grader disagreement. Report both positive and negative directions, every infrastructure failure and every missing design cell. Provide graded-only sensitivity clearly conditional on infrastructure success, not as a replacement primary denominator. No private reasoning inference or unsupported failure taxonomy labels.

A separate future external track requires its own licensed sources, sandbox review and prospective freeze; this replication cannot establish external generalization.
