# Tutorial: Basic Workflow

!!! tip

    **The code for this page is available on [GitHub](https://github.com/luocfprime/labtasker/tree/main/demo).**

    Labtasker supports 2 sets of client APIs:

    - Python Demo: Modify your Python Demo code with a few lines of changes to support Labtasker.
    - Bash Demo: No modification to your Python Demo code is required. Simply wrap your command with `labtasker loop ...`.

## Prerequisites

**Make sure you have a deployed server.**

You can follow the [Deployment](../install/deployment.md) guide to easily deploy a server.

**Make sure you have installed client tools.**

Following [Installation](../install/install.md).

**Make sure you have configured client.**

```bash
labtasker init
```

It will guide you step-by-step:

<script src="https://asciinema.org/a/f0XrD6BC8zbtYTth6FCpxusDT.js" id="asciicast-f0XrD6BC8zbtYTth6FCpxusDT" async="true"></script>

!!! tip ""

    See more details about creating a queue in [Queue Manual#create-queue](./manual_queue.md#create-queue).

## Step 1. Submit job arguments via Python Demo or CLI tool

=== "Bash Demo"

    ```bash title="demo/basic/bash_demo/submit_job.sh"
    --8<-- "demo/basic/bash_demo/submit_job.sh"
    ```

=== "Python Demo"

    ```python title="demo/basic/python_demo/submit_job.py"
    --8<-- "demo/basic/python_demo/submit_job.py"
    ```

!!! tip ""

    See more details in [Task Manual#submit-tasks](./manual_task.md#submit-tasks).

## Step 2. Run job

=== "Bash Demo"

    ```bash title="demo/basic/bash_demo/run_job.sh"
    --8<-- "demo/basic/bash_demo/run_job.sh"
    ```

    where

    ```python title="demo/basic/bash_demo/job_main.py"
    --8<-- "demo/basic/bash_demo/job_main.py"
    ```

=== "Python Demo"

    ```python title="demo/basic/python_demo/run_job.py"
    --8<-- "demo/basic/python_demo/run_job.py"
    ```

## Check pending/running jobs

=== "pending"

    ```bash
    labtasker task ls -s pending
    ```

=== "running"

    ```bash
    labtasker task ls -s running
    ```

!!! tip ""

    See more details in [Loop Manual#create](./manual_loop.md).
