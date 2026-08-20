# Labtasker v2 rewrite

`LABTASKER_V2_SPEC.md` is the authoritative standalone user-visible contract. This
plan may explain implementation structure but must not carry semantics required to
understand the public API. If the two documents disagree, update this plan to the
specification.

## Principle

Build the smallest reliable replacement for an experiment `for` loop. The current
repository is only a behavior reference. Do not design extension points before a
real second implementation or user requires them.

Small does not mean rough. Prefer a narrow, complete and polished framework over
broad feature coverage. A public feature ships only when its semantics, failure
behavior, HTTP/client surfaces, tests and documentation form a complete vertical
slice. Otherwise omit it without leaving a public stub or speculative extension
point.

Treat the rewrite as subtractive refactoring. Classify each touched v1 feature as
retained, redesigned or deleted. A deleted feature leaves no compatibility switch,
configuration field, dormant branch, dependency, test or documentation burden.
Do not keep an old mechanism merely because its replacement has been added.

Make Labtasker v2 agent-first. Every core workflow must be accessible through
deterministic, non-interactive and machine-readable public contracts with stable
errors, identifiers and retry behavior. Do not embed an LLM or general agent
framework; provide polished primitives that external coding agents can compose.
Workers remain autonomous after startup: agents may configure, launch, observe and
recover them, but task execution never waits for an agent decision.
Agent-friendly does not mean machine-only: keep JSON formatted and messages/logs
clear to a person on first read. Do not add parallel output modes merely because
an Agent is the primary operator.

## Initial shape

```text
labtasker/
├── packages/
│   ├── labtasker-client/
│   │   ├── src/labtasker/
│   │   └── pyproject.toml
│   └── labtasker-server/
│       ├── src/labtasker_server/
│       └── pyproject.toml
├── tests/
└── pyproject.toml
```

Publish two distributions from one monorepo:

- `labtasker` is the lightweight client package users install in experiment
  environments. It contains the Python API, worker loop and user CLI.
- `labtasker-server` contains the API server, database, migrations and server CLI.

Neither distribution depends on the other. They communicate through HTTP. Keep
their versions synchronized initially, but do not require exact-version equality;
the API exposes a protocol version and compatibility is checked in contract tests.
The first release version of both distributions is `2.0.0`, not `0.1.0`.

Do not publish a third `core` package yet. Domain rules belong to the server, while
wire models belong to the HTTP contract. A shared runtime package would couple
client and server releases without reducing much code.

The v2 Client speaks only `/api/v2`; the Server exposes no v1 adapter, and no
Client probes/falls back to v1. V1 and v2 may run as separate deployments during
cutover, but startup performs no v1 MongoDB import.

Keep the Server implementation direct:

```text
HTTP routes + private Pydantic schemas
                 -> TaskService / QueueService
                 -> private SQLAlchemy models + explicit SQL
```

Routes translate HTTP and domain errors but never manipulate ORM rows directly;
services own behavior and transactions without constructing HTTP responses; ORM
objects are not response models. Add no repository, generic Unit of Work or
domain-aggregate layer.

Use ordinary standard-library-compatible Python logging for Server and Worker
operational messages. Finite data CLI commands retain formatted JSON stdout, but
`loop` logs human-readable text to stderr and relays user output rather than
emitting JSONL events. Add no log-format mode. Never log Authorization/token;
other diagnostic fields are permitted when useful, without requiring routine
large-payload dumps or a redaction framework.
Handled finite-command `LabtaskerError`s use one readable indented JSON envelope
on stderr and exit 1; API errors preserve the Server envelope. Keep Typer usage
errors at exit 2 and `loop` diagnostics as natural-language stderr.

Keep CLI-owned Worker and Server loggers at INFO without verbosity/log-level
flags. Transient, task and fatal Python outcomes log at WARNING, ERROR and
CRITICAL; task/fatal include traceback while transient does not by default.
Command failure logs its exit code or signal once and relies on the already
relayed/journaled output rather than duplicating it.

Treat Linux as the fully supported and release-gated initial platform. Keep
ordinary Client, Server and noninteractive pipe Worker code portable on macOS and
Windows, but do not block 2.0.0 on full PTY, process-tree, launcher or distributed
parity there; ConPTY remains deferred.

Do not port v1's import-time Loguru/Rich logging setup. Import never replaces
streams or changes handlers. When a Worker invocation begins, respect an existing
effective `labtasker` logger configuration or install one named INFO stderr
fallback without touching root; remove only the fallback Labtasker owns.

Retain Python Worker tee as a small process-lifecycle utility: wrap the current
stdout/stderr only for the Worker invocation, restore them on return, and route
both through one shared lock to the sole active Task `run.log`. This captures
Python-level writes from Task threads, preserves ANSI and omits ContextVar/nested
destination machinery. Disable the inherited destination after fork. Do not
promise native-fd or arbitrary subprocess capture, and make surviving
output-producing Task threads user error. Command Workers continue to use their
separate raw-byte PTY/pipe implementation.

## 2.0.0 initial release scope

Only implement the path needed to run parameterized experiments:

1. Submit tasks containing JSON arguments.
2. Atomically claim one pending task, ordered by priority then stable pending
   order.
3. Run a Python function or shell command.
4. Heartbeat while it runs; heartbeat is mandatory for every claimed run.
5. Mark it successful, or retry it after an ordinary failure or lost heartbeat.
6. List/count tasks by status and inspect arguments/results.
7. Cancel or manually requeue a task.

Keep five task states: `pending`, `running`, `succeeded`, `failed`, and
`cancelled`. Cancellation is terminal and never consumes another retry, so
representing it explicitly is simpler than encoding it as a failure plus flags.

Keep Queue as the only server-side namespace and scheduling pool; do not add a
Project entity. Initialize a fresh database with `default`, require explicit
creation for every other Queue, and never auto-create one during submit. The 2.0.0 initial release
includes atomic hard Queue deletion: non-empty deletion requires explicit cascade,
and any running Task blocks it until cancellation.

Validate Queue and route with one case-preserving ASCII grammar,
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Match exactly and never lowercase. The
128-character ceiling accommodates descriptive Agent-generated labels without
allowing unbounded identifiers in paths, indexes and logs.

