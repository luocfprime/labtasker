# HTTP API

The application API is rooted at `/api/v2`. A running Server's
`/openapi.json` is the authoritative machine-readable schema for request and
response bodies. This page records the behavioral contract that an independent
Client or Worker must preserve.

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/openapi.json > openapi.json
```

FastAPI's interactive Swagger and ReDoc pages are intentionally disabled.

## Common contract

- `/health` and `/openapi.json` are unauthenticated. Every `/api/v2` endpoint
  uses the one Server-wide Bearer token when authentication is configured.
- Request schemas reject unknown fields. Response schemas may gain optional
  fields within v2; existing fields, types, defaults, meanings, and Task states
  do not change without a new API prefix.
- Request bodies and complete stored Task data are each limited to 1 MiB. Large
  artifacts do not belong in Task JSON.
- Public timestamps are UTC RFC 3339 strings. Task states are exactly `pending`,
  `running`, `succeeded`, `failed`, and `cancelled`.
- Successful `204` responses have no body. Clients must not invent receipt
  objects for them.

When enabled, authenticate application requests with:

```http
Authorization: Bearer <token>
```

## Discovery

| Method and path | Success |
| --- | --- |
| `GET /health` | `200` with `{"status":"ok","api_version":"2","database":"ok"}` after a real database check. Database failure returns `503` with `status` and `database` set to `error`. |
| `GET /openapi.json` | `200` with the generated OpenAPI schema. |

## Queue endpoints

| Method and path | Input | Success and constraints |
| --- | --- | --- |
| `PUT /api/v2/queues/{queue}` | No body | `201` when created, `200` when already present; returns `{"name": ...}`. |
| `GET /api/v2/queues` | None | `200` with the complete unpaginated Queue array. |
| `DELETE /api/v2/queues/{queue}?cascade=false` | Boolean query parameter | `204`. A non-empty Queue requires `cascade=true`; any running Task still blocks deletion. Successful cascade atomically deletes the Queue and all its Tasks. |

Queue names are explicit path components and are not authentication identities.

## Task resource endpoints

| Method and path | Input | Success and constraints |
| --- | --- | --- |
| `PUT /api/v2/queues/{queue}/tasks/{task_id}` | Task creation object | `201` on creation; `200` for an identical replay at the same ID; `409 task_id_conflict` for a different definition. |
| `GET /api/v2/queues/{queue}/tasks/{task_id}` | None | `200` with one Task; `404 task_not_found` when absent. |
| `GET /api/v2/queues/{queue}/tasks` | Selection and pagination query parameters | `200` with `{"items":[...],"next_cursor":...}`. Returns one page only. |
| `GET /api/v2/queues/{queue}/tasks/count` | Selection query parameters | `200` with `{"count":N}` for the complete selection. |
| `PATCH /api/v2/queues/{queue}/tasks/{task_id}` | Non-empty Task update object | `200` with the Task. Running Tasks reject updates. Object/list fields are complete replacements. |
| `PATCH /api/v2/queues/{queue}/tasks` | `{"filter":...,"changes":...}` | `200` with `{"matched":N,"updated":M}`. The filter is required; the update is atomic across matching non-running Tasks. |
| `POST /api/v2/queues/{queue}/tasks/{task_id}/cancel` | No body | `200` with the cancelled Task. Accepts pending/running and is idempotent for cancelled. |
| `POST /api/v2/queues/{queue}/tasks/{task_id}/requeue` | No body | `200` with the pending Task. Accepts pending/failed/cancelled, resets attempt and last error. |
| `DELETE /api/v2/queues/{queue}/tasks/{task_id}` | None | `204`; idempotent when absent. Running Tasks reject deletion. |

### Creation body

Every field is optional because the Server expands the same defaults as the
Python API:

```json
{
  "name": null,
  "args": {},
  "metadata": {},
  "priority": 0,
  "max_attempts": 3,
  "routes": ["default"]
}
```

The Task ID is the resource identity and must match
`t_[A-Za-z0-9_-]{12}`. Replaying the same normalized definition returns the
Task's current representation. JSON object-key order, route input order, and an
omitted default versus the same explicit default do not change that identity.

### List and count queries

Task listing accepts:

```text
status, name, filter, order_by, descending, limit, cursor
```

Count accepts `status`, `name`, and `filter`. Selectors are combined with AND.
`limit` is 1 to 1000 and defaults to 100. A non-null `next_cursor` must be reused
with the same Queue, selectors, filter, order field, and direction. The cursor is
opaque. See [Query language](../guides/query.md) for filter syntax.

### Update body

A Task update contains at least one of:

```json
{
  "name": "new name",
  "args": {},
  "metadata": {},
  "priority": 10,
  "max_attempts": 5,
  "routes": ["robotwin"],
  "result": {}
}
```

Every supplied object/list is a complete replacement. Identity, status, attempt,
last error, run ownership, and timestamps are Server-owned. Bulk update counts
only rows that match and remain non-running; a concurrent claim either sees all
new values or excludes that Task. Validation failure for one matched non-running
Task rolls back the complete batch.

## Worker protocol

These endpoints let an independent executor implement the same lease/fencing
contract as the bundled Workers. They are not public convenience methods on the
Python `Client`.

| Method and path | Body | Success |
| --- | --- | --- |
| `POST /api/v2/queues/{queue}/tasks/claim` | `{"route":...,"run_id":...}` | `200` with Task, `run_id`, and `lease_expires_at`; `204` when no compatible pending Task exists. |
| `POST /api/v2/queues/{queue}/tasks/{task_id}/heartbeat` | `{"run_id":...}` | `200` with the renewed `lease_expires_at`. |
| `POST /api/v2/queues/{queue}/tasks/{task_id}/complete` | `{"run_id":...,"result":{...}}` | `204`; completes the matching active run as succeeded. |
| `POST /api/v2/queues/{queue}/tasks/{task_id}/fail` | `{"run_id":...,"error":{"type":...,"message":...,"traceback":...}}` | `204`; charges the failure and retries or fails according to the Task budget. |
| `POST /api/v2/queues/{queue}/tasks/{task_id}/unclaim` | `{"run_id":...}` | `204`; returns the matching run to pending without an error payload. |

`run_id` matches `r_[A-Za-z0-9_-]{12}` and is a private per-claim ownership
token, not a Run resource. Heartbeat and terminal actions require the currently
active ID. A stale process cannot mutate a newer claim.

Claim matches the supplied route exactly and case-sensitively. Among compatible
pending Tasks, higher priority is claimed first, followed by stable pending
order. A healthy run renews its five-minute lease with heartbeat; the lease is
not an execution timeout.

Terminal actions are effect-idempotent for the most recently finalized run and
same action. A contradictory action or stale run conflicts. The Server exposes
no `/runs` collection or execution-history API.

## Task representation

Ordinary get/list/action responses contain exactly these required v2 fields:

```text
id, queue, status, name, args, metadata, priority, attempt, max_attempts,
routes, result, last_error, last_route, created_at, updated_at, started_at,
finished_at
```

Active `run_id` and lease expiry appear only in Worker protocol responses, never
in the ordinary Task resource.

## Errors

Every documented application error uses one envelope:

```json
{
  "error": {
    "code": "stale_run",
    "message": "This run is no longer active.",
    "details": {}
  }
}
```

Branch on `error.code`, not `message`. The stable status classes are:

| HTTP status | Meaning and representative codes |
| --- | --- |
| `401` | Missing or incorrect token: `unauthorized`. |
| `404` | Missing Queue or Task: `queue_not_found`, `task_not_found`. |
| `409` | State or ownership conflict: `task_id_conflict`, `task_running`, `stale_run`, `run_finalized`, lifecycle/update conflicts. |
| `413` | Body exceeds 1 MiB: `request_too_large`. |
| `422` | Invalid request, Task, filter, update, identifier, or complete stored data: for example `invalid_task`, `invalid_filter`, `invalid_update`, `task_data_too_large`. |
| `503` | Retryable Server-side operational failure such as `database_busy`; still uses the same envelope. |

Malformed FastAPI/Pydantic native errors are converted to this envelope; Server
tracebacks and database details are never part of the public response.

## Client retry boundary

Safe reads and representation-idempotent Task creation can be retried with the
same inputs. Lifecycle, update, and delete calls should not be retried blindly
after an uncertain response because another actor may have changed the resource.
Inspect current state before deciding.

Workers use a separate reliability policy: they keep heartbeat active while
retrying one terminal report, and `run_id` fencing prevents a stale retry from
overwriting a newer execution.
