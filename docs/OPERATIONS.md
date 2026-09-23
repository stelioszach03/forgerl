# ForgeRL operations

The reference deployment runs on one Linux VPS behind an existing HTTPS reverse proxy. FastAPI, SQLite, the controller and recorded evidence run on CPU. Hosted model requests go to Runpod only when admitted by the persistent spending ledger. This design has one queue worker and one host; it is not a highly available distributed cluster.

## Isolation and process ownership

The deployment scripts establish two service identities:

| Identity | Access |
|---|---|
| `forgerl-api` | Private application database, web process, restricted executor socket and systemd-loaded provider/session credentials |
| `forgerl-executor` | Its own rootless Docker daemon and constrained execution broker; no application database or provider credential |
| Container UID 65534 | Submitted candidate code and input cases over stdin; no host mounts, secrets or network |

The executor accepts a fixed JSON schema over a private Unix socket. It cannot accept arbitrary Docker commands, images, mounts or execution flags. Expected outputs stay outside the container and are compared by the trusted caller. The API service is not added to the Docker group and does not receive a Docker socket.

The configured container limits are 128 MiB memory, 0.5 CPU, 32 PIDs, a read-only filesystem, no network, dropped capabilities and `no-new-privileges`. The runner has output and execution limits, and timed-out containers are removed. The [runtime isolation receipt](../evidence/runtime-isolation.json) records a verified deployment snapshot; rerun verification after changing the kernel, Docker configuration or sandbox image. Docker flags alone are not proof that a host enforces the limits.