Treat one server as one trust domain. Use one optional server-wide Bearer token
and remove Queue passwords, per-Queue credentials, users and roles. Tokenless
startup is allowed only on an exclusively loopback bind; refuse a non-loopback
bind without a token. Configure or rotate the token through config/environment and
server restart, with no token-management API.
Treat `ipaddress(...).is_loopback` literals and case-insensitive exact `localhost`
as the complete tokenless host allowlist; wildcard addresses and other hostnames
require a token regardless of current DNS resolution.
When no Server token is configured, ignore an incoming Authorization header. When
configured, missing, malformed and wrong Bearer credentials all return the same
`401 unauthorized` plus `WWW-Authenticate: Bearer`, without diagnostic leakage.

Expose only `labtasker-server serve --host ... --port ... --database PATH`, with
defaults `127.0.0.1`, `8000` and `.labtasker/server.db`. Accept a SQLite path, not
a speculative backend URL; resolve relative paths from CWD and create the parent
directory. Read the credential only from `LABTASKER_SERVER_TOKEN`, rejecting a
present empty value. Add no token flag, Server config file, reload/workers/daemon
or log-level surface; supervision remains external.

Run Alembic initialization/forward migration before listening. Initialize a fresh
database and its `default` Queue, upgrade known older v2 revisions, and refuse
newer/unknown revisions or any migration failure. Add no upgrade/downgrade command
or automatic backup, and do not silently import v1 MongoDB data.

Configure every SQLite connection with WAL, foreign keys, a 5000 ms busy timeout
and FULL synchronous durability; establish/verify persistent settings at startup
and abort when the required values cannot be applied. Expose none of these as
public tuning options.

Do not rewrite running Tasks during Server shutdown. Before listening after a
restart, recover every already expired lease through the normal heartbeat-loss
transition and retain every still-valid lease. Add no restart grace state; workers
retry through a short outage and ordinary timeout semantics cover a long one.

Do not create a Worker entity or Worker FSM. Every claim gets a random `run_id`.
Heartbeat and completion must include that `run_id`, which is enough to reject a
stale process after timeout and reassignment.

Use heartbeat loss as the only abandoned-run recovery mechanism. Do not migrate
the separate task-execution timeout, `eta_max`, `start_heartbeat=False`, or their
branches and configuration. Labtasker detects a disappeared client; task-level
wall-clock deadlines belong in the task program or an external process supervisor.

Generate `run_id` in the Client before claim and send it with the single route.
Retry one logical claim at most three times with that same token; the Server
returns the same active Task after a lost response instead of claiming another.
Recovery requires the exact same Queue and route; reuse of an active token with a
different claim request conflicts. An explicit empty response ends that attempt
and the next idle poll uses a new token. Use one global
`heartbeat_timeout=300` seconds with a fixed 60-second Client interval and return
`lease_expires_at` from claim/heartbeat; add no Queue/Task/Worker override.
Heartbeat transport uncertainty alone does not revoke locally; only an explicit
Server stale response does. Passing the observed
`lease_expires_at` is not a Client-side cancellation trigger. This can permit
duplicate computation during a partition, but old-run Task/result writes remain
fenced, managed run directories remain isolated, and arbitrary external side
effects remain user-code responsibility.

Run the single-purpose expiry scan every 60 seconds at startup/background and do
not fold recovery into claim. Treat lease expiry as a hard Server-time boundary:
every claimant action requires an unexpired matching run, and a late request may
atomically perform the same expiry transition before returning finalized/stale.
Use terminal action `heartbeat_expired` and stable latest-error type
`HeartbeatTimeout`, with its occurrence time equal to the Server transition time.

Once user execution has ended, keep heartbeat active and retry the same
idempotent terminal action with backoff until accepted/deduplicated, explicitly
stale, externally terminated or rejected as a non-retryable protocol error. Do
not claim another Task or impose a public terminal-report timeout while an
expensive result remains unresolved.

Define strict terminal wire bodies: complete carries `run_id + result`, fail
carries `run_id + {type,message,traceback}`, and unclaim carries only `run_id`.
The Server supplies failure time, attempt and run identity. First acceptance and
same-action dedupe return 204 with no Task body; contradictory/stale actions
return stable conflicts, and the first terminal payload wins without a hash.

Use `attempt` and `max_attempts`, with `max_attempts=3` meaning at most three total
charged executions. Claim increments `attempt`; transient recovery rolls back only
that claim's increment; ordinary failure, fatal worker failure and heartbeat loss
retain it. A retryable charged failure or transient recovery goes to the end of
its priority class. Manual requeue always resets `attempt` to zero. Do not add
retry backoff, retry policy objects or a reset/preserve option.

Use exactly `pending`, `running`, `succeeded`, `failed`, and `cancelled`. Cancel is
valid for pending/running Tasks, idempotent on cancelled, and preserves attempt,
diagnostics and result; cancelling running invalidates its `run_id` without yet
defining how local user code stops. Requeue is valid for pending/failed/cancelled
Tasks and resets attempt, pending position and `last_error` while preserving user
data and the latest-run summary. Running rejects requeue. Rerunning a succeeded
experiment creates a new Task.

Return the resulting Task from cancel/requeue in Python, HTTP and CLI. Delete is
allowed and idempotent for every non-running Task, returning HTTP 204 and Python
`None` with no CLI stdout; a running Task must first be explicitly cancelled.

Keep failure diagnostics out of experiment output. The 2.0.0 initial release stores only the latest
charged failure as structured Task `last_error`; transient recovery and cancel do
not overwrite it, while manual requeue clears it. Do not add a persistent
run/attempt-history table before a real diagnostic workflow requires one.

When claim finds no eligible Task, the client polls for a bounded grace period
before exiting normally. `idle_timeout` defaults to 300 seconds, accepts zero for
immediate exit, and has no infinite mode. Validate it as a finite non-negative
non-Boolean number and reject null. A successful claim resets that timer.
Keep polling cadence internal; do not add idle Worker registration, idle
heartbeat, server long-poll or SSE merely to implement this grace wait.

Treat one decorated-function invocation or `labtasker loop` command as one
dedicated local Worker process. It executes at most one Task at a time and reuses
its fixed code, loaded models and ordinary function arguments across Tasks; the
server stores no Worker resource. Losing ownership of one run must therefore be
handled at current-Task scope rather than being assumed to invalidate the whole
Worker process. A confirmed stale heartbeat stops command child processes and
lets the parent loop continue. Inline Python uses a cooperative cancellation
event and waits for natural return by default. A finite explicitly configured
force-stop timeout terminates a non-cooperative dedicated Worker process when it
expires; null creates no deadline. Cooperative code may replace the current
run's force-stop timeout through an explicit setter for cleanup. Do not
use asynchronous exception injection or per-Task Python subprocesses. The public
names are `force_stop_timeout` (null by default),
`cancellation_requested()` and `set_force_stop_timeout(seconds)`. Python accepts
a null Worker/current-run timeout to wait naturally; command mode also waits
naturally when the option is omitted and accepts a finite non-negative timeout
when explicitly supplied. Reject booleans, NaN, infinities and negatives; only
this force-stop timeout accepts null. The pure query and setter require an active Task
context. A current-run setter replaces its timeout before or after revocation,
and the resulting deadline is anchored at revocation time so repeated calls do
not silently renew it. After successful finish, `cancellation_requested()` is
false, `set_force_stop_timeout()` raises because the run is no longer cancellable,
and `task_info()` remains available through local cleanup.

