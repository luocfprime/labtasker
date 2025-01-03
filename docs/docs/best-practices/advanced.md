# Advanced Features

## Database management

The backend uses MongoDB to store task data. The server itself does not preserve any state or data. This allows you to directly access the database using a database management tool to navigate and manage the tasks.

## Queue management

### Query single task

```bash
labtasker get-task --client-config ./my_client_config.env --task-id my_task_id

# or

labtasker get-task --client-config ./my_client_config.env --task-name my_task_name
```

### Getting task list

```bash
labtasker ls-tasks --client-config ./my_client_config.env --queue-id my_queue_id

# or

labtasker ls-tasks --client-config ./my_client_config.env --queue-name my_queue_name
```

## Adding metadata to tasks

When submitting tasks, you can add metadata to the task. Metadata is a separate field from `args`. This allows for flexible task management and reporting.

!!! example "Example: Tags implemented by metadata"

    You can implement tag feature using metadata.

    === "Python"

        ```python
        import labtasker

        tasker = labtasker.Tasker(client_config="./my_client_config.env")

        tasker.submit(
            task_name="optional_task_name",
            args={"my_param_1": my_param_1, "my_param_2": my_param_2},
            metadata={"tags": ["my_tag_1", "my_tag_2"]}
        )
        ```

    === "Bash"

        ```bash
        labtasker submit --client-config ./my_client_config.env \
        --task-name optional_task_name \
        --metadata '{"tags": ["my_tag_1", "my_tag_2"]}' \
        --args '{"my_param_1": $my_param_1, "my_param_2": $my_param_2}'
        ```

## Task settings

### Priority

### Timeout

### Retries

## Task filtering

## Suspend worker

## Daemon in bash API

### Heartbeat via bash
