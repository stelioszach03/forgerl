# ForgeRL pilot findings

**Completed three-seed pilot, 23 September 2026.** All predeclared studies—seeds 17, 29 and 43—have been imported, and [the aggregate](../artifacts/benchmark.json) is marked `complete`. It covers 18 evaluation episodes per policy on six unique held-out tasks from two families. The learned controller's 11/18 successes did not match deliberate-only's 18/18 on this small suite.

This is an evaluation of a bounded repair system and a small learned controller. It does not demonstrate a generally superior coding agent, language-model fine-tuning, or a validated world model. Negative controller results remain part of the project evidence.

## How to read the comparison

The study uses six unique held-out tasks from two families. Three requested seed replicates produced 18 evaluation episodes per policy; they do not create 18 independent tasks. Each seed has its own fitted controller, while deployment retains the predeclared seed-17 artifact. Aggregate adaptive results therefore describe the repeated training/evaluation procedure, not 18 evaluations of one production artifact.

Each policy sees the same task specification and visible tests and receives the same three-request cap. Fixed fast and deliberate-only are allowed to stop once visible tests pass. Actual spending and request counts differ. New provider samples were generated for each policy rather than selecting favorable training-tree branches.

Read held-out success together with estimated cost. Lower cost obtained alongside lower correctness is a trade-off, not evidence that the system preserves quality while saving compute. Provider wall time also includes service/network effects; it is not GPU utilization or a controlled hardware-throughput comparison. The project reports conservative token-rate cost estimates, not invoices.

No ordinary binomial interval is applied to repeated episodes as if all were independent. Two held-out families are too few for a meaningful family-cluster interval. Broad superiority claims, causal attribution and population-level guarantees are unsupported.

## Completed pilot results

The learned controller did not match the deliberate-only baseline on this suite. It used fewer requests on average, but the lower per-episode estimate accompanied fewer successful repairs. This does not establish quality-preserving compute savings or a general benefit from learned routing.

| Policy | Held-out successes | Mean requests | Mean estimated USD / episode | Estimated USD / success |
|---|---:|---:|---:|---:|
| Fixed short budget | 9/18 | 1.5000 | $0.0067678 | $0.0135356 |
| Deliberate only | 18/18 | 1.1667 | $0.0093450 | $0.0093450 |
| Heuristic routing | 12/18 | 1.3889 | $0.0075594 | $0.0113392 |
| Learned controller | 11/18 | 1.1111 | $0.0068406 | $0.0111936 |

All 72 held-out policy episodes completed without reported provider/execution failures, missing token accounting or budget exhaustion. Incorrect patches remain unsuccessful task outcomes. Deliberate-only passed all declared checks in its 18 episodes; this is a finite-suite observation, not 100% accuracy on arbitrary code or proof that every defect was eliminated.

Cost estimates and the training reward use a common conservative rate of $10 per million tokens for both endpoints. Runpod’s published Granite prices conflicted ($1 versus $10 per million tokens) when the protocol was set. The cost-per-success ranking therefore describes this configured proxy; a different billed Granite rate can change the economic ranking. Token counts and test outcomes remain separate measured quantities.

Displayed means are rounded from the artifact. Estimated USD per success includes the costs of unsuccessful episodes and divides total held-out evaluation cost by successful episodes. It excludes training collection and host-operation costs. The same calculation gives the learned controller a higher estimated cost per success than deliberate-only in this pilot, despite its lower cost per attempted episode.

Formal study accounting totals **$1.66204**: **$0.63321** for training-transition collection and **$1.02883** for validation/test evaluation across all three seeds. Development smokes and earlier cold-start/timeout reservations are separate. This is not a statement of total account spending or an invoice.

The adaptive seed-specific results were 4/6, 3/6 and 4/6 for seeds 17, 29 and 43 respectively. The production artifact remains seed 17; the combined 11/18 figure is not a claim about 18 trials of that single deployed policy.

## What the inspected traces show

These observations come from the completed raw traces and can be checked by task ID, seed and policy. They are not selected as a replacement benchmark; the aggregate retains every prospective outcome, including unsuccessful patches.