Create a distinct local journal for every claimed `run_id` under
`.labtasker/runs/{queue}/{task-name-slug}__{task_id}/` and name its run directory
with UTC start time, attempt and run ID. Store an immutable claim snapshot,
phase/ack journal, exact terminal payload and combined execution log. Persist the
payload and atomically advance the journal through
running/reporting/acknowledged or revoked on a best-effort basis, and expose the path as
`TaskInfo.run_dir` and `LABTASKER_RUN_DIR` without changing CWD. This is a
Worker-observed local record and a future recovery substrate, not a Server mirror
or an implemented replay mechanism. A terminal journal write failure is only a
warning and never blocks or changes the authoritative Server action. Add no
automatic retention, compression or cleanup, and do not claim ownership of
arbitrary artifact paths or external trackers selected by user code.

Limit Task name to 256 Unicode code points without normalization. Derive the
journal slug deterministically from Unicode alphanumeric runs, cap it at 80 UTF-8
bytes on a code-point boundary and retain the complete name only in Task data;
the appended Task ID remains filesystem identity. Reject Unicode `Cc` control
characters in Task name while leaving ordinary JSON string values unaffected.

Treat initial run-directory/task-snapshot creation as required execution setup.
If it fails after claim, do not start user code: best-effort unclaim and exit the
Worker nonzero. This is distinct from terminal journal updates, whose failure is
only a warning and never blocks the authoritative Server action.

Expose only `@loop(route="default", queue=None, idle_timeout=300,
force_stop_timeout=None)` and require the parenthesized decorator form. Add no
Client/filter/heartbeat/binding/Task-timeout options. `task_info()` returns a
flat frozen local `TaskInfo` with public Task fields plus claimant-only `run_id`
and `run_dir`. It and the other execution-context helpers raise `RuntimeError`
outside an active Task. `finish(result=None, skip_if_no_labtasker=False)`
immediately completes with the supplied JSON object, or `{}` when omitted, and
remains strict by default; an explicit true value no-ops only when no execution
context exists so the same training code can run standalone. Retain this v1 name
rather than adding `allow_standalone`, but make the default strict. It never skips
validation, transport or Server failures; do not recommend broad RuntimeError
catching. A second call is an explicit RuntimeError.

Preserve v1's useful command-child completion model. `labtasker loop` supplies
the effective URL/token, Queue, Task ID, run ID, route and run directory through
`LABTASKER_*` environment variables. The child can reconstruct `task_info()` and
call the same immediate `finish()`. Its shared journal can preserve a payload for
parent takeover, but local backup is best-effort and never coordinates or gates
Server correctness. Keep heartbeat active until the
terminal report resolves. If complete wins first, heartbeat recognizes the same
`last_terminal_run_id` and `action=complete` through an explicit Server
`run_finalized` response, so correctness does not depend on writable local files.
When a result was persisted and the child exits while still reporting, the parent
retries the same stored payload; otherwise that optional recovery path is simply
unavailable. If no finish call occurs, zero exit completes with `{}` and nonzero
exit fails; once finish succeeds, later shutdown, hanging cleanup or exit status
cannot rewrite the succeeded Task. Keep `task_info()` available through local
executor return and add no separate `executor_exited_at` field.

Support single-node distributed training by documenting and testing exactly one
topology: an outer Labtasker command Worker claims one Task and launches one
`torchrun` or `accelerate launch` process group. Only the outer Labtasker process
owns heartbeat and terminal orchestration; launcher ranks inherit argv/context
but importing the client starts no background work. Treat launcher zero/nonzero
status through the ordinary command contract and terminate its local process group
on confirmed revocation.

Make the exec boundary explicit: a fork child has only its calling thread and
exec replaces its transient memory before the launcher creates ranks, so no
heartbeat thread is copied into them. Close unrelated descriptors, pass only
intentional stdio/PTY handles and use subprocess session/process-group parameters
instead of Python `preexec_fn`.

Require user code to select exactly one explicit result reporter with its
framework's main-process API. Do not make `finish()` implicitly rank-aware or use
rank calls as result reduction. Before claim, reject a nested loop in an inherited
active Task context and reject a recognized `WORLD_SIZE > 1` environment carrying
`RANK` or `LOCAL_RANK`; use this only as an actionable misuse guard. Do not add a
launcher-variable registry or override.

Defer persistent distributed Python Workers that keep ranks alive across Tasks.
They require Task broadcast, cross-rank failure aggregation, cancellation and
poisoned-process-group recovery, none of which is justified for the single-node
experiment-launch workflow.

Keep a fake multi-rank launcher test in the ordinary PR suite, covering one
claim/heartbeat owner, passive child imports, input propagation, result ownership,
exit mapping, cancellation and misuse guards. Put real single-node torchrun and
Accelerate executions in a separately marked scheduled/release integration suite
so PyTorch is not a client runtime or general unit-test dependency.

After revocation, ordinary cleanup exceptions are local diagnostics rather than
server Task failures and the Worker continues. `FatalWorkerError` still exits an
unsafe Worker. It reports fail only while the run remains active; after finish it
exits locally without changing the succeeded Task. An explicitly configured
force-stop deadline terminates the Worker nonzero when it expires; the default has
no deadline.

Validate config, authentication, Queue, route/timeouts and static Python binding
before the first claim. Pre-claim or exhausted claim-transport failure terminates
the Worker without touching a Task. Idle timeout is the only normal automatic
end: Python returns `None`, CLI exits zero. Ordinary Task outcomes continue.
Use conventional statuses 1 for Worker failure, 2 for CLI usage and 130 for
KeyboardInterrupt, while preserving OS signal status and treating command-child
nonzero as a Task rather than Worker failure. Re-raise KeyboardInterrupt after
best-effort unclaim, do not catch SystemExit or install SIGTERM handling, and
when FatalWorkerError is raised before finalization, resolve fail and then
re-raise it; after finish, re-raise it without another Task action.

