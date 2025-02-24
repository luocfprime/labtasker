# Tutorial: Basic Workflow

!!! tip

    **The code for this page is available on [GitHub](https://github.com/fkcptlst/labtasker/tree/main/demo).**

    Labtasker supports 2 sets of client APIs:

    - Python: Modify your Python code with a few lines of changes to support Labtasker.
    - Bash: No modification to your Python code is required. Simply wrap your command with `labtasker loop ...`.


!!! note "demo step by step"

    <script src="https://asciinema.org/a/tRC0sFsoITjBr0Ik4e9DLXLEm.js" id="asciicast-tRC0sFsoITjBr0Ik4e9DLXLEm" async="true"></script>

## Prerequisites

**Make sure you have a deployed server.**

You can follow the [Deployment](../install/deployment.md) guide to easily deploy a server.

**Make sure you have installed client tools.**

Following [Installation](../install/install.md).

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
