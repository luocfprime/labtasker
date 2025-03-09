# Advanced Features

## Plugins

### CLI plugins

CLI plugins are particularly useful if you want to pack up your workflow and share it with others.

!!! tip "Demo plugin"

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

## Custom Resolvers

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
