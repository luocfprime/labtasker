# HTTP API

The application API is rooted at `/api/v2`. The running Server's
`/openapi.json` is the authoritative machine-readable endpoint and schema
reference. Interactive Swagger or ReDoc pages are intentionally not shipped.

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/openapi.json > openapi.json
```

## Resource shape

The API contains:

- Queue create, list, and delete operations;
- Task create, get, list, count, update, cancel, requeue, and delete operations;
- Worker claim, heartbeat, complete, fail, and unclaim operations.

Worker terminal operations address the canonical Task resource and put the
private `run_id` in the JSON body. The run ID is a fencing/lease token, not a
first-class Run resource, so there is no `/runs` collection or Run history API.

## Authentication

When configured, application requests use:

```http
Authorization: Bearer <LABTASKER_SERVER_TOKEN>
```

Health and OpenAPI discovery do not require the token. The Server applies one
shared token globally.

## Errors

Every application error has one stable envelope:

```json
{
  "error": {
    "code": "stale_run",
    "message": "The run no longer owns this Task.",
    "details": {}
  }
}
```

Clients should branch on `error.code`, not the human-readable message. Common
HTTP meanings include malformed/invalid requests, unauthorized access, missing
resources, conflicts such as stale runs or running-Task mutation, oversized
requests, and internal Server failures.

## Idempotency and fencing

Task creation with a caller-supplied ID is representation-idempotent. Terminal
run operations are effect-idempotent for the most recently finalized run and
action. A duplicate of that action succeeds without applying it again; a
different action or stale run conflicts.

The Server uses atomic conditional transitions. In particular, claim selection,
lease ownership, update restrictions, and terminal state changes are enforced in
the database rather than by read-then-write assumptions in a Client.
