# Task operations and recovery

## Submit repeatably

CLI `--args`, `--metadata`, and `--changes` each accept one strict JSON object.
The CLI does not infer types from repeated `key=value` options.

Use a caller-chosen ID when submission must be safe to repeat across process
restarts:

```bash
labtasker task submit \
  --id t_AbCdEf0123-_ \
  --name baseline-seed-1 \
  --args '{"seed":1,"enabled":true}' \
  --route train
```

Task IDs are opaque: `t_` followed by exactly 12 ASCII letters, digits,
underscores, or hyphens. Put the readable experiment label in `name`.

Submitting the same normalized complete definition with the same ID is
idempotent and returns the Task's current representation. Reusing the ID with a
different definition is a conflict, never an update. The Client generates an ID
before its own first network attempt when one is omitted, but an external tool
that must retry after its own restart should persist and reuse its chosen ID.
JSON object-key order, Task route input order, and explicitly spelling a
submission default do not change the normalized definition. Later lifecycle or
user-field updates also do not change the original creation definition used to
recognize a retry. Changing a real submitted value such as `max_attempts` is a
conflict.

The synchronous Python counterparts are `submit_task`, `get_task`, `list_tasks`,
`count_tasks`, `update_task`, `update_tasks`, `cancel_task`, `requeue_task`, and
`delete_task`. They follow the same defaults and lifecycle rules as the CLI.

For a large Python submission loop, reuse one explicit Client and close it
deterministically. There is no bulk-submission endpoint:

```python
from labtasker import Client

with Client() as client:
    for task_id, seed in persisted_work:
        client.submit_task(
            {"seed": seed},
            task_id=task_id,
            routes=["train"],
        )
```

Persist each caller-chosen ID with its complete Task definition before the
submission attempt when the loop must resume safely after its own process
restarts. Package-level functions already reuse one lazy default Client, but an
explicit context-managed Client is the canonical choice for a large loop,
deterministic cleanup, tests, or more than one endpoint. Do not invent a
`submit_tasks` API.

## Inspect all selected Tasks

```bash
labtasker task count --status pending
labtasker task list \
  --filter 'status == "failed" and missing(result.score)' \
  --limit 100
labtasker task get t_ABCDEFGHIJKL
```

`task list` returns one page. If `next_cursor` is non-null, request the next page
with the same Queue, filter, selectors, and ordering:

```bash
labtasker task list \
  --filter 'status == "failed" and missing(result.score)' \
  --limit 100 \
  --cursor OPAQUE_CURSOR
```

Python returns a `TaskPage` with `items` and `next_cursor`:

```python
page = labtasker.list_tasks(filter=filter_expr, limit=100)
tasks = list(page.items)
while page.next_cursor is not None:
    page = labtasker.list_tasks(
        filter=filter_expr,
        limit=100,
        cursor=page.next_cursor,
    )
    tasks.extend(page.items)
```

Filters support comparisons, `and`/`or`, scalar candidate lists, array
containment, and `exists(path)`/`missing(path)`. Literal null and Booleans use
`None`, `True`, and `False`. Every comparison requires the path to exist, so use
`missing(result.score) or result.score < 0.5` to include absent scores.

Use `exists(metadata.owner)` to check an object key. `"owner" in metadata` is
not object-key membership and is invalid. `"baseline" in metadata.tags` means
array containment. General unary `not (...)` is unsupported; use explicit `!=`,
`not in`, `exists`, or `missing` forms.

## Prioritize and update pending work

Workers claim higher `priority` first. Equal-priority pending Tasks keep stable
pending order. Priority affects only future claims; it never interrupts a
running Task.

Inspect a selection before changing it. Update one non-running Task:

```bash
labtasker task update t_ABCDEFGHIJKL --changes '{"priority":20}'
```

Or atomically update all matching non-running Tasks on the Server:

```bash
labtasker task update \
  --filter 'status == "pending" and "clip-openai" in routes' \
  --changes '{"routes":["clip-openai","clip-openclip"]}'
```

`args`, `metadata`, `result`, and `routes` are complete replacements, not
merges. Unspecified fields remain unchanged. Running Tasks cannot be updated.
Do not implement a bulk change as a client-side list/update loop when the
filtered bulk operation expresses it directly.

Bulk update is one Server transaction. A concurrent claim either sees the
complete new values, or wins first and excludes that now-running Task. The
result's `matched` count includes rows that satisfied the filter and remained
non-running at execution time; `updated` counts only rows whose stored values
actually changed. All matching non-running rows are validated before any write,
so one state-dependent conflict rolls back the complete batch rather than
silently skipping an invalid row.

There is no Server-side expression that merges a different existing object for
each Task. When preserving those differences is required, read each Task,
construct its complete replacement, and use ID-addressed `update_task`. This
read-modify-write path accepts last-write-wins if another caller updates the same
Task concurrently; v2 has no revision or compare-and-swap field.

