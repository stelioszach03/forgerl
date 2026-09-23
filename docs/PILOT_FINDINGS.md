# ForgeRL pilot findings

**Interim interpretation.** The aggregate inspected for this draft is marked `partial`: seeds 17 and 29 are complete, and seed 43 is still being collected. This document will receive its final comparison table only after all predeclared studies have been imported. Current measurements, coverage and raw-run references remain in [the benchmark artifact](../artifacts/benchmark.json).

This is an evaluation of a bounded repair system and a small learned controller. It does not demonstrate a generally superior coding agent, language-model fine-tuning, or a validated world model. Negative controller results remain part of the project evidence.

## How to read the comparison

The study uses six unique held-out tasks from two families. Three requested seed replicates produce at most 18 evaluation episodes per policy; they do not create 18 independent tasks. Each seed has its own fitted controller, while deployment retains the predeclared seed-17 artifact. Aggregate adaptive results therefore describe the repeated training/evaluation procedure, not 18 evaluations of one production artifact.

Each policy sees the same task specification and visible tests and receives the same three-request cap. Fixed fast and deliberate-only are allowed to stop once visible tests pass. Actual spending and request counts differ. New provider samples were generated for each policy rather than selecting favorable training-tree branches.

Read held-out success together with estimated cost. Lower cost obtained alongside lower correctness is a trade-off, not evidence that the system preserves quality while saving compute. Provider wall time also includes service/network effects; it is not GPU utilization or a controlled hardware-throughput comparison. The project reports conservative token-rate cost estimates, not invoices.

No ordinary binomial interval is applied to repeated episodes as if all were independent. Two held-out families are too few for a meaningful family-cluster interval. Broad superiority claims, causal attribution and population-level guarantees are unsupported.

## What the inspected traces show

These observations come from the completed seed-17/29 raw traces and can be checked by task ID, seed and policy. They are not selected as a replacement benchmark; the aggregate retains every prospective outcome, including unsuccessful patches.

**Visible success can hide a regression.** On `graph-topological` and `calendar-business-days`, inspected short-configuration and adaptive episodes stopped after passing visible checks while failing held-out checks. The scaffold's common visible-success stopping rule terminated these episodes. This is not evidence that the learned controller independently chose to stop after observing hidden failure: it never received that hidden result as feedback.

**A learned early stop can leave a task unresolved.** In the seed-29 `calendar-month-shift` adaptive trace, the controller chose `stop` after an unsuccessful first patch. Other policies solved their independent episodes for the same task/seed. That comparison does not establish that continuing the exact adaptive branch would have succeeded; that counterfactual was not evaluated prospectively.

**Some adaptive behavior is a fallback.** The inspected `graph-components` adaptive traces used a learned first action and a heuristic second action at a state without supported learned actions. The decision events identify `learned_q` and `heuristic_fallback`. A successful full episode should not be attributed entirely to learned decisions when part of its trajectory used the fallback.

The final summary must retain separate task failures and provider/execution failures. A completed but incorrect patch is an unsuccessful task outcome, not an infrastructure outage. Likewise, a service failure cannot be hidden by removing the corresponding attempted episode from the denominator.

## Plausible explanations to test next

The following are hypotheses, not findings from a causal experiment:

- **State aliasing.** The controller discretizes public-test progress, budget, attempt count and previous action. Different programs can share the same encoded state while requiring different repair strategies. The training artifact makes the initial routing decision from these coarse observable categories. Adding carefully bounded failure-type or program-structure features might improve separation; this pilot has not tested that intervention.
- **Sparse transfer between defect families.** Training and test families are deliberately disjoint. A small observed transition table may cover too little of the state/action behavior encountered on graphs or calendar arithmetic. More independently authored families and broader training coverage could test this explanation without memorizing task IDs.
- **Limited stopping feedback.** Visible success is an automatic terminal condition for every policy. The design exposes cases where that signal is insufficient, but does not let a controller request additional verification after visible success. A new protocol could compare an explicit verification action and a separately defined terminal rule. That change must not be retroactively applied to this study.
- **Reward and model configuration trade-offs.** The cost penalty, short horizon and two model/request configurations may favor inexpensive actions that do not generalize. A future preregistered ablation could vary those factors separately. The current results cannot identify which factor caused a performance difference.

These follow-ups require a new versioned experiment and fresh evaluation tasks. Altering the controller, reward, task data or hyperparameters after reading this pilot's test outcomes would not be an unbiased improvement to the existing result.

## Product choice and research record

The planned public interface offers deliberate-only as a practical default based on the pilot observations, while retaining the baseline, heuristic and learned options for inspection. This is an explicitly post-evaluation product choice, not a change to the predeclared study or proof of general default-policy superiority. A new independent evaluation would be needed to assess the selected default beyond this pilot.

The adaptive artifact remains seed 17, as chosen before evaluation. No higher-scoring seed is substituted. Changing the visitor's default selection does not change the saved controllers, recorded requests, failures or benchmark denominators.

## Evidence and reproducibility

See [methodology](METHODOLOGY.md) for the frozen collection/evaluation protocol, [seed-17 evidence](../artifacts/studies/seed17/raw-runs.jsonl), [seed-29 evidence](../artifacts/studies/seed29/raw-runs.jsonl), and [the aggregate provenance](../artifacts/benchmark.json) for manifest/controller hashes and coverage. Smoke checks are development observations and are excluded from the benchmark.

The final release interpretation should report all predeclared seeds and keep the unsuccessful controller outcomes visible. The project's defensible contribution is an inspectable implementation, a bounded real experiment and a reproducible account of what worked and what did not on the authored suite.