Enforce one stable execution FSM guard on the Server: complete/fail/unclaim may
transition only `running + matching active_run_id`. Once complete succeeds, no
later exception, heartbeat or exit code can rewrite succeeded; post-finish
ordinary errors are local diagnostics, while post-finish FatalWorkerError only
terminates the Python Worker.

Keep three retry domains explicit. The Server owns only Task
`attempt/max_attempts`; exhaustion fails that Task and the Worker continues. The
Client owns bounded HTTP transport attempts; exhausted claim/startup transport
exits the local Worker. External supervision owns process restart. Server storage
contains Task state plus active-run fencing/heartbeat/deduplication/latest-run
fields, but no worker ID/row/status/resources/process heartbeat/restart counter or
remote lifecycle command. Claim route is matching input and `last_route`
observability, not Worker registration.

Do not add `max_tasks`, `once`, `stop_after_current`, `daemon` or automatic
restart. Remote graceful stop would require a Worker control plane; daemon/restart
belongs to external supervision; bounded execution counts have no demonstrated
workflow. `idle_timeout=0` exits only after an explicit empty claim and is not a
promise to execute exactly one Task.

Replace `summary` with an always-object `result`, defaulting to `{}`. Python return
values have no implicit result meaning; persist output only through immediate
explicit `finish(result={...})`, atomically with succeeded completion. A Python
normal return, command exit zero without `finish`, or `finish()` without an
argument writes `{}` as the complete result rather than inheriting an older value;
a second call is rejected. Ordinary Task update
may replace the complete result object only while the Task is not running; there
is no incremental merge API. Store the latest charged failure separately as
`last_error` with type, message, optional traceback,
timestamp, attempt and run ID. Retain it after a later successful retry and clear
it on manual requeue. Represent it in the Client as frozen public `LastError`,
distinct from the Worker exception `TaskError`. Do not implement incremental
metric/result updates in 2.0.0 initial release.

Before an official Client fail report, serialize the diagnostic. If it would
exceed 1 MiB, send a fixed compact fallback preserving only the original
exception type, a message pointing to local `run.log`, and null traceback. Keep
the complete traceback in ordinary local logging; do not let an oversized
diagnostic strand the run until heartbeat expiry or add partial-truncation knobs.

Expose one compact latest-run summary on every public Task: nullable `last_route`,
`started_at` and `finished_at`. Creation leaves all three null. Claim records its
route and start time and clears the finish time; complete, fail, unclaim,
heartbeat-expiry recovery and running cancellation record the finish time. A
pending cancellation with no run, manual requeue and ordinary Task update preserve
the summary, while the next claim overwrites it. A non-null timestamp pair is a
coarse server-observed duration, including heartbeat detection delay where
applicable; it is not a process-lifetime guarantee. Because routes remain editable,
historical `last_route` may differ from the current route set. Refresh `updated_at`
for lifecycle transitions, requeue and effective ordinary updates, but not for
ordinary heartbeat renewal. Do not add Run history merely to retain older values.

## Next major feature: explicit routing

After the atomic claim and `run_id` foundation is stable, implement explicit
routing as the next major refactor feature. Routing remains inside one queue; it
must not turn queues into worker classes or grow into a resource scheduler.

The routing contract has only two fields:

```text
Worker claim:
  route: str

Task:
  routes: non-empty set[str]
```

A worker may claim a task exactly when its single route is a member of the task's
route set, in addition to the ordinary queue, state and claim conditions:

```text
eligible(task, claim) =
  task.status == pending
  AND claim.route IN task.routes
```

`route` is an opaque execution-compatibility label, not a persistent entity. Many
worker processes may claim with the same route. The server does not register
routes, track whether they are online, or verify that a worker really implements
the contract represented by its route.

Use an exact zero-configuration default rather than a wildcard:

```text
worker route default = "default"
task routes default  = {"default"}
```

Task routes are a non-empty, unordered set. Matching is exact and case-sensitive.
Accept only a non-empty duplicate-free `list[str]`, and store/return it in
lexicographic order. Do not coerce a scalar string, tuple, set or arbitrary
iterable. Do not add wildcards, regular expressions, negation, route priority or
fallback. An unknown route is valid; its tasks remain pending until a matching
worker claims them.

### Why routing belongs to tasks

Starting a new worker must not implicitly redirect old pending work. A worker
chooses one identity when it starts; tasks contain the complete, explicit set of
identities allowed to execute them. For example:

```text
old worker: route = sdxl
new worker: route = sdxl-v2

new-only task:       routes = {sdxl-v2}
new-or-old task:     routes = {sdxl, sdxl-v2}
old task migrated:   {sdxl} -> {sdxl, sdxl-v2}
```

This supports rolling codebase upgrades without making a new worker unexpectedly
steal an old backlog. If a new worker should help with old tasks, that decision is
materialized by explicitly adding its route to selected pending tasks.

A route should name an execution equivalence class, normally a code path or
entrypoint whose implementations do not need to be distinguished by tasks.
Implementations that may require separate rollout or selection should use
separate routes, for example `diffusers-sdxl` and `comfy-sdxl`, rather than both
using `sdxl`. Sharing a route is an explicit promise that tasks do not need to
distinguish those workers. If that promise later becomes false, new workers use
new route names and pending tasks are migrated explicitly; the server does not
split an existing route automatically.

### Task route migration

Route migration uses the ordinary Task update API, not a special routing
action. Support ID-addressed `update_task(...)` and server-side filtered
`update_tasks(...)` through the shared `TaskUpdate` changes object. A supplied
`routes` field is the complete replacement set; do not add incremental
add/remove/merge operators whose outcome depends on hidden prior state. Do not
implement the batch form as a client-side list-then-update loop.

The operation must:

- modify only rows that are not running when the database mutation executes;
- be atomic with respect to claims;
- return matched and updated counts;
- validate the replacement as a non-empty deduplicated set of exact strings; and
- never mutate the route contract of a running task.

If a claim wins the transaction race, that run keeps the route under which it was
claimed and the task is excluded from the non-running mutation. A successful
claim records its route as the Task's `last_route` alongside the private `run_id`
for reproducibility.

### Routing boundaries

- Keep one unified queue for visibility, ordering, authentication and operations.
- Do not create Route, Provider or Worker registry tables.
- Do not model CPU/GPU quantities, capacity, placement, fairness or reservation.
- Do not let one worker advertise a list of routes; compatibility expansion is an
  explicit task mutation, not an implicit worker subscription.
- Remove worker-side claim filters from the routing contract. Query filters remain
  useful for listing tasks and selecting non-running tasks for explicit batch updates,
  but they are not hidden runtime routing policy.
