# Recruiter explorer and optional bounded live trial

The default product is a read-only evidence explorer. It opens the completed
v0.3 transfer pilot: 162 actual episodes, six policies, separate primary,
validation and source-derived samples. The study selector preserves v0.2 and
existing v0.2 task/run links. Replay reveals stored events without inference.

Start with **Inspect a real repair**, then **See a verification miss**. The latter
deliberately shows a candidate that passed public VERIFY but failed the final
hidden grader. Original visible tests, supplemental public checks and final
hidden grading are separate. Missing token/cost measurements remain missing.
The published study, frozen source, outcomes and report are unchanged.

## Read-only deployment

Serve `forgerl.app:app` with `FORGERL_PUBLIC_INFERENCE=0` and
`FORGERL_WORKER=0`. No model credential, ledger or executor is required.
The default artifact root is `artifacts/forgebench/v0.3-pilot1`; an operator may
override it with `FORGEBENCH_PILOT_ARTIFACT_DIR`.

The public v0.3 routes are:

| Method and path | Content |
| --- | --- |
| `GET /api/forgebench/versions/v0.3-pilot1` | Actual policy summaries and run index |
| `GET …/tasks`, `GET …/tasks/{task_id}` | Visible task specification/source |
| `GET …/runs/{run_id}`, `GET …/runs/{run_id}/patch` | Sanitized recorded trajectory/patch |
| `GET …/download/{name}` | Allowlisted report PDF/Markdown, CSV, analysis JSON or trajectory JSONL |

The derived `explorer/` files can be regenerated without inference:

```sh
python scripts/export_pilot_explorer.py --output /tmp/forge-explorer-new
```

Use a fresh directory. Export checks the frozen catalog, actual initial files
and published analysis before writing anything. Its receipt hashes source and
outputs. Deployment includes the immutable `study/`, `analysis/`, `report/` and
derived `explorer/` directories; it does not need private research data.

## Optional live trial: separate from the benchmark

Implemented but disabled by default. Enabling it is an operator deployment
decision after reviewing the code, service identities, existing ledger and
isolated executor. The old v0.1 inference flag must remain disabled.

The trial accepts only `binary_protocol-repair-1` with `cheap_only`. It makes
at most one GPT-OSS-20B request, at most 2,048 output tokens, no provider retries
and a 120-second worker limit. It uses the pinned OpenRouter profile and the
existing rootless executor. No uploads, free-form prompt, arbitrary repository,
task choice, model choice or shell command are accepted. The trial uses the
original one-candidate engine, not the six-policy pilot experiment. It does not
alter the leaderboard or produce evidence of unseen-task generalization.

The task and research source are already public. Hidden/reference fixtures are
withheld from the model request and the live API; they are not a claim of
permanent secrecy or contamination resistance. The browser labels every live
result as a newly generated curated trial. Provider/worker failures stay failures;
the recorded-repair link is a distinct fallback, never a fabricated live output.

```text
Browser → HTTPS/Nginx → public FastAPI gateway (no key/ledger/executor)
                              │ bounded Unix-socket queue messages
                              ▼
                     private one-worker broker
                       │                 │
                 original ledger    model credential
                       │                 │
                       └── fixed request ┘
                              │ proposed files
                     existing executor broker
                              │
                    disposable rootless container
                              │ sanitized result
                              └── public gateway → browser
```

### Persistent controls and failure behavior

- Admission allows one active job and at most two queued jobs. Queued jobs expire
  after 180 seconds. A session is single-use and expires after 15 minutes.
- A private HMAC of the network address limits admission to one job per UTC day;
  raw addresses are not stored in broker tables. Session creation is additionally
  capped per address and globally. Shared networks can share this allowance;
  a distributed attacker can exhaust it, but cannot increase financial caps.
- Origin allowlisting, cross-site rejection, a secure HttpOnly SameSite cookie,
  CSRF token, owner-bound polling and atomic session consumption prevent replay
  and cross-session access. A browser disconnect does not restart the job.
- **All public-bucket ledger charges** count toward **$0.05 per UTC day** and
  **$1 per UTC month**. The original **$8 public / $20 global lifetime caps**
  remain unchanged. Calendar boundaries do not erase lifetime charges. The
  original provider-disabled latch is honored. No fresh ledger is permitted.
