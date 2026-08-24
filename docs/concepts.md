# Core model

Labtasker's working model is deliberately small: submit each independent job as
a Task, then start Workers that repeatedly take one compatible Task, execute it,
and report the outcome. The Server remembers the work; it does not manage the
Worker processes or the hardware beneath them.

## Task

A Task is one unit of work and its recorded state. It contains JSON arguments,
metadata, priority, retry limits, compatible routes, result, timestamps, and the
latest error. Its ordinary path is:

```text
pending -> running -> succeeded
                   -> pending or failed
                   -> cancelled
```

Explicit actions do not patch the status field generically. Cancel accepts
pending or running Tasks; requeue accepts pending, failed, or cancelled Tasks;
update and delete accept any non-running Task. A succeeded experiment is rerun
by submitting a new Task rather than rewriting its successful lifecycle.

## Worker

A Worker is a Client process that executes at most one Task at a time. Start one
Worker on each CPU, GPU, machine, or other resource you want to use. When it
finishes a Task, it asks the Server for another.

The Server records which route and run currently own a Task, but it has no
Worker registry, capacity model, or Worker heartbeat separate from a running
Task. Starting and stopping Worker processes remains the user's responsibility.

## Route

A route is an exact, case-sensitive compatibility label. Every Worker starts
with one route; every Task lists one or more routes. A Worker can take a Task
only when its route appears in that list.

```text
Task routes:  ["sdxl-v1", "sdxl-v2"]
Worker route: "sdxl-v2"
Result:       compatible
```

Routes are not registered resources, identities, or GPU claims. Labtasker never
infers them from Task arguments. This keeps implementation changes explicit:
start a Worker under `sdxl-v2`, then update only the pending Tasks that should be
allowed to use it.

## Queue

A Queue keeps one independently managed body of Tasks together. Every operation
selects one Queue, and Task IDs are unique within it. A fresh database contains
Queue `default`.

Use separate Queues for work that should be managed independently. Do not use
them to describe CPU, GPU, codebase, or model compatibility; routes serve that
purpose.

## Claim, run, and lease

When a Worker takes a pending Task, the claim changes it to running and creates
a private `run_id`. Heartbeats and terminal reports must include that ID. If an
old Worker reports after the Task has been recovered and claimed again, its ID
no longer matches and it cannot overwrite the newer run.

The Worker renews a five-minute lease once per minute. If heartbeats stop, the
Server returns the Task to pending or marks it failed according to its remaining
retry budget. Labtasker has no separate execution timeout; a healthy long run
can continue while its lease is renewed.

## Attempt

`attempt` counts executions charged against `max_attempts`. Ordinary exceptions
and `TaskError` charge the current execution. `TransientError` returns the Task
to pending without charging that incident. Requeue resets `attempt`; retrying a
failed Task does not.