- Treat argument-shape validation, including the v1 "No More, No Less" behavior,
  as a separate input-contract decision. Explicit routes own execution eligibility;
  parameter binding must not silently become a second implicit routing system.

Use one recursive strict-JSON numeric domain everywhere: signed 64-bit integers,
finite IEEE-754 binary64 floats, and booleans distinct from numbers. Reject
NaN/infinities, numeric overflow and out-of-range filter literals in Python, CLI
and HTTP; disable nonstandard JSON constants and serializer `allow_nan` behavior.
Limit every recursive args/metadata/result value to container depth 64, with
scalars at zero and each object/array adding one; reject deeper data as
`json_too_deep` before persistence.
Require Unicode scalar values in every JSON string and key; reject lone
surrogates without repair or replacement while leaving ordinary Unicode and each
field's explicit control-character policy unchanged.

## Technology baseline

- Python 3.11+
- One `uv` monorepo workspace with two package-specific `pyproject.toml` files
- FastAPI for the small HTTP surface
- SQLAlchemy 2.x with SQLite, WAL, foreign keys and a busy timeout
- Alembic migrations from the first release
- Normal CRUD may use SQLAlchemy ORM; atomic claim remains explicit SQL
- Pydantic 2 for HTTP/client boundary models, strict configuration and
  `TaskArg` TypeAdapter validation
- httpx for the client transport and Typer for both CLIs
- pytest against real temporary SQLite files
- One server process; ordinary polling rather than long polling or SSE

Task claim must be one conditional `UPDATE ... RETURNING` statement. SQLite
contention and stale `run_id` reports need deterministic integration tests.

SQLAlchemy and Alembic are retained because they reduce schema and migration work
that otherwise becomes immediate technical debt. Repository interfaces, generic
storage abstractions and multiple backend implementations remain deferred.

Use synchronous SQLAlchemy Sessions with one explicit transaction per service
command. Keep ORM models private for ordinary CRUD, use SQLAlchemy Core/explicit
SQL for atomic claim and compiled filter expressions, and reuse the same access
layer for background expiry. Do not add SQLModel, `aiosqlite`, async repositories,
a generic Unit of Work or shared persistence/API models.

Start every mutating command with SQLite `BEGIN IMMEDIATE`; read-only commands
use ordinary read transactions. If the fixed five-second busy timeout cannot
obtain the writer lock, roll back and return `503 database_busy` rather than
retrying indefinitely inside the Server.

Make `(queue_name, task_id)` the Task primary key, allowing the same explicit ID
in independent Queues, while a global partial unique index prevents a non-null
`active_run_id` from owning two Tasks. Store args/metadata/result as sorted compact
canonical JSON text with valid-object checks and query via SQLite JSON1; avoid
SQLite JSONB/version coupling and do not expose key order as API behavior.

Store every database timestamp as UTC Unix microseconds in SQLite `INTEGER`
columns, generated only by an injectable Server clock. Convert these values to
UTC RFC 3339 on HTTP and timezone-aware `datetime` in Python. Keep one private
Task row containing identity, lifecycle, JSON payloads, priority/attempt budget,
timestamps and latest-run summary, latest error, creation hash, active lease,
latest terminal-dedupe slot and a private `pending_at_us`. Set that timestamp on
submission and every transition into or explicit requeue within pending, clear it
outside pending, and leave it unchanged on ordinary updates. Claim ordering is
`priority DESC, pending_at_us ASC, task_id ASC`; do not add a Queue ticket
counter. Keep routes only in the association table, not redundantly in the Task
row.

Use database CHECK constraints for the existing FSM invariants: nonnegative
attempt and positive max attempts; pending has pending time, no active lease and
remaining budget; running has an active run/lease and no pending time; all other
states have neither active lease nor pending time.

Back Task routes with a private `task_routes(queue_name, task_id, route)`
association table, composite FK/cascade and indexes for both per-Task loading and
`queue + route` claim lookup. It is not a Route entity. Replace a Task's complete
set transactionally, assemble the public sorted list with batched loading, and
compile route membership to indexed EXISTS/join rather than `json_each` scans.

Create only the fixed-path indexes for claim ordering, lease expiry, default and
status list ordering, active-run uniqueness, latest-terminal lookup and both
route association access orders. Do not pre-index names, arbitrary JSON paths or
every optional order field without measured query plans.

## Contract boundary

- The server owns an explicitly versioned `/api/v2` HTTP contract and OpenAPI
  document.
- Queue names are explicit in `/api/v2/queues/{queue}/...`; authentication never
  substitutes a hidden `/queues/me` identity.
- Create Tasks with client-generated IDs through idempotent create-by-ID `PUT`.
  The same normalized creation request returns the existing Task; a different
  request at that ID conflicts. Generate Task and Run IDs with `t_` and `r_`
  prefixes followed by 12 URL-safe characters from 72 secure random bits. Store
  an internal SHA-256 hash of
  canonical normalized submit JSON so later Task edits do not break recognition
  of the original request. Hard delete removes that hash and allows later reuse
  of the explicit ID; retain no tombstone or permanent used-ID registry. Do not
  add an Idempotency-Key subsystem.
- Normalize Task creation to `name=null`, empty args/metadata, priority zero,
  `max_attempts=3` and routes `["default"]`. Python `submit_task()` accepts no
  arguments; `None` for args/metadata/routes means use those defaults. Explicit
  Task IDs must match `^t_[A-Za-z0-9_-]{12}$`.
- HTTP Task creation accepts only name/args/metadata/priority/max_attempts/routes;
  reject unknown and server-owned fields. Expand defaults and canonicalize object
  key and route order before hashing, so omitted and explicit defaults identify
  the same creation request.
- Create Queues idempotently by name with `PUT /api/v2/queues/{queue}`.
- Use explicit lifecycle action endpoints instead of generic status patching, and
  return `204 No Content` for an empty claim.
- Address heartbeat, complete, fail and unclaim through
  `/api/v2/queues/{queue}/tasks/{task_id}/{action}` and carry the claimant-only
  `run_id` in the request body. Do not add `/runs/{run_id}` endpoints.
- Fence execution updates with an active `run_id` and retain only the latest
  terminal `(run_id, action)` for bounded retry deduplication. Do not add a Run
  entity, execution-history table or terminal payload hash.
- Return every API error as `{error:{code,message,details}}` with stable machine
  codes.
- Normalize request validation without a more specific documented code to
  `422 invalid_request` with located readable errors. Do not leak FastAPI's native
  validation envelope or create per-endpoint validation codes.
