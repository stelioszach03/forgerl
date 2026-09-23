# ForgeBench operations

## Read-only public service

The public site serves stored artifacts. `FORGERL_PUBLIC_INFERENCE=0` is the default; POST session/run routes reject requests before admission. No worker, provider session or recovery process starts. Browsing, downloading a report and opening a trajectory make no inference calls.

The deployment definition in `deploy/forgerl-public.service` uses its own `forgerl-viewer` Unix identity, no `LoadCredential`, no executor socket setting, and a derived v0.1 archive database. The authoritative research ledger remains `/var/lib/forgerl/forgerl.sqlite3`; the sealed archive contains only public runs and events, has no ledger tables or write methods, and is never used for spending. Published v0.2 JSON files are root-owned, readable evidence. The public identity has no access to private research data, credential directories or broker group permissions.

Nginx serves TLS and routes `/demos/forgerl/` to the loopback public service. The vanity domain https://forge.stelioszach.com routes to the same service with a valid certificate and renewal reload hook; the original portfolio URL remains available. Public serving does not depend on a research job or GPU allocation.

## Operator-run research

Keep model keys in root-only files under `/etc/forgerl`, passed as systemd `LoadCredential`. Do not embed secrets in command arguments, repository configuration, prompts, output JSON or frontend code. `OPENROUTER_API_KEY_FILE` is also supported for an explicitly private credential file outside the checkout.

The controlled `openrouter` profile pins CoreWeave's FP4 endpoints for GPT-OSS-20B and GPT-OSS-120B, disables provider fallback and enforces price ceilings. Successful results must identify the requested model and CoreWeave. `openrouter-dev` uses `:floor` and is explicitly a variable-provider development treatment. Never aggregate these two profiles as equivalent runs. `runpod` and `together` are optional explicit adapters, not silently substituted providers or a claim they were evaluated in v0.2.

The key has a finite non-renewing account-side limit. The durable ledger independently retains the original research/public/global caps and all earlier charges. Each study and episode adds preflight caps. Reported OpenRouter usage cost is rounded upward to microUSD for ledger safety; raw reported cost remains in trajectories. Unknown billing retains the complete price-ceiling reservation. These figures exclude credit-purchase fees. No auto-recharge or GPU instance is required.

Research requires the restricted rootless executor. Pin `FORGERL_SANDBOX_IMAGE` to the built image digest in its broker service and set `FORGEBENCH_EVALUATED_IMAGE` to that exact digest for study provenance. The research process receives only the broker socket, not the Docker socket. The broker has no model credential or research ledger. Never execute generated modules on the host or switch to an unsafe fallback when Docker is unavailable.

```sh
# Plan only; does not read a key or open the ledger.
python scripts/forgebench.py --seed 17 --provider openrouter --max-cost-usd 5

# Inside the authorized operator service with private credential/socket env:
python scripts/forgebench.py --execute-research \
  --db /var/lib/forgerl/forgerl.sqlite3 --provider openrouter \
  --seed 17 --max-cost-usd 5 --output /var/lib/forgerl/studies/forgebench-v02/seed17
```

Run requested seeds17,29,43 in separate fresh directories. The CLI takes an exclusive ledger-adjacent lock. Do not launch competing research processes or remove their lock. Never rerun an uncertain request merely because its completion was lost. Trajectory events are fsynced as they occur; completed episodes are atomic. Inspect partial artifacts, the durable ledger and service status before deciding whether a new protocol/run is needed.

## Publication and rollback

### Rate limits in new studies (runner v0.2.1)

The research CLI defaults to `--rate-limit-retries 2` for new experiments. An explicit HTTP 429 can be retried at most twice within the original six-request, ten-decision, cost and token bounds. Waits use 30/60-second backoff and respect a longer valid `Retry-After` value up to 60 seconds. If the provider requires more than 60 seconds, the episode stops instead of retrying early. Each wait and request is recorded; the pinned provider/model do not change. Unknown charges retain their reservation and unknown token usage remains unknown.

These runs use the distinct `forgebench-v0.2-prespecified-rate-limit-retry-v1` protocol and record the retry limit in configuration. Do not pool them with the completed v0.2 study. Use `--rate-limit-retries 0` to disable the behavior; exact reproduction of published v0.2 uses its frozen source commit `abadaff` and preserved artifacts. The public dashboard remains read-only. It labels historical 429 records and unconfirmed budget reserves and can open the next recorded seed without inference.

1. Preserve study directories unchanged. Copy artifacts, verify source/task/provider/controller hashes and aggregate all predeclared seeds, including incomplete ones.
2. Build CSV/JSONL, figures and technical report from those same records. Render and inspect the actual PDF; fixture PDF checks do not verify a final report.
3. Test a new public release on loopback under the public identity, without keys or broker permissions. Verify catalog size, known recorded run, patch/export, provider-disabled admission and the archived v0.1 results.
4. Back up Nginx configuration and the prior release before routing to the tested service. Run `nginx -t`, reload and verify the portfolio and all existing demos as well as ForgeRL.
5. Roll back the route/release on a failed health or content check. Do not replace the authoritative research database or reset accounting during rollback.
6. After research, verify the operator unit has stopped and no model jobs or GPU instances remain. The public page stays available independently.

## Maintenance boundaries

Follow [MAINTENANCE.md](MAINTENANCE.md). A monthly review can check correctness, provider availability, task quality and reproducibility. It does not silently raise limits, buy credits, publish invented activity or submit a paper. Keep the v0.1 study separate and retain unfavorable v0.2 results.
