# Living benchmark maintenance

A release reflects new verified work, not artificial activity. Monthly maintenance should inspect the existing source, current provider catalog, failed trajectories, task coverage and published links, then propose or implement the next bounded improvement.

1. Add 10–20 substantive new scenarios when useful, prioritizing new independent repository families over minor variants. Give every task a specification, visible failure, held-out edge/regression cases and a reference that passes in the real isolated runner.
2. Keep released tasks and raw study artifacts immutable. A corrected task changes the manifest and requires a new benchmark release; never overwrite unfavorable results.
3. New models, provider/quantization changes, reward functions, actions or budgets are separate treatments. Freeze their configuration before evaluation. Use training/validation for development; refresh the held-out families before claiming new unseen evaluation after repeated inspection.
4. Useful next ablations are learned selection versus its fallback, rollback availability, public-feedback removal, reward cost weight and additional task horizons. These are planned studies, not current results.
5. Keep the public dashboard read-only. No monthly job resets a ledger, raises a key limit, purchases credits, enables auto-recharge or keeps a GPU allocated. New spending beyond the existing finite authorization requires an explicit new budget.
6. Generate exports, figures and the technical report from the same preserved records. Check links, source hashes, mobile layout and PDF rendering before publication.
7. Update README benchmark date/model/task counts only after a real run. Record actual changes in CHANGELOG and a release. A monthly review without a benchmark does not count as a benchmark run.

The 200+ task target depends on tested diversity and measurable difficulty. It is a roadmap, not a current achievement. A preprint can follow a sufficiently supported experimental result; the current report must stay labeled as a technical software report without implying peer review, acceptance or novel-algorithm superiority.
