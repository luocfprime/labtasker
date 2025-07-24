# `labtasker loop`

!!! abstract

    This page details the loop related operations.

    `labtasker loop` is the core command that runs the job automatically in a looped fashion.
    You can use it via Bash or Python.

## What does loop do

Labtasker loop automatically fetch tasks and run them.

It does the following steps (mainly):

1. Create worker if not exist or specified.
   (keeping track of workers helps to prevent a single failing node from depleting all tasks in the queue by crashing
   repeatedly)
2. Call fetch_task API.
3. Setup necessary context.
4. Start a heartbeat thread.
5. Run task.
6. Submit summary (`success`/`failed`).

## Usage

### Basic

=== "Bash Usage"

    For bash, you may use the `labtasker loop` command.

    See the example in the [Basic Workflow](./basic.md#step-2-run-job).

=== "Python Usage"

    For python, you may use the `@labtasker.loop()` decorator.

    See the example in the [Basic Workflow](./basic.md#step-2-run-job).

??? note "About the `required_fields`: the No more, No less principle"

    Labtasker fetches tasks based on specific requirements for the `args`.
    It follows a strict **"No More, No Less"** principle:

    - **No More**: Tasks must not have extra fields that aren't needed.
      - **No Less**: Tasks must include all required fields.

    ---

    ### Why is this rule important?

    #### **Case 1: The "No More" Rule**

    *Tasks should not include extra fields that aren't used.*

    For example, consider a task in the queue:

    ```yaml
    task_id: 1
    args:
        prompt: "an astronaut riding a horse"
        guidance_scale: 7.5
    ```

    Now, let’s say you have a script, `job.py`, with the following arguments:

    ```python
    # job.py
    parser.add_argument("--prompt", type=str, required=True)
    parser.add_argument("--guidance_scale", type=float, default=100)
    ```

    If you run `labtasker loop -- python job.py '%(prompt)'`, it fetches the task.
    However, since you didn’t specify `guidance_scale` in the command, `job.py` will use the default value (`100`), even though the task’s `args` says `guidance_scale: 7.5`. This mismatch can cause confusion because:

    - The task’s recorded `args` don’t match what was actually used during execution.
    - When you review the experimental records, extra fields in `args` might lead to
    incorrect assumptions.

    ---

    #### **Case 2: The "No Less" Rule**

    *Tasks must include all required fields.*

    For instance, imagine you need to run this command:

    ```bash
    labtasker loop -- python job.py '%(prompt)' '%(guidance_scale)'
    ```

    But the task fetched looks like this:

    ```yaml
    task_id: 2
    args:
        prompt: "an astronaut riding a horse"
    ```

    Here, the `guidance_scale` is missing from `args`, causing the command to fail because
    a required field is not provided. This is why all required fields must be present in the task's `args`.

    ---

    Therefore, the **"No More, No Less"** rule ensures tasks are fetched with exactly
    the right fields—no extra or missing ones—to avoid errors and inconsistencies.

    ---

    **Can this be bypassed?**

    What if you still want to fetch tasks with extra fields, even though it might have drawbacks? Is it possible?

    The answer is yes, and there’s a simple workaround:

    ```bash
    echo '%(guidance_scale)' > /dev/null && labtasker loop -- python job.py '%(prompt)'
    ```

    This trick makes Labtasker think you’ve used the extra field. However, it’s always better to be explicit.
    If you want to ignore extra fields, make sure to do it intentionally.

### Use filter to get only the task you want

Similar to the `labtasker task ls` command, loop also supports filtering using MongoDB syntax queries
to fetch only the task you want to run.

=== "Bash Usage"

    ```bash
    # example to execute task with tags "experimental" or "diffusion"
    labtasker loop --extra-filter '{"metadata.tags": {"$in": ["experimental", "diffusion"]}}' -- python job.py %(prompt)
    ```

=== "Python Usage"

    ```python
    @labtasker.loop(
        required_fields=["prompt"],
        extra_filter={"metadata.tags": {"$in": ["experimental", "diffusion"]}}
    )
    def main():
        # your job code here
    ```

### Upon task failure

When a task fails, you will be presented with a 10-second countdown to choose one of the following options:

1. **Report:** Mark the task as failed and submit the error message. The task state will be set to either "pending" or "
   failed," depending on the remaining retry attempts. Additionally, the worker's remaining attempts will be reduced by
   one.
2. **Ignore:** Disregard the failure, reset the task state to "pending," restore the retry count as if no failure
   occurred, and proceed to the next task.

By default, the system selects the first option, which is ideal for background task execution, allowing Labtasker to
automatically report failures.

The second option is useful for debugging scenarios where you do not want to re-submit or manually adjust the task
state. It enables you to isolate the failure without affecting subsequent tasks.

<script src="https://asciinema.org/a/ifCMwvWqACatCnE22ZCkRQ7lH.js" id="asciicast-ifCMwvWqACatCnE22ZCkRQ7lH" async="true"></script>
