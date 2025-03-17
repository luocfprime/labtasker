# Advanced Features

## Plugins

### CLI plugins

CLI plugins are particularly useful if you want to pack up your workflow and share it with others.

!!! example "Demo plugin"

    There is a demo plugin at `/PROJECT_ROOT/plugins/labtasker_plugin_task_count`.

    It creates a new custom command `labtasker task count`, which shows how many tasks are at each state.

    <script src="https://asciinema.org/a/4bVEhCtHaDD4N7FCGxssoUMfE.js" id="asciicast-4bVEhCtHaDD4N7FCGxssoUMfE" async="true"></script>

To install officially bundled plugins:

=== "PyPI"

    ```bash
    pip install 'labtasker[plugins]'
    ```

=== "GitHub"

    ```bash
    pip install 'labtasker[plugins] @ git+https://github.com/fkcptlst/labtasker.git'
    ```

To install other plugins, simply install it like a regular Python package.

```bash
pip install labtasker-plugin-task-count
```

!!! note

    Behind the hood, it uses Typer command registry and setuptools entry points to implement custom CLI commands.

    To write your own CLI plugin, see [Setuptools Doc](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)
    and [Typer Doc](https://typer.tiangolo.com/tutorial/subcommands/nested-subcommands/) for details.

### Workflow plugins [WIP]

## Custom resolvers

Sometimes after we fetched task args from the server, we need to convert it into other types (such as dataclasses) for
further processing.

Suppose you have a set of tasks submitted like this:

```python title="demo/advanced/custom_resolver/submit_job.py"
--8<-- "demo/advanced/custom_resolver/submit_job.py"
```

You can manually specify the `required_fields` and convert them into your own dataclass manually:

```python title="demo/advanced/custom_resolver/wo.py"
--8<-- "demo/advanced/custom_resolver/wo.py"
```

Now, you can achieve a more elegant solution by using a custom resolver:

```python title="demo/advanced/custom_resolver/w.py"
--8<-- "demo/advanced/custom_resolver/w.py"
```

## Event system

Labtasker implements a simple event notification system based on Server Sent Events (SSE).
This is particularly useful for real-time notifications, workflows, and other use cases.

### Demo: `labtasker event listen`

We use the `labtasker event listen` command as a demo.

It will listen to the FSM state transition events from the server and print them out.

!!! example "labtasker event listen"

    <script src="https://asciinema.org/a/XT3yc8CzXrY2m97986nVA1HwR.js" id="asciicast-XT3yc8CzXrY2m97986nVA1HwR" async="true"></script>

### Demo: email notification on task failure

Using the event listener, it is very easy to implement a simple email notification system
on various events.

For example, you can listen for `pending -> failed` state transition events and
send notification email.

```python title="demo/advanced/event_system/email_on_task_failure.py"
--8<-- "demo/advanced/event_system/email_on_task_failure.py"
```

Below is a recorded demo running a simulated unstable job with 50% chance of crashing.

```python title="demo/advanced/event_system/sim_unstable_job.py"
--8<-- "demo/advanced/event_system/sim_unstable_job.py"
```

The notification script successfully captures the event and sends email.

!!! example "Email notification on task failure"

    <script src="https://asciinema.org/a/QHwatVNwEzLSd3e52k8R3bIvT.js" id="asciicast-QHwatVNwEzLSd3e52k8R3bIvT" async="true"></script>
