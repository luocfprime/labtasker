# Python API

The public `labtasker` package is synchronous and typed. Every resource
operation is available both as a package-level function and as a method with the
same name on `Client`. Methods return Labtasker domain models, not HTTP response
wrappers.

The `labtasker-server` distribution has no supported embedding API. Operate it
through `labtasker-server` or the documented HTTP API; importing
`labtasker_server.app.create_app` or other Server modules is internal use.

## Choose the Client form

Package-level functions share one lazily created process-wide Client:

```python
import labtasker

task = labtasker.submit_task({"seed": 7}, routes=["sdxl"])
page = labtasker.list_tasks(status="pending")
```

Use an explicit Client for a large submission loop, deterministic cleanup, test
isolation, or more than one Server:

```python
from labtasker import Client

with Client(url="https://labtasker.example", token=token, queue="paper") as client:
    task = client.submit_task({"seed": 7}, routes=["sdxl"])
```

`Client(url: str | None = None, socket: str | Path | None = None,
labtasker_root: str | Path | None = None,
auto_start_local_server: bool = False, token: str | None = None,
queue: str | None = None)` resolves the root from
its explicit argument, `LABTASKER_ROOT`, then exact `CWD/.labtasker`. It resolves
one endpoint from the first explicit, environment, or root-config URL/socket
layer and otherwise selects managed local. Labtasker does not search parents or
VCS roots.

The default managed-local Client only connects to its derived Unix socket. Set
`auto_start_local_server=True` to authorize that Client to create or recover the
standard local daemon when the first connection fails. This option is invalid
with an HTTP URL or explicit socket. Repeated and concurrent authorized calls
reuse one matching daemon. Resolution happens once when the Client is
constructed; later `chdir()`, config, or environment changes do not retarget it.
A non-null `queue=` on a Task method overrides only that operation's Queue;
changing Servers requires a new Client.

`close()` is idempotent and never stops a local Server. Operations on a closed
Client raise `RuntimeError("Client is closed.")`. The package-level default
Client has no close/reset API. There is no asynchronous Client.

`Client.server_version` is a read-only `str | None`: the normalized PEP 440 Server
package version from the latest business response. It is `None` before a
response or when that response has no usable version header. Reading it never
makes a request. Older Servers may not advertise their version.

Resolved endpoint, credential, Queue, root, and auto-start configuration is
private implementation state, not a supported `Client` property. Pass those
values explicitly when constructing a Client; use `labtasker config show` for a
non-secret diagnostic view of current CLI resolution.

When a response reports a Server older than the Client, the Client writes an
advisory `warning` to stderr recommending an upgrade. Each Client instance warns
once per distinct older Server version, including patch and prerelease
differences. Results, exceptions, and retries are unchanged; the warning does
not mean the current operation is incompatible. There is no version preflight or
automatic fallback. Applications needing feature-specific compatibility checks
must account for `server_version` being unknown and still handle operation errors.

## Public package imports

The supported package-root import surface is `labtasker.__all__`:

```text
Client

submit_task  get_task  list_tasks  count_tasks
update_task  update_tasks  cancel_task  requeue_task  delete_task
create_queue  list_queues  delete_queue
list_workers  count_workers

loop  TaskArg  TaskInfo  task_info  finish  report_progress
report_worker_telemetry  cancellation_requested  set_force_stop_timeout

Task  TaskPage  Queue  BulkUpdateResult  LastError
WorkerObservation  WorkerPage  CountGroup  GroupCountPage
JSONValue  TaskStatus  TaskOrderField  TaskUpdate

LabtaskerError  ConfigError  TransportError  APIError
TransientError  TaskError  FatalWorkerError
```

Imports from private modules and Worker wire operations such as claim,
heartbeat, complete, fail, and unclaim are not supported Python interfaces.

## Task operations

```text
submit_task(args=None, *, name=None, metadata=None, priority=0,
            max_attempts=3, routes=None, task_id=None, queue=None) -> Task
get_task(task_id, *, queue=None) -> Task
list_tasks(*, status=None, name=None, name_fuzzy=None, filter=None, order_by="created_at",
           descending=True, limit=100, cursor=None, queue=None) -> TaskPage
count_tasks(*, status=None, name=None, name_fuzzy=None, filter=None,
            queue=None, group_by=None, limit=None, cursor=None) -> int | GroupCountPage
update_task(task_id, changes, *, queue=None) -> Task
update_tasks(*, filter, changes, queue=None) -> BulkUpdateResult
cancel_task(task_id, *, queue=None) -> Task
requeue_task(task_id, *, queue=None) -> Task
delete_task(task_id, *, queue=None) -> None
```

