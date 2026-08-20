# Core model

## Queue

A Queue is the only namespace. Task IDs are unique within their Queue, and every
operation selects one Queue. The fresh-database default is named `default`.

Queues are useful for independently managed bodies of work, not for expressing
Worker capability. CPU, GPU, codebase, and model compatibility belong in routes.

## Task

A Task is a durable JSON record containing arguments, metadata, priority, retry
limits, routes, result, timestamps, and the latest error. Its lifecycle is:

```text
pending -> running -> succeeded
                   -> pending or failed
                   -> cancelled
```

Explicit user actions can also cancel, requeue, update, or delete a Task. Except
for a running Task, these operations are intentionally permissive: an explicit,
unambiguous user request is not blocked merely because it is unusual.

## Route

A route is an opaque compatibility label. A Worker declares one route when it
starts; a Task stores a non-empty set of routes. Matching is exact.

```text
Task routes:  ["sdxl-v1", "sdxl-v2"]
Worker route: "sdxl-v2"
Result:       eligible
```

Routes are not registered resources, authenticated identities, resource claims,
or inferred capabilities. This makes rolling changes explicit: start a new
Worker under `sdxl-v2`, then update only the pending Tasks that should become
compatible with it.

## Claim, run, and lease

A claim changes one pending Task to running and creates a private `run_id`. That
ID is a fencing token: heartbeat and terminal reports must include it, so a stale
Worker cannot modify a newer execution of the same Task.

The Worker renews a five-minute lease once per minute. If heartbeats stop, the
Server recovers the Task according to its existing retry budget. Labtasker does
not impose a separate execution timeout.

## Attempt

`attempt` counts charged executions. Ordinary failures and `TaskError` consume
an attempt. `TransientError` returns the Task to pending without charging the
current incident. Requeue clears `attempt`; retry after a failure does not.

## Worker

A Worker is a Client process, not a Server resource. The Server stores the
current run and route on the Task but has no Worker table, worker registration,
capacity model, or worker heartbeat independent of a claimed Task.