- Enforce one 1 MiB (1,048,576-byte) limit on every HTTP request body, returning
  `413 request_too_large`; add no separate args/metadata/result/traceback limits.
  Also enforce the same bound on canonical complete user-owned Task data after
  create, update or complete, returning `422 task_data_too_large`; this prevents
  several small patches from accumulating a large-file record.
- Client request/response types remain small and local to the client package;
  avoid importing server Pydantic models.
- Server request schemas forbid extras; Client response models ignore unknown
  additive fields but remain strict about required/known fields.
- A monorepo contract test runs the real client against the real server. After
  the first release, the release suite also runs the previous published v2 Client
  through submit/get/list/claim/report against the candidate Server.
- `/api/v2` may add endpoints, optional response fields and stable error codes;
  removing/renaming/retyping/redefining a field or adding Task states requires a
  new API version.
- Do not preflight ordinary calls through health or add capabilities/version-range
  negotiation. `/openapi.json` is the only generated machine schema; do not
  commit a generated SDK or create a second shared wire package.
- Expose unauthenticated `/health` with one real database check and an exact
  status/API-version/database shape, plus unauthenticated `/openapi.json`. Return
  a redacted 503 health result on DB failure, add no capability list and disable
  Swagger/ReDoc HTML while authenticating every `/api/v2` endpoint.
- Importing the client performs no network access or global hook installation.
- Make top-level functions the primary Python API. Also expose a synchronous
  context-managed `Client` for pooled batch submissions, multiple servers and
  deterministic cleanup; top-level functions delegate to one lazy default Client
  without import-time configuration, network access or `atexit` hooks. Name its
  constructor inputs `url`, `token` and `queue`; do not add a `base_url` alias.
  `None` continues through environment, CWD config and built-in fallbacks for
  every constructor field, including token. Resolve and snapshot once at explicit
  construction or at the first top-level call that creates the lazy default
  Client; add no live config reload/reset behavior. Make explicit `close()`
  idempotent and context-managed; operations afterward raise exactly
  `RuntimeError("Client is closed.")` and never reopen. Do not expose close/reset
  for the lazy default Client.
- Export every documented ordinary resource function—including `submit_task` and
  `count_tasks`—plus the documented models, types, Worker decorator/helpers and
  exceptions from the `labtasker` package root. Keep claim/heartbeat/terminal
  Worker protocol calls internal to `loop`; independent executors use the public
  HTTP contract rather than a second low-level Python convenience API.
- Resolve optional Queue configuration per call, then Client, environment, CWD
  `.labtasker/config.toml`, and finally `default`. Return Tasks/pages directly
  instead of HTTP response wrappers, and preserve server error codes through a
  small structured Client exception hierarchy.
- Parse one strict flat TOML client file through Python 3.11 `tomllib`, with only
  optional string keys `url`, `queue` and `token`. Reject unknown, duplicate,
  empty or ill-typed values; apply the same validation to environment variables.
  Accept absolute HTTP(S) base URLs without userinfo/query/fragment, preserve an
  optional path prefix and normalize away a trailing slash. Omitting `token`
  sends no Authorization header; a present empty token is invalid. If the new CWD
  config is absent but v1 `.labtasker/client.toml` exists, fail with
  `legacy_config_found` before other resolution rather than parsing, migrating or
  silently ignoring it. Do not enforce config-file permission bits; recommend
  the environment variable for remote credentials and never log the token.
- Keep Queue as a name-only resource. Expose create/list/delete in Python, HTTP
  and CLI; return one Queue, an unpaginated Queue array and no deletion value.
  Remove `get_queue`, item GET and `queue get` because there is no other Queue
  representation to retrieve.
- Fix the client CLI tree to full-name Task and Queue actions, `loop`, and
  read-only `config show`; keep `labtasker-server serve` in the Server package.
  Add no command aliases, Worker/Event/Admin commands or config mutation command.
- Put `--queue` on each relevant Task leaf command and `loop`, not in a second
  global position. Provide no CLI URL/token flags; environment variables handle
  one-off connection overrides. Make `config show` network-free and output only
  effective URL, Queue and a token-present boolean, never the credential.

## Parsers and expression languages

Keep explicit language contracts, but use machinery proportionate to each
language.

- Compile one Pydantic `TypeAdapter(annotation)` per annotated `TaskArg` before
  claim and call `validate_python(..., strict=True)` for selected, default and
  resolver outputs. Unsupported annotations are startup errors. Pydantic models,
  dataclasses and custom schemas retain their own strict-schema behavior; use an
  explicit resolver for application-specific conversion. Add no second
  custom/coercive typing validator.
- Replace the command-template ANTLR grammar, generated artifacts and vendored
  runtime with a compiled deterministic scanner. The language is regular,
  nonrecursive and fail-fast; define it completely with EBNF, a transition table
  and conformance tests rather than regex replacement or ad-hoc splitting. Do not
  retain an unused `.g4` file as a second source of truth.
- Accept only `labtasker loop [OPTIONS] -- COMMAND [ARG...]`, require the `--`
  boundary, resolve each template independently and execute the resulting argv
  directly. Delete `--command`/`--cmd`/`-c`, `--script-path`, stdin command input,
  `--executable` and built-in shell mode. Users can explicitly execute `bash -lc`
  or a script when they genuinely want shell semantics.
- Replace the v1 `%(...)` form with `%{...}` and use `%{{` as the literal `%{`
  escape. This leaves `%%` unchanged and lets `%%{a}` mean a literal percent
  followed by interpolation. Reuse the object-only path from `TaskArg`, with
  segments restricted to `[A-Za-z_][A-Za-z0-9_]*`; reject numeric segments,
  whitespace, hyphens, Unicode identifiers, array indexes, wildcards and escapes.
- Compile and syntax-check every argv template before the first claim. Treat a
  missing key, non-object intermediate or resolved NUL as a claimed Task's binding
  failure; never start the child after such a failure. Require precise 1-based
  argv-element/code-point diagnostics for static syntax errors.
- Preserve argv boundaries: one input template always produces one output
  element and is never word-split again. Insert strings exactly and encode every
  other JSON value as deterministic compact JSON with UTF-8 preserved and object
  keys sorted. Allow embedded/multiple placeholders, empty elements and every
  JSON value; reject NUL and missing paths as Task binding failures.
- Inherit the Worker environment, then overwrite the reserved `LABTASKER_*`
  execution context and remove `LABTASKER_TOKEN` when authentication is disabled.
  Add no `--env` syntax: static values belong on the Worker process, while a
  platform launcher or wrapper can express dynamic values (for example POSIX
  `env 'LR=%{lr}' python train.py`).