| Operation | Contract |
| --- | --- |
| `submit_task` | Creates one pending Task and returns it. `args` and `metadata` default to `{}`, `routes` to `["default"]`, and `max_attempts` to `3`. |
| `get_task` | Returns one Task or raises `APIError` with code `task_not_found`. |
| `list_tasks` | Returns exactly one `TaskPage`; it never auto-fetches or streams every match. Selectors are combined with logical AND. |
| `count_tasks` | Returns an `int` for the complete selection, or a `GroupCountPage` when `group_by` is supplied. |
| `update_task` | Replaces supplied user-owned fields on one non-running Task and returns the resulting Task. |
| `update_tasks` | Atomically updates all matching non-running Tasks and returns `BulkUpdateResult(matched, updated)`. A non-empty filter is required. |
| `cancel_task` | Cancels a pending or running Task. Repeating cancel on a cancelled Task is idempotent. |
| `requeue_task` | Accepts pending, failed, or cancelled; returns it to pending, resets `attempt` to `0`, and clears `last_error`. |
| `delete_task` | Permanently deletes one non-running Task and returns `None`. Deleting an absent Task is idempotent. |

### Grouped counts

Use an ordered sequence of dimensions, not a comma-separated Python string:

```python
page = client.count_tasks(status="pending", group_by=["routes", "status"])
for group in page.items:
    print(group.key, group.count)
```

Task dimensions are `routes` and `status`, singly or together in either order.
`GroupCountPage` contains `group_by`, `count`, `items: list[CountGroup]`, and
`next_cursor`. Each `CountGroup` has `key: dict[str, str]` and `count`.
The top-level count covers the complete selection. Multi-route Tasks appear in
each compatible route group, so summing groups can exceed that total.

`limit` defaults to 100 groups and accepts 1–1000; `cursor` continues one page.
Both require grouping. Groups sort by their keys in the requested dimension
order. Follow cursors with the same selection and grouping; page size may change.
Each page reads current data, so concurrent changes can affect later pages.
Empty, repeated, whitespace-containing and unsupported dimensions are rejected.
An old Server's scalar response to a grouped request raises `TransportError`.

## Worker observations

```text
list_workers(*, filter=None, limit=100, cursor=None, queue=None) -> WorkerPage
count_workers(*, filter=None, group_by=None, limit=None, cursor=None,
              queue=None) -> int | GroupCountPage
```

These methods also have package-level forms. `WorkerPage` contains `items` and
`next_cursor`, sorted by Worker ID ascending with the same 1–1000 page limit.
Each `WorkerObservation` exposes `id`, `queue`, `route`, `status`, nullable
`task_id`, `metadata`, nullable `telemetry` and `telemetry_updated_at`,
`last_seen_at`, and `expires_at`. Timestamps are UTC. Fixed fields and nested
`metadata.*` / `telemetry.*` paths support the
[query language](../guides/query.md).

```python
workers = client.list_workers(filter='route == "sdxl" and status == "idle"')
counts = client.count_workers(group_by=["route", "status"])
```

Worker grouping supports `route` and `status`, singly or together. Plain counting
returns an integer; grouped counting follows the Task page contract above.
Only unexpired observations are returned. `idle` means awaiting work; `busy`
includes execution, reporting and cleanup after `finish()`. Observations renew
periodically and can be delayed. An advisory `task_id` may refer to a terminal or
deleted Task. Use Task state for ownership and recovery decisions. Worker
observation failures never block Task execution or consume the failure guard.
There are no public Worker control methods.

## Task submission details

### Submission and idempotency

Task data must use strict JSON-compatible Python values. `args`, `metadata`, and
`result` are objects; arrays are Python lists; object keys are strings. NaN,
Infinity, cycles, arbitrary objects, and integers outside signed 64-bit range are
rejected before transport.

When `task_id` is omitted, the Client generates one before its first network
attempt. For retry safety across caller process restarts, persist a caller-chosen
ID matching `t_[A-Za-z0-9_-]{12}` and replay the complete definition:

```python
task = labtasker.submit_task(
    {"seed": 7},
    task_id="t_AbCdEf0123-_",
    name="baseline-seed-7",
    routes=["sdxl"],
)
```

The same ID and normalized definition return the Task's current representation,
even if it is now running or terminal. A different definition at that ID raises
`APIError(code="task_id_conflict")`; it never updates or overwrites the Task.
Object-key order, route input order, and explicitly supplied default values do
not change the normalized definition.

### Selection and pagination

`status`, exact `name`, fuzzy `name_fuzzy`, and `filter` are combined with AND. `limit` must be from
1 through 1000. Ordering is stable and supports `id`, `name`, `status`,
`priority`, `attempt`, `max_attempts`, `last_route`, and the public timestamps.

Name search uses `list_tasks(name_fuzzy="tr ev")` or
`count_tasks(name_fuzzy="tr ev")`. It ignores case and outer whitespace; every
whitespace-separated word must be a subsequence of the name, independently of
word order. Empty searches do not restrict names. Punctuation is literal and
ordering is unchanged. Use `name="train_model_eval"` or
`filter='name == "train_model_eval"'` for strict equality.

Follow `next_cursor` with the same Queue, selectors, filter, order field, and
direction:

```python
page = labtasker.list_tasks(filter='status == "failed"', limit=100)
tasks = list(page.items)
while page.next_cursor is not None:
    page = labtasker.list_tasks(
        filter='status == "failed"',
        limit=100,
        cursor=page.next_cursor,
    )
    tasks.extend(page.items)
```

See [Query language](../guides/query.md) for the filter grammar. A cursor is
opaque and is not a Task ID or offset.

### Updates and lifecycle

`changes` is a `TaskUpdate` dictionary containing at least one of `name`,
`args`, `metadata`, `priority`, `max_attempts`, `routes`, or `result`. Every
supplied object or list is a complete replacement; there is no merge, dot-path
patch, or add/remove operator. Unspecified fields remain unchanged.

Bulk update is one Server transaction. `matched` counts filter matches that are
still non-running at execution time; `updated` counts rows whose stored value
actually changed. A concurrent claim either sees the complete new values or wins
first and excludes that running Task. If one matched non-running Task violates a
state-dependent rule, the whole batch rolls back.

| Current state | Update | Cancel | Requeue | Delete |
| --- | --- | --- | --- | --- |
| `pending` | yes | yes | yes | yes |
| `running` | no | yes | no | no |
| `succeeded` | yes | no | no; submit a new Task to rerun | yes |
| `failed` | yes | no | yes | yes |
| `cancelled` | yes | idempotent | yes | yes |

Lifecycle is changed only through these explicit actions; `status` is never a
writable update field.

## Queue operations

```text
create_queue(name) -> Queue
list_queues() -> list[Queue]
delete_queue(name, *, cascade=False) -> None
```

`create_queue` is idempotent and returns the Queue. `list_queues` returns the
complete, unpaginated list. Deleting an empty Queue succeeds without `cascade`;
a non-empty Queue requires `cascade=True`. Deletion is rejected while any Task
in the Queue is running, even with cascade. A successful cascade atomically
deletes the Queue and every Task in it; it does not delete Worker journals or
external artifacts.

The `default` Queue is created only with a fresh database. If explicitly deleted,
it must be explicitly recreated.

## Response models

Response models are frozen, strict Pydantic models. Known fields keep stable
types; unknown response fields are ignored so a newer v2 Server may add optional
fields. Use `model_dump(mode="json")` for a JSON-ready representation. Mutating a
dict inside a returned model changes only that local object and never updates the
Server.

| Model | Public fields |
| --- | --- |
| `Task` | `id`, `queue`, `status`, `name`, `args`, `metadata`, `priority`, `attempt`, `max_attempts`, `routes`, `result`, nullable `progress`, `progress_updated_at`, `progress_attempt`, `last_error`, `last_route`, `created_at`, `updated_at`, `started_at`, `finished_at` |
| `TaskPage` | `items: list[Task]`, `next_cursor: str | None` |
| `BulkUpdateResult` | `matched: int`, `updated: int` |
| `Queue` | `name: str` |
| `LastError` | `type`, `message`, `traceback`, `occurred_at`, `attempt`, `run_id` |
| `TaskInfo` | Every `Task` field plus the active `run_id` and absolute local `run_dir` |
| `WorkerObservation` | `id`, `queue`, `route`, `status`, nullable `task_id`, `metadata`, nullable `telemetry`, `telemetry_updated_at`, `last_seen_at`, `expires_at` |
| `WorkerPage` | `items: list[WorkerObservation]`, `next_cursor: str | None` |
| `CountGroup` | `key: dict[str, str]`, `count: int` |
| `GroupCountPage` | ordered `group_by: list[str]`, complete `count: int`, paginated `items: list[CountGroup]`, `next_cursor: str | None` |