Rootless Docker uses user namespaces and a shared host kernel. It reduces privilege exposure but is not a microVM and does not guarantee safety for arbitrary hostile code. This app only permits its curated task catalog. Do not add repository upload, package installation or arbitrary shell execution without redesigning the trust boundary. [Docker rootless documentation](https://docs.docker.com/engine/security/rootless/)

## Configuration

Keep secrets outside the repository and application release directory. The following are placeholders, not production credentials or paths:

```sh
export RUNPOD_API_KEY_FILE=/path/to/private/provider-key
export FORGERL_SESSION_KEY_FILE=/path/to/private/session-key
export FORGERL_DB=/path/to/persistent/forgerl.sqlite3
export FORGERL_EXECUTOR_SOCKET=/path/to/private/executor.sock
export FORGERL_POLICY_FILE=/path/to/release/artifacts/policy.json
export FORGERL_BENCHMARK_FILE=/path/to/release/artifacts/benchmark.json
export FORGERL_PUBLIC_ORIGIN=https://portfolio.example
```

Production uses systemd `LoadCredential` for both keys. Direct environment-key support exists for development but should not be embedded in service command lines, shell history, source files or CI. The session key must remain stable across ordinary service restarts. The database directory is private to the API identity; the executor cannot read it.

`FORGERL_WORKER=0` disables the queue worker for a read-only preview or maintenance process. Use exactly one live worker for this release. The broker's permitted-UID list must include only the authorized API/operator identities. If the broker is configured but unavailable, execution fails closed; it does not fall back to host Python execution.

## Initial installation

Review `scripts/setup_host.py` and `scripts/install_service.py` before running them as an administrator. They are reference deployment scripts with an explicit host layout, not a portable package installer. They do not configure DNS, TLS or the public reverse proxy.

1. Install Python 3.12, Docker's rootless tooling and its user-namespace prerequisites. Ensure cgroup limits are available and delegated correctly. The Docker guide documents subordinate UID/GID requirements and rootless service setup.
2. Place the reviewed release in the location expected by `install_service.py`. Provision the provider key as a root-owned private file with mode 0600 using a secure file-transfer/editor workflow. Do not pass the secret value as a command argument.
3. Run `setup_host.py` to create the dedicated identities and rootless daemon. Preserve other applications' Docker services; this project uses a separate daemon/socket.
4. Run `install_service.py`. It installs locked Python dependencies, builds the sandbox, records its immutable image ID, loads service credentials, and starts the broker and API on loopback.
5. Run the offline test suite and explicitly enabled Docker integration checks against the intended execution context. Run `scripts/verify_isolation.py` against the rootless daemon and the exact recorded image.
6. Check loopback health, metadata, task retrieval and a recorded trace. A fresh provider smoke run is optional paid work and must use the same research ledger.
7. Enable the public reverse-proxy route only after local acceptance. Check the existing proxy configuration before reloading it.

The reference API listens on loopback port 18405 and trusts forwarded headers only from loopback. The public deployment uses the `/demos/forgerl/` prefix. The proxy must strip that prefix before forwarding and overwrite the forwarded client-IP header with the actual peer address. Otherwise client-supplied forwarding headers can invalidate per-IP limits.

A corresponding location block for an existing TLS site is:

```nginx
location /demos/forgerl/ {
    client_max_body_size 2k;
    proxy_pass http://127.0.0.1:18405/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Adapt the public origin and cookie path together if deploying at another prefix. The current secure-session cookie path is explicitly scoped to the reference demo prefix. Keep the API listener private and let the existing proxy terminate TLS.

## Spending and admission controls

The ledger stores integer micro-USD amounts in SQLite. A transaction reserves each request's conservative upper estimate before the provider is called. The overall normal operating allowance is $20: $12 research and $8 public inference. The remaining $5 of the original $25 is held as contingency, not automatically spendable. These are one-time experiment allowances, not recurring monthly budgets.

Public inference additionally has a rolling daily spending limit, bounded queue depth, two runs per session per day and three runs per IP per day. Cookies use an HMAC-protected session and CSRF token. Clearing a cookie does not remove the IP/global limits. Limits reduce casual abuse; they do not establish a person's identity or defeat every coordinated client.

Costs are conservative estimates based on provider token usage and the configured published rate. They are not invoices. Timeouts, cancellation and ambiguous failures retain their reservations. A charge above its reservation disables further provider access for investigation. Runpod account limits and account balance are separate from these application limits; do not enable automatic top-ups as part of operating this project.

Use the same persistent database for the service and all research scripts. Creating a fresh ledger, deleting charges or restoring an older ledger without reconciliation can permit repeated spending beyond the approved allowance. Reconcile estimates with provider billing records before increasing a limit. Never turn the $5 contingency into a recurring automatic refill.

## Pause and resume new inference

Run operator commands as an identity authorized to access the existing database, with `FORGERL_DB` pointing at that database. The following pauses new reservations while preserving read-only pages and evidence:

```python
from forgerl.store import Store

with Store().transaction() as connection:
    connection.execute(
        "INSERT INTO settings(name,value) VALUES('provider_disabled','operator_paused') ON CONFLICT(name) DO NOTHING"
    )
```

Existing requests may still finish and settle their charges. For maintenance, allow in-flight work to finish where possible before stopping the API service. Do not clear uncertain reservations to make the UI available again.

After resolving the operational issue, remove only the explicit operator pause:

```python
from forgerl.store import Store

with Store().transaction() as connection:
    connection.execute(
        "DELETE FROM settings WHERE name='provider_disabled' AND value='operator_paused'"
    )
```

Provider HTTP 401/402/403 responses also pause new reservations with a `provider_access` reason. After resolving the credential, credit or permission issue, an operator may remove that specific reason while preserving the spending ledger, then perform a bounded smoke check. Do not remove a different discrepancy flag.

Investigate an accounting-discrepancy pause separately; do not clear it with an unrestricted delete. A code change is required to authorize a larger application budget, and should be reviewed as a spending change.

## Release, rollback and backup

Build a candidate release separately. Run Python, Docker and frontend checks, verify the task manifest and frozen controller compatibility, then check the UI at desktop and mobile widths. Preserve a copy of the current code, artifacts and service configuration before promotion. The installer writes systemd units and rebuilds the runner; ordinary releases should not rerun host provisioning unnecessarily.

The production policy must be the predeclared seed-17 artifact. Install it only after checking its trained flag and manifest fingerprint. Publish the aggregate benchmark and its supporting evidence together. Do not select a different seed because it scored better, or advertise a partial study as complete.

For a code rollback, return to the previous code/artifact release and restart only the ForgeRL services that changed. Keep the current database and charges. A rollback must not reset spending or silently replay requests that were interrupted. The queue recovery path marks an in-progress request interrupted after restart; uncertain provider billing remains recorded.

Back up SQLite using its backup API or another WAL-aware method while the database is live. Copying only the main `.sqlite3` file can omit committed WAL data. Store backups privately with restrictive permissions and keep raw evidence/manifests alongside the appropriate release. The database includes rate-limit hashes and operational records; it is not a public research artifact.

After restoring an older backup, leave inference paused until missing provider charges and pending requests have been reconciled. Verify restored data and artifact checksums before resuming. A backup kept only on the same VPS does not protect against loss of that VPS; this project does not claim cross-host disaster recovery.

## Credential rotation and incident handling

Pause new inference first. Replace the provider credential atomically with a new private file while preserving restrictive ownership and permissions, then restart the API service so systemd reloads it. Verify the new configuration through a bounded, explicitly accounted smoke request before revoking the old key. The executor needs no provider-key restart or access.

Rotate the session-signing key when compromise is suspected; existing sessions and CSRF tokens become invalid and users start a new session. Normal application releases do not require a session-key change. Do not put key values into command history or diagnostic exports.

If a key leaks, revoke it at the provider, preserve the ledger and review request/billing history. If the executor boundary is suspect, stop new inference and the affected executor, retain evidence, patch/rebuild the isolated runtime and repeat acceptance before re-enabling it. Do not publish private logs, session/IP hashes or credentials in a GitHub issue.

## Checks and limitations

Health reports process availability; it is not proof of provider reachability, budget availability or effective container isolation. Inspect `/api/meta` for live availability and `/api/benchmark` for evidence status. Check service logs for execution failures and the provider console for billing differences. Recorded traces should have real patch/test events and preserve failed or uncertain outcomes.

The application returns security headers, applies origin/CSRF checks and escapes backend content in the UI. These are tested controls, not an external penetration test or an impossible-to-hack guarantee. The SQLite queue and single VPS suit this bounded demo; no service-level agreement, failover cluster or independent security certification is claimed.

CI uses the official [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python) and [setup-node](https://github.com/actions/setup-node) actions, pinned to verified v7 commit hashes. It has read-only repository permissions, does not persist checkout credentials and uses no deployment/provider secrets. Review and update the pins intentionally. [GitHub secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use)