- Expose no PTY flag. On POSIX, automatically use an internal PTY only when the
  Labtasker process itself has interactive stdin/stdout/stderr; otherwise use
  concurrently drained subprocess pipes, including on Windows v2. Relay output
  live as raw bytes and copy both modes without decoding to `run.log`. PTY
  preserves direct-terminal buffering, input, progress, prompt and combined-stream
  behavior; noninteractive pipes use null stdin and preserve separate output
  streams but cannot force arbitrary child programs to flush. Add no separate
  Task-input protocol.
- Do not support both old and new placeholder syntaxes in v2. Keeping one syntax
  makes errors and documentation unambiguous.
- Test scanner golden cases, overlapping percent/opening sequences, exact error
  locations, generated valid templates and arbitrary Unicode fuzz input. Require
  every loop iteration to advance and preserve O(n) behavior. Use v1 parser tests
  as a migration checklist, not as proof of the intentionally changed v2 syntax.
  Reconsider a parser generator only after an explicit design decision adds
  nesting, quoted keys, operators or recovery.
- Keep the Python-AST allowlist approach for task query and batch-selection
  filters. It provides familiar syntax without `eval` and rejects unsupported
  syntax explicitly. Do not reuse these filters as worker-side claim routing.
- Bound every filter to 8192 UTF-8 bytes before parsing and return
  `filter_too_large`; expose no additional AST depth/node-count settings.
- Name the expression `filter` consistently in Python, CLI and HTTP. Do not add
  public `where` or `query` aliases.
- Preserve the query transpiler tests as a behavior specification.
- Replace only the MongoDB code-generation backend. The server transpiler should
  produce SQLAlchemy expressions for SQLite while preserving the supported query
  language.
- Keep parsing, validation and backend translation as separate stages so syntax
  behavior is not tied to a database implementation again.

The first release supports comparisons, `and`/`or`, `in`/`not in`, and
`exists(path)`/`missing(path)`. It deliberately omits general unary `not`.
Comparisons contain exactly one path and one scalar literal; reject path-to-path,
chained and structured-value comparisons. Dynamic JSON ordering is numeric only,
while built-in timestamps accept validated RFC 3339 strings. Statically invalid
built-in-field comparisons are filter errors; an incompatible value on a dynamic
JSON row simply does not match.
Membership admits only `path in [scalar literals]` and `scalar literal in path`,
plus their guarded `not in` forms. These spellings declare scalar-path and
array-path expectations respectively. Reject every other operand shape instead
of guessing an intended containment operation. A dynamic row with the wrong
runtime shape does not match either the positive or negative form.
Do not overload `in` for object-key presence: callers use `exists(path)` or
`missing(path)`. A dynamic object value never changes an array-containment
expression into a key lookup.
Every ordinary comparison and membership predicate requires its referenced path
to exist; an absent path does not match even `!=` or `not in`. Callers include
absent paths explicitly with forms such as `missing(result.acc) or
result.acc < 0.9`. Explicit JSON null is distinct from absence: `exists(path)`
includes null, while `missing(path)` is true only for absence.

Include `last_route`, `started_at` and `finished_at` among filterable built-ins.
Fixed built-in fields always exist even when null, so callers use
`started_at != None` rather than `exists(started_at)` to test whether a value was
recorded. Allow one `order_by` from `id`, `name`, `status`, `priority`, `attempt`,
`max_attempts`, `last_route`, `created_at`, `updated_at`, `started_at` or
`finished_at`; sort nulls last in both directions and use `id` as the stable
tie-breaker. Do not add JSON-path/multi-field ordering or a virtual duration
field. Callers derive coarse duration from the latest non-null timestamp pair.

Comparisons use strict JSON types without implicit coercion: booleans and
numbers are distinct, strings are not converted to numbers, and integer/float
spellings share the bounded JSON number domain above. Ordering additionally requires a
compatible non-null value. Array membership requires an existing array-valued
path; missing, null and wrong-container values do not satisfy either `in` or
`not in`.

Implementation tests must cover the absent/null/value truth table, guarded
negative comparisons, strict type boundaries and explicit missing-path
inclusion. The SQLite backend must distinguish absence from JSON null with JSON
type/existence checks instead of inheriting SQL null behavior. Remove regex and
natural-language date helpers rather than carrying their complexity forward.
Parser rigor is valuable; language expansion remains demand-driven.

Only listing, counting and non-running Task update consume filters initially. Batch update
requires an explicit filter, applies server-side rather than through pagination,
and returns matched/updated counts. Cancel, requeue and delete remain ID-addressed,
and the update surface cannot patch status or run ownership. Supplied object/list
fields use complete replacement; do not retain v1 merge/replace switches or add a
dot-path patch language.

Ordinary Task update writes exactly `name`, `args`, `metadata`, `priority`,
`max_attempts`, `routes` and `result`. Identity, status, attempt, `last_error`,
timestamps and run-fencing/deduplication fields remain server-owned. Refresh
`updated_at` after an effective update. Reject a pending Task update unless the
new `max_attempts` remains greater than its current `attempt`; non-pending Tasks
only require a positive value because requeue resets `attempt`.

Represent update data as one strict JSON object described in Python by a
typing-only `TaskUpdate` `TypedDict`; callers pass normal dicts. Use
`update_task(task_id, changes, *, queue=None) -> Task` and keyword-only
`update_tasks(filter=..., changes=..., queue=None) -> BulkUpdateResult`. Empty,
unknown, server-owned or wrongly typed fields are validation errors; only `name`
accepts null.

Expose `PATCH /api/v2/queues/{queue}/tasks/{task_id}` with a direct changes body
and collection `PATCH /api/v2/queues/{queue}/tasks` with `{filter, changes}`.
The CLI uses positional ID or `--filter` plus one strict `--changes` JSON object;
remove v1 `-u field=value`, per-field flags and replace/merge switches.

List Tasks through keyword-only `list_tasks(status=None, name=None, filter=None,
order_by="created_at", descending=True, limit=100, cursor=None, queue=None)`.
Exact `status` and `name` shortcuts are ANDed with the general filter; ID lookup
belongs to `get_task`, not list. Return one frozen `TaskPage(items, next_cursor)`
and never auto-fetch later pages. Bound `limit` to 1–1000. The stateless opaque
cursor binds the Queue, selection and ordering inputs plus the last position; a
mismatch is `invalid_cursor`, although the next request may choose a different
page size. CLI list prints that same page as two-space-indented UTF-8 JSON and
does not offer table, pager, TTY-dependent or IDs-only alternatives.
Each page is a point-in-time query, not part of a cross-page database snapshot;
concurrent mutations may move rows across a cursor boundary. Add no snapshot ID,
pagination transaction or server-side cursor session.

