# ForgeRL implementation contract

Status: implementation and the predeclared three-seed pilot are complete. See README, the benchmark artifact and deployment evidence for the release status and measured scope.

## Scope and evidence
An actual bounded Python repair agent: curated authored regression tasks, LLM-generated code edits, isolated execution, visible test outcomes, exported unified patches and traceable model/token/cost events. A finite adaptive controller chooses a short-budget model call, deliberate model call, replan or stop. Train the controller using real collected transitions; never claim the language models were fine-tuned or trained with GRPO. Frozen policies are evaluated prospectively on held-out task families. Negative results are published with their limits. This is not SWE-bench or arbitrary GitHub execution.

## Deployment and budget
Existing portfolio VPS: 4 vCPU, 16GB RAM, 193GB disk, Docker and Nginx. Deploy under https://stelioszach.com/demos/forgerl/ first; a separate subdomain is optional and must not block the real project. Existing site and four demos remain untouched until isolated acceptance succeeds. CPU handles web/queue/controller/sandboxes. Runpod predeployed model endpoints supply inference, with no always-on GPU allocation. Initial research hard cap $12, public inference reserve $8, safety reserve $5 (maximum user-authorized spend $25). All inference reservations survive process restarts and unknown/timeout bills are retained. API key stays outside source in systemd credentials. Never echo or publish keys.

## Implementation ownership
Root: FastAPI app, durable SQLite/WAL queue and event store, provider integration, spend ledger, public request limits, deployment, publication.
Engine agent: forgerl/tasks.py, forgerl/sandbox.py, sandbox/ runner, forgerl/controller.py and tests for those files. Independent of HTTP/UI.
Frontend agent: static/ UI and frontend tests only, using this API contract.
Research agent: methodology/protocol, later training/evaluation scripts and evidence review after module contract is ready.

## Backend contract (same-origin relative api/ under base URL)
- GET api/meta -> {name,version,live:{available,reason,remaining_usd,per_run_max_steps},policies:[{id,label,description}],models:[{id,label}],limits:{max_steps},evidence_status,links:{source,methodology}}
- GET api/tasks -> {tasks:[{id,title,family,difficulty,split,summary,description,source,filename,public_tests_count,tags:[]}]}. No expected hidden outputs in public API/model prompt.
- GET api/tasks/{id} -> task object with public_tests descriptions and source.
- POST api/session -> sets signed HttpOnly Secure SameSite cookie, returns {csrf_token}. No account registration or external messaging.
- POST api/runs header X-CSRF-Token, body {task_id,policy} -> 202 {id,status,mode:"live"}. No arbitrary prompt, repository, code or shell input. Known policies fixed, heuristic, adaptive; UI must not invent capability or results.
- GET api/runs?limit=20 -> {runs:[RunSummary]}. Gallery contains recorded research evidence and public curated-task runs only.
- GET api/runs/{id} -> RunDetail below.
- GET api/runs/{id}/events?after=0 -> {events:[{seq,kind,title,message,at,data}],status,next_seq}; polling every 1.5s is acceptable; stop at terminal state. No fake streaming/progress.
- GET api/runs/{id}/patch -> text/plain unified diff.
- GET api/runs/{id}/export -> JSON trace + provenance; exclude credentials/IPs/session hashes.
- GET api/benchmark -> {status:"not_run"|"complete",methodology:{...},summary:[{policy,n,solved,solve_rate,mean_steps,mean_tokens,mean_cost_usd,mean_latency_s}],paired_runs:[{task_id,task_title,runs:[RunSummary]}],limitations:[],provenance:{...}}. Empty state must be honest.
- RunSummary: {id,task_id,task_title,policy,status,mode:"live"|"recorded",created_at,steps,tokens,cost_usd,elapsed_s,public_passed,public_total,heldout_passed,heldout_total,solved,stop_reason,model_ids:[]}
- RunDetail = summary + {events:[],initial_source,final_source,diff,evidence:{...},error:null|string}
- Errors JSON {detail:{code,message}}; HTTP 403 session/CSRF,429 limits,503 provider/budget unavailable. Always handle safely/readably.

## Engine Python interfaces
Task dataclass: id,title,family,split,difficulty,summary,description,source,filename="solution.py",function_name,public_cases,hidden_cases,tags. Each case {name,args,kwargs,expected} JSON values; optional expected_error str. Curated tasks only. Provide list_tasks(), get_task(id), public_task(task,include_cases=False), task_manifest_hash(). Author 24 meaningful regression tasks across disjoint train/validation/test families, ideally 12/6/6. Correct reference implementations can live in tests but must never enter model prompts.

Sandbox interface: evaluate(task,source,hidden=False)->dict {passed,total,cases:[{name,passed,actual,error}],elapsed_s,security:{...}}. Never exec generated source on the host. Docker-only production backend, no unsafe fallback. Local tests mock subprocess or run Docker only if available. Server-owned expected outputs stay outside model/container; run code in a networkless, non-root, read-only, no-mount, no-capabilities container with timeout, memory/CPU/pids/output limits. Runner receives source and input cases through stdin; returns actuals only, host compares against server-owned expected outputs. Plan for a local Unix-socket executor broker so HTTP app receives no Docker socket/admin privileges. AST guard is defense in depth, not a security boundary. Implement broker/client separation if practical; root will install dedicated executor.

Controller: state features only observable public tests + attempt/cost budget + last action/improvement. Actions {"fast","deliberate","replan","stop"}; selectors fixed/heuristic/adaptive; max3 model calls initially (fixed also stops at actual visible pass to avoid strawman wasted calls). Adaptive falls back honestly to heuristic when no trained artifact exists; API labels not-trained until artifact loaded. provide choose_action(policy,state,artifact=None), encode_state(state), fit_q(transitions,seed,...) -> JSON artifact + diagnostics. No fabricated confidence percentage. Stop on visible pass can still fail held-out tests, reported explicitly.

## Frontend visual plan
Visual thesis: a precise dark research workbench in the portfolio's navy/teal palette, using the actual SZ logo, restrained type and code/trace as the visual anchor.
Content: compact brand/navigation, task selector + source/issue, run controls, measured trace and patch/tests inspector; separate experiment comparison and methodology. Mobile collapses inspectors with 44px touch targets; every panel has one purpose.
Interaction thesis: gentle entry, live event insertion/status transitions, keyboard-accessible source/diff/test tabs; reduced-motion honored. No emoji decoration, fake benchmarks, made-up progress bars or fabricated runs. Main statuses always distinguish Live, Recorded, Not run and Unavailable. No stock hero imagery needed for a technical operator workspace.