**Visible success can hide a regression.** On `graph-topological` and `calendar-business-days`, the seed-17/29 short-configuration and adaptive episodes stopped after passing visible checks while failing held-out checks. The scaffold's common visible-success stopping rule terminated these episodes. This is not evidence that the learned controller independently chose to stop after observing hidden failure: it never received that hidden result as feedback.

**A learned early stop can leave a task unresolved.** In the seed-29 `calendar-month-shift` adaptive trace, the controller chose `stop` after an unsuccessful first patch. The seed-43 adaptive trace also stopped after a failed first patch on that task, and on `graph-topological`. At least one comparison policy solved an independent episode for each of those task/seed pairs. That comparison does not establish that continuing the exact adaptive branch would have succeeded; that counterfactual was not evaluated prospectively.

**The failed patches contain inspectable defects.** In the seed-29 month-shift example, the candidate references `timedelta` without importing it; the visible test events report `NameError`. The business-days candidate rejects equal dates even though the specification requires zero. The topological candidate compares its output length with the number of dictionary keys, while the specification includes neighbor-only vertices. These observations come from source and test-event inspection, not a claim about why a model internally produced the mistakes.

**Some adaptive behavior is a fallback.** The seed-17/29 `graph-components` adaptive traces used a learned first action and a heuristic second action at a state without supported learned actions. The decision events identify `learned_q` and `heuristic_fallback`. A successful full episode should not be attributed entirely to learned decisions when part of its trajectory used the fallback.

The summary retains separate task failures and provider/execution failures. A completed but incorrect patch is an unsuccessful task outcome, not an infrastructure outage. Likewise, a service failure cannot be hidden by removing the corresponding attempted episode from the denominator.

## Plausible explanations to test next

The following are hypotheses, not findings from a causal experiment:

- **State aliasing.** The controller discretizes public-test progress, budget, attempt count and previous action. Different programs can share the same encoded state while requiring different repair strategies. The training artifact makes the initial routing decision from these coarse observable categories. Adding carefully bounded failure-type or program-structure features might improve separation; this pilot has not tested that intervention.
- **Sparse transfer between defect families.** Training and test families are deliberately disjoint. A small observed transition table may cover too little of the state/action behavior encountered on graphs or calendar arithmetic. More independently authored families and broader training coverage could test this explanation without memorizing task IDs.
- **Limited stopping feedback.** Visible success is an automatic terminal condition for every policy. The design exposes cases where that signal is insufficient, but does not let a controller request additional verification after visible success. A new protocol could compare an explicit verification action and a separately defined terminal rule. That change must not be retroactively applied to this study.
- **Reward and model configuration trade-offs.** The cost penalty, short horizon and two model/request configurations may favor inexpensive actions that do not generalize. A future preregistered ablation could vary those factors separately. The current results cannot identify which factor caused a performance difference.

These follow-ups require a new versioned experiment and fresh evaluation tasks. Altering the controller, reward, task data or hyperparameters after reading this pilot's test outcomes would not be an unbiased improvement to the existing result.

## Product choice and research record

The application is configured to offer deliberate-only as its practical default based on the pilot observations, while retaining the baseline, heuristic and learned options for inspection. This is an explicitly post-evaluation product choice, not a change to the predeclared study or proof of general default-policy superiority. A new independent evaluation would be needed to assess the selected default beyond this pilot.

The adaptive artifact remains seed 17, as chosen before evaluation. No higher-scoring seed is substituted. Changing the visitor's default selection does not change the saved controllers, recorded requests, failures or benchmark denominators.

## Evidence and reproducibility

See [methodology](METHODOLOGY.md) for the frozen collection/evaluation protocol, [seed-17 evidence](../artifacts/studies/seed17/raw-runs.jsonl), [seed-29 evidence](../artifacts/studies/seed29/raw-runs.jsonl), [seed-43 evidence](../artifacts/studies/seed43/raw-runs.jsonl), and [the aggregate provenance](../artifacts/benchmark.json) for manifest/controller hashes and coverage. Smoke checks are development observations and are excluded from the benchmark.

All predeclared seeds and unsuccessful controller outcomes are retained. The project's defensible contribution is an inspectable implementation, a bounded real experiment and a reproducible account of what worked and what did not on the authored suite.

Aggregate file SHA-256 used for this interpretation: `b771deabe6f5cf380cfd46a08cbaa5e92caec6e79dcaefbca3ba1f8395496123`.
