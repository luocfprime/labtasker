# Failure and recovery

## Failure behavior

For Python Workers:

| Outcome | Task effect | Worker effect |
| --- | --- | --- |
| normal return or `finish()` | succeeded | continues |
| ordinary exception or `TaskError` | charged failure | continues |
| `TransientError` | pending, incident uncharged | continues |
| `FatalWorkerError` | charged failure | exits |
| `KeyboardInterrupt` | best-effort unclaim | exits |

For command Workers, exit code zero succeeds and a non-zero exit code is a
charged failure. A charged failure returns to pending while retry budget remains;
otherwise the Task becomes failed.

## Heartbeat recovery

Every claim receives a private run ID and a five-minute lease. The Worker sends a
heartbeat once per minute. Transport failures are retried; a stale or finalized
run revokes local ownership. A late heartbeat or completion can never mutate a
newer run because every transition is conditionally fenced by the run ID.

There is no independent execution timeout. A long healthy run may continue as
long as its heartbeat is renewed.

## Cancellation

Server cancellation is immediate and authoritative. Local execution may take
time to stop:

- Python code can poll `cancellation_requested()`.
- Command Workers terminate the child process group when forced stopping is
  enabled.
- `force_stop_timeout=None`, the default, waits for natural cleanup.

This default protects codebases that have already produced a result but cannot
reliably tear down complex engines on demand.

## Local run journal

Each claim creates a semantic directory under:

```text
.labtasker/runs/{queue}/{task-name}__{task-id}/
  {started-at}__attempt-{attempt}__{run-id}/
```

It records the claimed Task snapshot, run state, combined output log, and the
prepared terminal payload. Terminal payloads are immutable once written. Journal
writes after an accepted Server completion are best effort and cannot reverse the
Task's succeeded state.

The Server remains authoritative. The journal is designed for local browsing,
debugging, and possible future recovery tooling; v2 does not automatically
restore Server state from disk.

## Diagnostics

Failed Tasks retain only the latest structured error: type, message, traceback
when available, timestamp, attempt, and run ID. `started_at` and `finished_at`
give a useful coarse runtime estimate without introducing a separate Run history
resource.