Task states are exactly `pending`, `running`, `succeeded`, `failed`, and
`cancelled`. Timestamps are timezone-aware UTC `datetime` values.

`TaskStatus` is the exact Task-state literal union. `TaskOrderField` is the
literal union of `id`, `name`, `status`, `priority`, `attempt`, `max_attempts`,
`last_route`, `created_at`, `updated_at`, `started_at`, and `finished_at`.
`TaskUpdate` is a `total=False` `TypedDict` with optional `name`, `args`,
`metadata`, `priority`, `max_attempts`, `routes`, and `result` keys; runtime
validation still requires at least one supplied field. `JSONValue` is the
recursive strict JSON-compatible value type.

## Worker API

```text
@loop(route="default", queue=None, idle_timeout=300,
      force_stop_timeout=None, max_consecutive_failures=5, metadata=None)
def worker(...): ...

TaskArg(default=..., path=None, resolver=None)
task_info() -> TaskInfo
finish(result=None, *, skip_if_no_labtasker=False) -> None
report_progress(progress, *, skip_if_no_labtasker=False) -> bool
report_worker_telemetry(telemetry, *, skip_if_no_labtasker=False) -> bool
cancellation_requested() -> bool
set_force_stop_timeout(seconds: float | None) -> None
```

Only parameters marked by `TaskArg(...)` bind from Task args. Binding is strict
and happens after claim; ordinary return succeeds with `{}`. `finish()` accepts
one JSON object and completes the Task before local cleanup continues. It is
stable once accepted and may be called only once. The context helpers require an
active Worker execution; cancellation and force-stop helpers require a Python
Worker execution.

`report_progress()` replaces the current run's latest strict JSON-object
snapshot. It returns `True` when accepted. Transport failures and Server
rejections are isolated from Task execution, log a warning and return `False`;
confirmed run finalization also updates the existing local revocation state.
Invalid JSON-compatible data or missing context raises. The Server supplies the
public report timestamp and attempt, retains the last snapshot after the run
ends, and clears it on the next claim. Reports do not renew heartbeat leases.
The object has no required business keys. `completed` and `total` form an
optional display convention used by Labtasker WebUI, not a validation rule for
the Python or HTTP API.

`metadata` is one strict JSON object fixed for the Worker invocation.
`report_worker_telemetry()` synchronously replaces that Worker's latest strict
JSON-object telemetry snapshot and returns whether the Server accepted it. It
does not renew Worker presence or affect Task execution. Labtasker performs no
automatic resource detection, sampling, retry, throttling, or history storage;
callers own those choices. The helper also works inside a Python program launched
by `labtasker loop`.

See [Python Workers](../workers/python.md) for binding, cancellation, failure,
and Worker-lifetime semantics.

## Errors and retries

Invalid Python arguments raise `ValueError` before transport. Using an active-run
helper outside its valid context raises `RuntimeError`. Operational failures use:

| Exception | Meaning |
| --- | --- |
| `ConfigError` | Invalid current configuration. Exposes `code`, `message`, and `details`. |
| `TransportError` | No usable Labtasker response: connection, timeout, local startup, malformed protocol, or incompatible response. Its code is `transport_error`. |
| `APIError` | A valid Server rejection. Exposes `status_code`, stable `code`, readable `message`, and structured `details`. |

Reads, list/count, and idempotent Task creation use bounded transport retries.
Ordinary lifecycle, update, and deletion mutations are not automatically retried
after an uncertain response; inspect current state and decide explicitly.
Every ordinary Client request has a 15-second timeout.

`TransientError`, `TaskError`, and `FatalWorkerError` are Worker outcome signals,
not Client-operation errors and not subclasses of `LabtaskerError`.