- Before each call, an atomic transaction reserves its conservative cost, with a
  maximum $0.005 per trial. The call must belong to an admitted running job and
  cannot reserve a second time, including after a zero-cost settlement.
  Missing provider usage retains the conservative reservation. Reported known
  cost is reconciled by the existing provider adapter; excess actual charges
  trip the original provider-disabled latch.
- One OS-held worker lock and atomic job claim prevent duplicate workers.
  Restart marks only this broker's running jobs interrupted and their pending
  reservations uncertain; it never replays them or resets research charges.
- Public responses suppress hidden fixtures, credentials and internal error
  details. Financial summaries are accounted inference cost; purchase fees and
  VPS cost are excluded. Containers share the host kernel; this is not a microVM.
- Every live API response, including session, error and state responses, is marked
  `Cache-Control: private, no-store`. Terminal job payloads and their expired
  sessions are pruned after seven days by hourly worker maintenance or the next
  session request. Queued/running work is never pruned; financial charge rows
  and uncertain reservations are retained permanently.

### Operator setup and review checklist

Examples are in `ops/recruiter-broker.service.example` and
`ops/recruiter-public-gateway.conf.example`; they are not an installer.

1. Preserve/backup the original existing ledger. Review its current totals and
   provider-disabled state without resetting anything. Stage this application
   separately from frozen research runtimes; no historical source is replaced.
2. Use a private broker identity with access to the existing ledger and executor
   socket. The public viewer identity must have neither. A new dedicated
   `forgerl-recruiter-client` group grants only access to the broker socket.
   Do not add the public viewer to the private research/executor group.
3. Supply `openrouter-key` and a random persistent `recruiter-session-secret`
   (at least 32 bytes) through systemd `LoadCredential` to the private broker
   only. Do not print/copy credentials into source, the public service or logs.
4. Set the broker's existing `FORGERL_RECRUITER_LEDGER`, isolated
   `FORGERL_EXECUTOR_SOCKET`, exact `FORGERL_RECRUITER_ORIGINS` and explicit
   `FORGERL_RECRUITER_WORKER_ENABLED=1`. The launcher supports only a fresh
   absolute Unix-socket path; it rejects existing paths and the private ASGI
   application rejects TCP clients. Directory/socket permissions are 0750/0660.
5. Configure the public process only with `FORGERL_RECRUITER_BROKER_SOCKET` and
   the same origins. Preserve `FORGERL_PUBLIC_INFERENCE=0`, `FORGERL_WORKER=0`.
   Apply the example filesystem restrictions after checking real service paths.
   The optional `-/run/forgebench-executor` restriction tolerates an absent
   executor runtime directory at boot; UID/group permissions still deny access.
6. Keep public Uvicorn reachable only through the local trusted reverse proxy.
   Trust forwarded addresses only from that proxy; Nginx should replace
   `X-Forwarded-For` with `$remote_addr` and set the correct HTTPS scheme. The
   gateway uses the resulting ASGI client address, never a user-provided IP
   parameter. Do not use unrestricted forwarded-IP trust on an exposed listener.
7. Verify the read-only explorer first, Unix-socket group permissions, and denial
   of public key/ledger/executor access. Test bad Origin, missing CSRF, extra body
   fields, replayed admission and another session's job ID. Run at most the
   explicitly reviewed tiny live smoke, then reconcile its original-ledger row.
8. To disable live admission, remove the public socket environment setting and
   restart the public viewer. Stop the private broker if required; scoped recovery
   preserves pending accounting. Recorded replay remains available throughout.

The public contract is `GET /api/recruiter-live/state`, explicit
`POST /session`, `POST /runs` with fixed task/policy and `X-CSRF-Token`, then
owner-bound `GET /runs/{id}`. Session creation and admission are never retried
automatically by the browser after an ambiguous response. A saved opaque job ID
allows polling after reload; no credential/CSRF is stored in browser storage.

## Verification

Focused offline tests exercise actual published record counts, immutable-source
binding, negative outcomes, version switching, GET-only replay, mobile-safe DOM,
private transport, financial concurrency, restart recovery and a synthetic
one-call worker. Synthetic provider tests are not reported as model experiments.

```sh
python -m pytest -q tests/test_pilot_view.py tests/test_recruiter_*.py
npm run test:frontend
```

Visual acceptance uses the actual read-only local app on desktop and a 390-pixel
phone viewport. Live-provider availability and real isolated execution require
the operator's separately authorized deployment smoke; an offline test cannot
establish those production conditions.
