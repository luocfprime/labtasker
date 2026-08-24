# Failure and recovery

Labtasker records what finished and returns retryable work to the Queue, so a
Worker crash or interrupted session does not require rerunning the complete
experiment. A **charged failure** consumes one of the Task's `max_attempts`; an
uncharged incident leaves that retry budget unchanged.

## Failure behavior

For Python Workers:

| Outcome | Task effect | Worker effect |
| --- | --- | --- |
| normal return or `finish()` | succeeded | continues |
| ordinary exception or `TaskError` | charged failure | continues |
| `TransientError` | pending, incident uncharged | continues |
| `FatalWorkerError` | charged failure | exits |
| `KeyboardInterrupt` | best-effort unclaim | exits |

For command Workers that have not called `finish()`, exit code zero succeeds and
a non-zero exit code is a charged failure. A successful `finish()` is stable: a
later exception or non-zero child exit is only a local diagnostic. A charged
failure returns to pending while retry budget remains; otherwise the Task becomes
failed.

## Heartbeat recovery

Every claim receives a private run ID and a five-minute lease. The Worker sends a
heartbeat once per minute. Transport failures are retried. A stale run, or a run
finalized by any action other than its own successful completion, revokes local
ownership. A late heartbeat or completion can never mutate a newer run because
every transition is conditionally fenced by the run ID.

There is no independent execution timeout. A long healthy run may continue as
long as its heartbeat is renewed.

## Cancellation

Server cancellation is immediate and authoritative. Local execution may take
time to stop:

- Python code can poll `cancellation_requested()`.
- Command Workers send termination to the child process group; a configured
  force-stop timeout escalates to killing any remainder.
- `force_stop_timeout=None`, the default, waits for natural cleanup.

This default protects codebases that have already produced a result but cannot
reliably tear down complex engines on demand.

## Local run journal

Each claim creates a semantic directory under:

```text
.labtasker/runs/{queue}/{task-name-slug}__{task_id}/
  {started-at}__attempt-{attempt}__{run_id}/
```

It records the claimed Task snapshot, run state, combined output log, and the
prepared terminal payload. Terminal payloads are immutable once written. Journal
writes after an accepted Server completion are best effort and cannot reverse the
Task's succeeded state.

The Server remains authoritative. The journal is for local browsing and
debugging; v2 does not restore Server state from it.

## Diagnostics

A Task retains only its latest charged error: type, message, traceback when
available, timestamp, attempt, and run ID. A later success does not erase that
diagnostic; manual requeue does. `started_at` and `finished_at` summarize the
latest run and give a coarse runtime estimate without a separate Run-history
resource.
