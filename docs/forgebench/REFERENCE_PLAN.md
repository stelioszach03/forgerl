# Optional proprietary reference: GPT-4.1

**Prepared, not executed.** This is a separate post-primary comparator, with no results asserted. It does not alter the frozen three-seed GPT-OSS primary study, its model routing, controller, task split or reported outcomes.

## Fixed treatment and verification

Use `openai/gpt-4.1`, hosted by **OpenAI** through OpenRouter. The public endpoint catalog was retrieved on **23 September 2026** and lists the exact provider tag `openai`, model id `openai/gpt-4.1`, and endpoint name `OpenAI | openai/gpt-4.1-2025-04-14`. It supports the requested `max_tokens`, `seed`, `response_format` and `temperature` parameters. The retrieved response is preserved in [reference-provider-snapshot.json](reference-provider-snapshot.json). Execution rechecks this fixed contract before loading the credential or making a paid request. Catalog availability is not a guarantee of account authorization or successful future inference. [Official endpoint catalog](https://openrouter.ai/api/v1/models/openai/gpt-4.1/endpoints).

The verified ceiling is **$2 per million input tokens and $8 per million output tokens**. This is a higher-priced proprietary reference than the selected GPT-OSS treatment. It is not described as newest, frontier or universally stronger; its quality on ForgeBench must be measured. The primary source identifies the model and published price. [OpenRouter GPT-4.1](https://openrouter.ai/openai/gpt-4.1).

Routing is fixed to `only: ["openai"]`, `order: ["openai"]`, `allow_fallbacks: false`, `require_parameters: true` and per-million-token price ceilings of `prompt: 2`, `completion: 8`. There is no model list, provider fallback, `:floor`, `:nitro`, automatic substitution, arbitrary endpoint URL or environment-selected model. Responses must identify exactly `provider="OpenAI"` and `model="openai/gpt-4.1"`; mismatches retain their recorded charge but are excluded as candidates. [Official provider-routing controls](https://openrouter.ai/docs/guides/routing/provider-selection).

The request uses JSON-object output, temperature 0.2, 4,096 maximum output tokens and the episode's requested seed. No reasoning parameter, tool calls, plugins or web-search feature are requested. Only visible `message.content` is captured; any separate reasoning fields are ignored. Requested seeds do not guarantee determinism. [Chat-completion API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion).

## Prespecified selection and limits

Run all ten existing **test** tasks, once each, in lexical identifier order, with episode seed **17**. Selection is independent of prior task successes or failures. Use the existing `strong_only` episode policy: at most six model requests, ten routing decisions, 100,000 measured/conservatively bounded tokens per episode and the original stopping/invalid-response rules. No controller fitting, validation-based tuning or hidden-test-driven retries occur.

Task identifiers:

- `federation-clock-components`
- `federation-clock-join`
- `federation-replica-recovery`
- `federation-strict-frontier`
- `federation-tombstone-policy`
- `search-case-normalization`
- `search-frequency-ranking`
- `search-label-semantics`
- `search-ranked-pagination`
- `search-search-release`

The required catalog hash is `ccb6b8e3996e067e24ecfb4b2f14d6ffb543380b10acb7bcfbc4f19d6b6f116b`. The runner rejects a changed catalog or a different ten-task test split.

The **entire reference study has a prospective $1 cap**, further restricted by the remaining existing research ledger. Every request reserves its conservative input-byte/output-token ceiling before network access. The per-study cap, global ledger cap, provider price filter and exclusive ledger lock all apply. An uncertain bill retains the full reservation; reported cost is rounded upward to microUSD. No cap resets or automatically renews.

All ten tasks are planned, **not guaranteed to finish within $1**. Using the per-episode token ceiling and six full 4,096-token responses gives a loose all-ten token-price bound of approximately $3.475 before rounding, so $1 cannot promise worst-case completion. Shorter successful patches can cost substantially less, but no estimate is presented as a measured result. Stop before any unaffordable reservation, retain the last attempted episode, and explicitly report every unrun task as missing. Do not lower output/call limits or select easier tasks to manufacture full coverage. Account purchase fees are outside the API-usage measure.

## Separate execution and evidence

New implementation files are `forgerl/bench/reference.py`, `scripts/reference_forgebench.py` and `tests/test_bench_reference.py`. They reuse the existing sandbox, episode engine, prompt schema and durable ledger through a separate fixed provider adapter. No frozen core-runtime file is modified for this comparator.

```bash
# Safe default: prints the plan; no key, ledger, catalog request or inference.
python scripts/reference_forgebench.py

# Operator-only after the primary job releases its ledger lock:
python scripts/reference_forgebench.py --execute-reference \
  --db /var/lib/forgerl/forgerl.sqlite3 \
  --key-file /etc/forgerl/openrouter.key \
  --max-cost-usd 1
```

An explicit output, if supplied, must stay under `artifacts/forgebench/reference/`. Evidence directories are new and cannot overwrite existing runs. Outputs include `plan.json`, `source-manifest.json`, `manifest.json`, append-and-flush `events.jsonl`, complete `runs/<id>.json` trajectories and **`reference.json`**. There is deliberately no primary `benchmark.json` output. The version is `0.2-reference` and protocol is `forgebench-v0.2-post-primary-reference-gpt41-seed17`.

Report actual model/provider configuration, source and task hashes, catalog verification, coverage, errors, token measurements, elapsed time and accounted API costs. An interrupted run retains a partial trace and terminal episode where possible. Unknown measurements remain unknown. This reference is not an extra independent seed of the primary study and must not enter its aggregator.

## Interpretation

This comparator was designed after the primary study was already launched. The test tasks are known authored benchmark tasks, not new held-out discoveries. Ten related scenarios in two families and one seed support a small descriptive comparison only. Any juxtaposition with primary results must label the different provider/model/source/protocol and post-primary timing. It cannot establish router superiority, industrial long-horizon capability or general model rankings. A higher bill is not evidence of a stronger result.
