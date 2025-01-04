# Basic Practices

This section describes the basic practices for using Labtasker.

After installation, you can use Labtasker to schedule your experiment tasks.

## Basic workflow

1. Submit tasks to the server via a bash script, looping over a list of arguments.
2. Start multiple worker scripts, each using Labtasker client API to fetch tasks from the server.
3. The worker scripts execute the tasks and report the results back to the server.

Suppose your server is running on `localhost:8080`.

!!! note

    The following "Python" and "Bash" API can mix. That is, you can submit tasks via Python script and execute tasks via Bash script.

### Step 0. Client configuration

You can start interactive cli to create a client configuration file.

```bash
labtasker config
```

You can see the example of the client configuration file in `client.example.env`.

```ini
# my_client_config.env

HTTP_SERVER_ADDRESS=localhost:8080

QUEUE_NAME=my_queue
PASSWORD=my_password  # a password for a queue
```

### Step 1. Create a task queue

First, you need to create a task queue.

The following command loads the client configuration from `my_client_config.env` and creates a task queue with name and password specified in the client configuration.

=== "Option 1. Python"

    ```python
    import labtasker

    tasker = labtasker.LabtaskerClient(client_config="./my_client_config.env")
    status, queue_id = tasker.create_queue()
    ```

=== "Option 2. Bash"

    ```bash
    labtasker create-queue --client-config ./my_client_config.env

    # {
    #     "status": "success",
    #     "queue_name": "my_queue",
    #     "queue_id": "xxxxxx"
    # }
    ```

### Step 2. Submit tasks

=== "Option 1. Python"

    ```python
    # submit_tasks.py
    import labtasker

    tasker = labtasker.LabtaskerClient(client_config="./my_client_config.env")

    for my_param_1 in range(10):
        for my_param_2 in range(10):
            tasker.submit(task_name="optional_task_name", args={"my_param_1": my_param_1, "my_param_2": my_param_2})
    ```

=== "Option 2. Bash"

    ```bash
    # submit_tasks.sh
    #
    # submit task parameters as a JSON string, loop over different combinations of task parameters
    # {
    #     "my_param_1": 1,
    #     "my_param_2": 2
    # }
    for my_param_1 in {1..10}
    do
        for my_param_2 in {1..10}
        do
            labtasker submit --client-config ./my_client_config.env --task-name optional_task_name --args '{"my_param_1": $my_param_1, "my_param_2": $my_param_2}'
            # returns a JSON string containing relevant task information
        done
    done
    ```

### Step 3. Execute tasks

=== "Option 1. Python"

    ==**This approach is intrusive to the task Python script**==

    ```python
    # task_runner.py
    import time
    import labtasker
    from subprocess import run

    tasker = labtasker.LabtaskerClient(client_config="./my_client_config.env")

    while True:
        task = tasker.fetch(eta_max="2h", start_heartbeat=True)
        if task.status == "empty":
            break
        elif task.status == "error":
            continue

    # Execute the task
        try:
            run(["python", "run_my_experiment.py", "--param1", task.args["my_param_1"], "--param2", task.args["my_param_2"]])
        except Exception as e:
            task.report(status="failure", summary={"error": str(e)})
            continue

    task.report(status="success", summary={"log_file_path": "/path/to/log/file"})

    time.sleep(1)
    ```

=== "Option 2. Bash"

    ==**This approach is non-intrusive to the task Python script**==

    ```bash
    # work.sh
    CONFIG_PATH="./my_client_config.env"

    while true
    do
        # Fetch task arguments
        response=$(labtasker fetch --client-config "$CONFIG_PATH" --eta-max 2h)  # the timeout for single task execution is 2 hours. Required for bash cli, since heartbeat is not supported for bash cli.

    # Extract status from the JSON response, one of "empty", "error", "success"
        status=$(echo "$response" | jq -r '.status')

    case "$status" in
            "empty")
                echo "No tasks to execute"
                break
                ;;
            "error")
                echo "Task fetch failed"
                sleep 10
                continue
                ;;
            "success")
                echo "Task fetched successfully"
                # Proceed with task execution
                ;;
            *)
                echo "Unexpected status: $status"
                sleep 10
                continue
                ;;
        esac

    # Extract task ID and parameters from nested JSON
        # {
        #     "status": "success",
        #     "task_id": "123",
        #     "args": {
        #         "my_param_1": "1",
        #         "my_param_2": "2"
        #     }
        # }
        task_id=$(echo "$response" | jq -r '.task_id')
        my_param_1=$(echo "$response" | jq -r '.args.my_param_1')
        my_param_2=$(echo "$response" | jq -r '.args.my_param_2')

    # Execute the task
        if python run_my_experiment.py --param1 "$my_param_1" --param2 "$my_param_2"; then
            # Report success
            labtasker report --client-config "$CONFIG_PATH" --task-id "$task_id" --status "success" --summary '{"log_file_path": "/path/to/log/file"}'
        else
            # Report failure
            labtasker report --client-config "$CONFIG_PATH" --task-id "$task_id" --status "failed" --summary '{"log_file_path": "/path/to/log/file"}'
        fi

    # Optional: Sleep to avoid tight loop
        sleep 1
    done
    ```

## Feature comparison

We compare the Python and Bash API:

| Features                  | Python | Bash |
| ------------------------- | ------ | ---- |
| Heartbeat                 | ✅     | -    |
| Worker-ID auto-register   | ✅     | -    |
| Error worker auto-suspend | ✅     | -    |
| Create queue              | ✅     | ✅   |
| Submit                    | ✅     | ✅   |
| Upload metadata           | ✅     | ✅   |
| Task filtering            | ✅     | ✅   |

!!! note "Why are some features not supported in Bash?"
    The fundamental reason is that bash is difficult to implement a daemon process that automatically sends heartbeat, maintains a worker ID and quits when the bash script exits.

    Such functionality can be achieved via `TRAP` mechanism in bash. But it increases the complexity of the bash script.

    We show the example in the [advanced use cases section](./advanced.md#daemon-in-bash-api).