Expose `count_tasks(status=None, name=None, filter=None, queue=None) -> int`,
`GET /api/v2/queues/{queue}/tasks/count` returning `{"count": n}`, and
`labtasker task count` printing that object as formatted JSON. Reuse the exact
list selection semantics but accept no ordering, pagination, grouping or route
aggregation. Do not add `total` to every `TaskPage`; counting is an explicit
query whose transaction provides only a point-in-time snapshot.

Validate every non-running batch match before writing and roll back the whole
batch on a state-dependent invariant conflict. Only rows that concurrently become
running are excluded. Use last-write-wins with no revision/ETag/If-Match in 2.0.0 initial release,
and do not automatically retry either update call.

For ordinary Client transport, use at most three attempts only for read-only
GET/list/count calls and exact create-by-Task-ID PUT. Do not automatically retry
cancel, requeue, Task delete, single/batch update or Queue create/delete: even an
endpoint that is idempotent in one state can cross a concurrent explicit state
change. Return `TransportError` for an uncertain mutation outcome and leave
inspection/retry to the caller rather than adding revision tokens, operation IDs
or tombstones.

Keep the Client error hierarchy small. `TransportError` with fixed code
`transport_error` covers network/timeouts and malformed or schema-incompatible
protocol responses; a valid Server error envelope, including 5xx, remains
`APIError`. Do not add `ProtocolError`.
For retry-eligible reads and exact Task create PUT, retry only `TransportError`
and exact Server code `database_busy`, up to three total attempts; do not retry
other valid API errors.

Give `ConfigError` exactly `invalid_config` and `legacy_config_found`. Use the
readable message and source/field details to distinguish parser, key, type and
value failures instead of adding exception subclasses or more codes.

Use the same submit surface across the function API and Client:
`submit_task(args=None, *, name=None, metadata=None, priority=0,
max_attempts=3, routes=None, task_id=None, queue=None) -> Task`. CLI submit keeps
typed scalar flags, strict JSON-object `--args`/`--metadata`, repeatable `--route`
and optional `--id`; remove trailing shorthand and emit exactly one Task JSON
object on success.

## Event-system decision

Do not migrate the current in-memory EventManager, FSM event handles or direct
publish calls.

Events are not required for the first runnable release. Task listing and status
polling cover the core experiment workflow, so 2.0.0 initial release contains no public SSE
endpoint and no generic event bus.

If real automation use requires events, add one append-only `task_events` table:

- A task mutation and its event row are committed in the same SQLite transaction.
- Each event has a monotonic integer `event_id`, queue/task IDs, transition,
  `run_id`, timestamp and small JSON payload.
- The event table is the source of truth; an in-memory queue may only wake
  listeners and may never own delivery state.
- SSE is a transport adapter over `task_events`, supports `Last-Event-ID`, and
  replays rows after that cursor.
- Delivery is at least once; consumers deduplicate by `event_id`.
- Retention is explicit and independent of live delivery.

Do not add a generic EventBus, plugin callbacks, external broker or transactional
outbox. With one SQLite database, the event-log row itself provides the required
atomicity. Add Kafka/Redis-style delivery only when an actual consumer requires it.

## Testing strategy

- Pure tests for state transitions and retry counting.
- SQLite independent-connection tests for atomic claim, two concurrent claimers,
  same-run replay and route conflict, completion versus expiry, stale terminal
  retry versus a new run, update versus claim, cancel versus complete,
  heartbeat-loss recovery and schema upgrade.
- A few API tests for submit/list/claim/report and OpenAPI compatibility.
- Count tests compare the explicit count with all cursor pages under the same
  status/name/filter selection, and request-limit tests cover exact-boundary,
  declared-oversize and cumulatively received oversize bodies. Size tests also
  prove that multiple PATCH requests cannot exceed the canonical stored-Task
  bound, and an oversized official failure diagnostic reaches `fail` through the
  fixed compact fallback rather than heartbeat expiry.
- Boundary tests cover tokenless Authorization ignore versus uniform authenticated
  401s, idempotent/use-after-close Client behavior, 256-code-point names and
  80-byte Unicode-safe slugs, and int64/finite-float acceptance plus NaN,
  infinity and overflow rejection through Python, CLI, HTTP and filters.
- Binding/boundary tests use real strict Pydantic TypeAdapters, reject Task-name
  `Cc` controls, verify depth 64/65 recursively on every Task JSON surface, and
  cover tokenless IPv4/IPv6 loopback plus case-insensitive localhost while
  refusing wildcard and other hostname binds without a token.
- Boundary tests reject lone Unicode surrogates in every JSON string/key path,
  exercise filter sizes immediately below/at/above 8192 UTF-8 bytes, and verify
  finite-command JSON stderr versus human-readable usage/`loop` diagnostics.
- Transport tests prove that only reads/create-by-ID retry, mutations do not;
  cover ID reuse after hard delete, malformed response mapping to
  `transport_error`, and pagination behavior under both static and concurrently
  mutated data without asserting a cross-page snapshot.
- Validation tests cover the generic `invalid_request` envelope and location
  paths, the two ConfigError codes, exact `database_busy` retry selection, and
  finite/non-negative/non-Boolean timeout boundaries including zero and null.
- A real client-to-server contract test prevents the two packages from drifting.
- One end-to-end test that submits tasks and runs two client processes.

Do not add mocks for the database, multi-layer marker systems, probabilistic
stress tests, contract frameworks, or broad coverage targets.

## Delivery order

1. Build and test the SQLite task table, atomic claim and `run_id` fencing.
2. Implement explicit routes in submit/claim plus atomic non-running route
   migration as the next major feature.
3. Add the complete initial HTTP resource and Worker-protocol endpoints defined
   by the spec, without deferred surfaces.
4. Build the separate client package: configuration and models, all documented
   Task/Queue Python and CLI operations, then the Python/command Worker loop and
   local journal.
5. Run the contract, concurrency, launcher and real experiment end-to-end suites.
6. Publish both 2.0.0 distributions and wait for actual usage before adding
   anything else.

## Explicitly deferred

- Multiple database backends or repository interfaces
- PostgreSQL
- Authentication beyond a single optional shared token
- Events, SSE and outbox
- New query-language features beyond the existing supported subset
- Plugin system
- Worker registry
- Web UI
- Async database layer
- Results analytics
- Full v1 compatibility
