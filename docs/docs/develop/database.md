# Database

Each queue indentified by a unique queue_name, is responsible for managing:

1. A collection of tasks (task queue)
2. A collection of workers to check worker status. If a worker crashes multiple times, the tasks will be no longer be assigned to it. (worker pool)
3. Authentication for the queue

## Data entry

```json
{
    "task_id": "xxxxxx",
    "queue_id": "uuid-string",
    "status": "created",
    "task_name": "optional_task_name",
    "start_time": "2025-01-01T00:00:00Z",
    "last_heartbeat": "2025-01-01T00:00:00Z",
    "last_modified": "2025-01-01T00:00:00Z",
    "heartbeat_timeout": 60,
    "timeout": 3600,
    "max_retries": 3,
    "retries": 0,
    "priority": 10,
    "metadata": {},
    "worker_metadata": {
        "worker_id": "xxxxxx",
        "queue_id": "uuid-string",
        "status": "active",
        "worker_name": "optional_worker_name",
        "max_crash_count": 3,
        "crash_count": 0
    },
    "args": {
        "my_param_1": 1,
        "my_param_2": 2
    },
    "summary": {}
}
```

## Priority

- LOW: 0
- MEDIUM: 10  (default)
- HIGH: 20

## Worker FSM

states:

- active
- suspended
- crashed

## Task FSM

states:

- created
- cancelled
- pending
- running
- completed
- failed

## Collections

### Queues Collection
```json
{
    "_id": "uuid-string",
    "queue_name": "my_queue",
    "password": "hashed_password",
    "created_at": "2025-01-01T00:00:00Z"
}
```

### Tasks Collection
```json
{
    "_id": "xxxxxx",
    "queue_id": "uuid-string",
    "status": "created",
    "task_name": "optional_task_name",
    "start_time": "2025-01-01T00:00:00Z",
    "last_heartbeat": "2025-01-01T00:00:00Z",
    "last_modified": "2025-01-01T00:00:00Z",
    "heartbeat_timeout": 60,
    "timeout": 3600,
    "max_retries": 3,
    "retries": 0,
    "priority": 10,
    "metadata": {},
    "worker_metadata": {
        "worker_id": "xxxxxx",
        "queue_id": "uuid-string",
        "status": "active",
        "worker_name": "optional_worker_name",
        "max_crash_count": 3,
        "crash_count": 0
    },
    "args": {
        "my_param_1": 1,
        "my_param_2": 2
    },
    "summary": {}
}
```

### Workers Collection
```json
{
    "_id": "xxxxxx",
    "queue_id": "uuid-string",
    "worker_name": "optional_worker_name",
    "status": "active",
    "heartbeat_timeout": 60,
    "crash_count": 0,
    "max_crash_count": 3
}
```
