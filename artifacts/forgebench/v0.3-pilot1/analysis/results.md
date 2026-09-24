# ForgeBench v0.3 prospective transfer pilot results

Coverage: **162 / 162** prespecified episodes. Study status: **complete**.

Descriptive one-seed pilot. No broad superiority, statistical significance or learned-verification claim.

## test

| Policy | Attempted/planned | Family-weighted success | Accounted cost/task | Graded episodes |
| --- | --- | --- | --- | --- |
| strong_only | 18/18 | 88.9% | $0.000263 | 18 |
| cheap_only | 18/18 | 83.3% | $0.000137 | 18 |
| escalate_on_failure | 18/18 | 88.9% | $0.000100 | 18 |
| static_router | 18/18 | 83.3% | $0.000140 | 18 |
| adaptive | 18/18 | 88.9% | $0.000194 | 18 |
| supervised_cost | 18/18 | 94.4% | $0.000124 | 18 |

## validation

| Policy | Attempted/planned | Family-weighted success | Accounted cost/task | Graded episodes |
| --- | --- | --- | --- | --- |
| strong_only | 6/6 | 100.0% | $0.000142 | 6 |
| cheap_only | 6/6 | 83.3% | $0.000205 | 6 |
| escalate_on_failure | 6/6 | 100.0% | $0.000128 | 6 |
| static_router | 6/6 | 100.0% | $0.000181 | 6 |
| adaptive | 6/6 | 100.0% | $0.000138 | 6 |
| supervised_cost | 6/6 | 100.0% | $0.000145 | 6 |

## external

| Policy | Attempted/planned | Family-weighted success | Accounted cost/task | Graded episodes |
| --- | --- | --- | --- | --- |
| strong_only | 3/3 | 100.0% | $0.000852 | 3 |
| cheap_only | 3/3 | 100.0% | $0.000309 | 3 |
| escalate_on_failure | 3/3 | 100.0% | $0.000444 | 3 |
| static_router | 3/3 | 100.0% | $0.000400 | 3 |
| adaptive | 3/3 | 100.0% | $0.000323 | 3 |
| supervised_cost | 3/3 | 100.0% | $0.000266 | 3 |

Single-seed descriptive pilot. Family-weighted means use observed families; incomplete coverage prevents a full-matrix claim. All infrastructure failures retained, graded-only conditional sensitivity separate. External source-derived track never pooled.

Full per-run metrics, reserved-cost accounting, verification outcomes and learned/fallback counts are in results.csv and analysis.json.
The original all-action learned/fallback counts are preserved. A separately labeled post-run diagnostic excludes STOP/VERIFY, reports STOP source counts and separates provider-retry actions; it does not change primary scores or the frozen protocol.

Frozen source digest: `990e82a33d8a69f73cc3690031ff98fa430fc073d5bca035666b39b124769708`.
Frozen protocol digest: `ae5156ee716a6babff6ef2871a988988c0917ec4a63b0f18bc22ad41848dd3ae`.
