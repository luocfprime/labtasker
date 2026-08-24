# Python API

The public `labtasker` package is synchronous and typed. Every resource
operation is available both as a package-level function and as a method with the
same name on `Client`. Methods return Labtasker domain models, not HTTP response
wrappers.

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

`Client(url=None, token=None, queue=None)` resolves each omitted field through
environment, the current directory's `.labtasker/config.toml`, then defaults.
Resolution happens once when the Client is constructed. Later `chdir()`, config,
or environment changes do not retarget it. A non-null `queue=` on a Task method
overrides only that operation's Queue; changing Servers requires a new Client.

`close()` is idempotent and never stops a local Server. Operations on a closed
Client raise `RuntimeError("Client is closed.")`. The package-level default
Client has no close/reset API. There is no asynchronous Client.

## Task operations

```text
submit_task(args=None, *, name=None, metadata=None, priority=0,
            max_attempts=3, routes=None, task_id=None, queue=None) -> Task
get_task(task_id, *, queue=None) -> Task
list_tasks(*, status=None, name=None, filter=None, order_by="created_at",
           descending=True, limit=100, cursor=None, queue=None) -> TaskPage
count_tasks(*, status=None, name=None, filter=None, queue=None) -> int
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
| `count_tasks` | Returns an `int` for the complete selection; it is independent of list pagination. |
| `update_task` | Replaces supplied user-owned fields on one non-running Task and returns the resulting Task. |
| `update_tasks` | Atomically updates all matching non-running Tasks and returns `BulkUpdateResult(matched, updated)`. A non-empty filter is required. |
| `cancel_task` | Cancels a pending or running Task. Repeating cancel on a cancelled Task is idempotent. |
| `requeue_task` | Accepts pending, failed, or cancelled; returns it to pending, resets `attempt` to `0`, and clears `last_error`. |
| `delete_task` | Permanently deletes one non-running Task and returns `None`. Deleting an absent Task is idempotent. |

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

`status`, exact `name`, and `filter` are combined with AND. `limit` must be from
1 through 1000. Ordering is stable and supports `id`, `name`, `status`,
`priority`, `attempt`, `max_attempts`, `last_route`, and the public timestamps.

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
| `Task` | `id`, `queue`, `status`, `name`, `args`, `metadata`, `priority`, `attempt`, `max_attempts`, `routes`, `result`, `last_error`, `last_route`, `created_at`, `updated_at`, `started_at`, `finished_at` |
| `TaskPage` | `items: list[Task]`, `next_cursor: str | None` |
| `BulkUpdateResult` | `matched: int`, `updated: int` |
| `Queue` | `name: str` |
| `LastError` | `type`, `message`, `traceback`, `occurred_at`, `attempt`, `run_id` |
| `TaskInfo` | Every `Task` field plus the active `run_id` and absolute local `run_dir` |

Task states are exactly `pending`, `running`, `succeeded`, `failed`, and
`cancelled`. Timestamps are timezone-aware UTC `datetime` values.

## Worker API

```text
@loop(route="default", queue=None, idle_timeout=300,
      force_stop_timeout=None)
def worker(...): ...

TaskArg(default=..., path=None, resolver=None)
task_info() -> TaskInfo
finish(result=None, *, skip_if_no_labtasker=False) -> None
cancellation_requested() -> bool
set_force_stop_timeout(seconds: float | None) -> None
```

Only parameters marked by `TaskArg(...)` bind from Task args. Binding is strict
and happens after claim; ordinary return succeeds with `{}`. `finish()` accepts
one JSON object and completes the Task before local cleanup continues. It is
stable once accepted and may be called only once. The context helpers require an
active Worker execution; cancellation and force-stop helpers require a Python
Worker execution.

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

`TransientError`, `TaskError`, and `FatalWorkerError` are Worker outcome signals,
not Client-operation errors and not subclasses of `LabtaskerError`.
