# Python API

The `labtasker` package is synchronous and typed. It exposes a function-first API
backed by one lazily created default `Client`, plus an explicit `Client` class for
lifecycle or multi-target control.

## Task functions

```python
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

`changes` is a `TaskUpdate` typed dictionary. It may contain `name`, `args`,
`metadata`, `priority`, `max_attempts`, `routes`, or `result`.

## Queue functions

```python
create_queue(name) -> Queue
list_queues() -> list[Queue]
delete_queue(name, *, cascade=False) -> None
```

## Worker functions

```python
@loop(route="default", queue=None, idle_timeout=300,
      force_stop_timeout=None)
def worker(...): ...

TaskArg(default=..., path=None, resolver=None)
task_info() -> TaskInfo
finish(result=None, *, skip_if_no_labtasker=False) -> None
cancellation_requested() -> bool
set_force_stop_timeout(seconds) -> None
```

See [Python Workers](../workers/python.md) for binding and lifecycle semantics.

## Models and errors

Response models are frozen, strict Pydantic models. The central models are
`Task`, `TaskInfo`, `TaskPage`, `Queue`, `LastError`, and `BulkUpdateResult`.

All package errors derive from `LabtaskerError`:

- `ConfigError` for invalid local configuration;
- `TransportError` for connection or malformed-response failures;
- `APIError` for a structured Server rejection;
- `TransientError`, `TaskError`, and `FatalWorkerError` for deliberate Worker
  control.

Task arguments, metadata, results, and updates accept strict JSON-compatible
values only. Arbitrary Python objects, NaN, Infinity, non-string object keys, and
excessively deep data are rejected before transport.
