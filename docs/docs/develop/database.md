# Database

Each queue identified by a unique queue_name, is responsible for managing:

1. A collection of tasks (task queue)
2. A collection of workers to check worker status. If a worker crashes multiple times, the tasks will be no longer be assigned to it. (worker pool)
3. Authentication for the queue

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
- success
- failed

## Collections

### Queues Collection

```json
{
    "_id": "uuid-string",
    "queue_name": "my_queue",
    "password": "hashed_password",
    "created_at": "2025-01-01T00:00:00Z",
    "last_modified": "2025-01-01T00:00:00Z",
    "metadata": {}
}
```


### Tasks Collection

```json
{
    "_id": "xxxxxx",
    "queue_id": "uuid-string",
    "status": "created",
    "task_name": "optional_task_name",
    "created_at": "2025-01-01T00:00:00Z",
    "start_time": "2025-01-01T00:00:00Z",
    "last_heartbeat": "2025-01-01T00:00:00Z",
    "last_modified": "2025-01-01T00:00:00Z",
    "heartbeat_timeout": 60,
    "task_timeout": 3600,
    "max_retries": 3,
    "retries": 0,
    "priority": 10,
    "metadata": {},
    "args": {
        "my_param_1": 1,
        "my_param_2": 2
    },
    "cmd": "python main.py --arg1=1 --arg2=2",
    "summary": {},
    "worker_id": "xxxxxx",
}
```

### Workers Collection

```json
{
    "_id": "xxxxxx",
    "queue_id": "uuid-string",
    "status": "active",
    "worker_name": "optional_worker_name",
    "metadata": {},
    "max_retries": 3,
    "retries": 0,
    "created_at": "2025-01-01T00:00:00Z",
    "last_modified": "2025-01-01T00:00:00Z"
}
```