## Use explicit lifecycle actions

```bash
labtasker task cancel TASK_ID
labtasker task requeue TASK_ID
labtasker task delete TASK_ID
```

- Cancel accepts pending or running Tasks. Server cancellation is immediate and
  fences an active run even if local cleanup continues.
- Requeue accepts pending, failed, or cancelled Tasks, returns them to pending,
  resets `attempt` to zero, and clears the last error.
- A succeeded Task cannot be requeued. Submit a new Task to rerun successful
  work.
- A running Task cannot be updated, requeued, or deleted. Cancel it first, then
  requeue if a new execution is wanted.
- Delete permanently removes one non-running Task. Do not delete unless the
  user's intent is explicit.

Queue deletion is separate. A non-empty Queue requires explicit cascade
deletion, and even cascade is rejected while any Task in the Queue is running.
Cancel running Tasks first. A successful cascade atomically deletes the Queue
and all of its Tasks. If Queue `default` is explicitly deleted, later requests
do not recreate it; create it again explicitly if it is still wanted.

Create and select another independently managed Queue only when needed:

```bash
labtasker queue create paper-a
labtasker queue list
labtasker task list --queue paper-a
labtasker queue delete paper-a --cascade
```

The Python Queue API is:

```python
labtasker.create_queue("paper-a")
queues = labtasker.list_queues()
labtasker.delete_queue("paper-a", cascade=True)
```

Use `--queue`, the Python `queue=` argument, `LABTASKER_QUEUE`, or the config
file to select it. Do not use Queues to represent Workers, GPUs, models, or
routes.

## Choose the failure level

In a Python Worker:

| Situation | Raise | Task effect | Worker effect |
| --- | --- | --- | --- |
| Temporary infrastructure incident | `TransientError` | Return to pending without charging the incident | Continue |
| Bad Task or ordinary execution failure | `TaskError` or an ordinary exception | Charge the attempt; retry or become failed | Continue |
| Worker process is no longer trustworthy | `FatalWorkerError` | Charge the attempt; retry or become failed | Exit |

A charged failure returns to pending while `attempt < max_attempts`; otherwise
it becomes failed. `TransientError` rolls back only the current claim's attempt
increment; it does not erase older charged failures. Both a retryable charged
failure and a transient return re-enter the end of their priority group, so
already-waiting equal-priority Tasks run first.

## Recover safely

A healthy long Task has no execution timeout. Every claim gets a private
`run_id`, renews a five-minute lease with a heartbeat once per minute, and may
run as long as heartbeats continue.

Stopping or restarting the Server does not itself rewrite running Tasks. While
an active Server is temporarily unavailable, Workers keep their local execution
and retry heartbeat and terminal-report transport. A restart shorter than the
remaining lease can therefore be transparent. Before a restarted Server begins
serving, it applies the ordinary expiry transition to leases already past their
deadline; heartbeat loss is a charged failure, not a special restart state.

When a Worker disappears, lease recovery returns the Task to pending or marks it
failed according to its retry budget. Recovery is normally committed roughly
five to six minutes after the last accepted heartbeat. A later heartbeat or
completion from the stale Worker has the wrong `run_id` and cannot overwrite a
newer run.

For cancellation or other revocation, Python code may poll
`cancellation_requested()`. A Command Worker terminates the child process group.
The default `force_stop_timeout=None` waits indefinitely for safe cleanup; set a
finite timeout only when forced termination is acceptable.

Once `finish(result)` is accepted, a later exception or nonzero command exit is
only a local diagnostic and cannot change succeeded state. Call `finish()` when
the result must be accepted before cleanup continues.

The local `.labtasker/runs/` journal contains the Task snapshot, output, state,
and prepared terminal report for diagnosis. The Server remains authoritative;
v2 does not reconstruct Server state from journals. It also does not provide
automatic journal retention, compression, or cleanup, and deleting a Task or
Queue does not delete project files or external artifacts.

## Automate the CLI safely

Successful finite Task, Queue, and configuration commands keep requested data
on stdout as one two-space-indented JSON document with no ANSI styling. Endpoint
selection, local daemon startup or reconnection, and other diagnostics go to
stderr, so redirecting stdout remains machine-readable. Successful delete
commands are quiet on stdout.

Handled configuration, transport, and API errors write no stdout, put a stable
structured error envelope on stderr, and exit `1` without an application
traceback. CLI argument or usage errors exit `2`; an interrupted Worker retains
the conventional `130`. Use the exit status, not log text, to decide whether a
finite command succeeded.

`labtasker loop` is different: it is a long-running supervised process that
writes ordinary timestamped operational logs and relays user-code output. It
does not produce one JSON document or a JSONL event stream.
