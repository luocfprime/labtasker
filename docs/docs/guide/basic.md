# Tutorial: Basic Practices

## Prerequisites

**Make sure you have configured client.**

```bash
labtasker config
```

**Validate server connection.**

```bash
labtasker health
```

**If a task queue for current project has not been created,
you can create one from the previously configured config.**

```bash
labtasker queue create-from-config
```

## Step 1. Submit job arguments via Python or CLI tool

=== "Bash"

    ```bash title="demo/bash_demo/submit_job.sh"
    --8<-- "demo/bash_demo/submit_job.sh"
    ```

=== "Python"

    ```python title="demo/python_demo/submit_job.py"
    --8<-- "demo/python_demo/submit_job.py"
    ```

## Step 2. Run job

=== "Bash"

    ```bash title="demo/bash_demo/run_job.sh"
    --8<-- "demo/bash_demo/run_job.sh"
    ```

    where

    ```bash title="demo/bash_demo/job_main.py"
    --8<-- "demo/bash_demo/job_main.py"
    ```

=== "Python"

    ```python title="demo/python_demo/run_job.py"
    --8<-- "demo/python_demo/run_job.py"
    ```

## Check pending/running jobs

=== "pending"

    ```bash
    labtasker task ls --extra-filter '{"status": "pending"}'
    ```

=== "running"

    ```bash
    labtasker task ls --extra-filter '{"status": "running"}'
    ```
