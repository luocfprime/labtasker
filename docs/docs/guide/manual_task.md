# `labtasker task`

!!! abstract

    This page details the task related operations.

## Submit tasks

### Specifying task args via `--args` option or `[ARGS]` argument

You can submit the task args that you want to run.

=== "Specify args via `--args` option"

    ```bash
    labtasker task submit --args '{"foo.bar": 0.1}'
    ```

=== "Specify args via `[ARGS]` argument"

    !!! tip

        Specify task args via `[ARGS]` argument is convenient if you have a job script that takes CLI arguments directly.

        Normally, you would run it like this (suppose your job script takes `--foo.bar` as a CLI argument):

        ```bash
        python train.py --foo.bar 0.1
        ```

        You can directly copy and paste the `--foo.bar` argument as a positional argument to `labtasker task submit`.

        ```bash
        labtasker task submit -- --foo.bar 0.1
        ```

!!! tip "arg cast to python primitive"

    By default, `labtasker task submit` will cast the `args` to python primitive types.

    Therefore,  if you specify `-- --foo 0.1`, it will be cast to `float` type rather than remain as a string.

    The same principle applies to `labtasker task update`.

!!! tip "Dict nesting"

    Labtasker parses the **dot-separated top-level keys** as keys to nested dicts.

    For example:

    `--foo.bar 0.1` would give you task `args` as `{"foo": {"bar": 0.1}}`.

    If you are accessing task `args` via `labtasker.task_info().args`,
    remember to access like `labtasker.task_info().args["foo"]["bar"]` rather than `labtasker.task_info().args["foo.bar"]`.

    The same principle applies to `args`, `metadata`, `summary` for queues, tasks and workers.

### Metadata

Metadata is handy if you want to filter tasks according to certain conditions.

For example, you may implement a custom tag system to manage your tasks through metadata.

!!! example annotate

    ```bash
    # submit a task 1
    labtasker task submit --metadata '{"tags": ["test", "experimental"]}' -- --foo.bar 0.1
    # submit a task 2
    labtasker task submit --metadata '{"tags": ["tag-baz"]}' -- --foo.baz 0.2

    # loop up tasks that contains 'experimental' or 'tag-baz' (1)
    labtasker task ls --extra-filter '{"metadata.tags": {"$in": ["experimental", "tag-baz"]}}' --quiet --no-pager

    # output:
    # dd4e3ce3-25a8-4176-bf4b-dba82187679d
    # 155f3872-1a07-45c9-85fb-51fce5cc29b5
    ```

1. See more about `labtasker task ls` in [List tasks](#list-query-tasks).

## List (query) tasks

By default, `labtasker task ls` displays all tasks in the queue. Output is shown through a pager like `less` by default. Add `--no-pager` to display directly in the terminal.

You can filter tasks using:

- `--task-id` or `--task-name` for basic filtering
- `--extra-filter` for advanced queries

### Using Extra Filters

Choose between two filter syntaxes:

1. **Python Native Syntax**: Intuitive to use but less powerful.
   ```bash
   # Find tasks where args.foo.bar > 0.1
   labtasker task ls --extra-filter 'args.foo.bar > 0.1' --quiet --no-pager
   ```
   ==Note:== Does not support `not in`, `not expr`, or `!=` due to null value ambiguities

2. **MongoDB Syntax**: More powerful but requires MongoDB knowledge.
   ```bash
   # Find tasks where args.foo.bar > 0.1
   labtasker task ls --extra-filter '{"args.foo.bar": {"$gt": 0.1}}' --quiet --no-pager
   ```

You can see the transpiled query using `--verbose` option.

## Modify (update) tasks

By default, `labtasker task update` will open terminal editor (such as vim) to allow you edit the task info.

However, you may specify the `--update` option or the `[UPDATES]` argument to specify the fields to update instead of
opening the editor.

=== "Specify args via `--update`/`-u` option"

    ```bash
    # Example of updating task
    labtasker task update --id 9ca765ce-94fe-4e2f-b88b-954b3412e607 -u 'args.arg1=0.3' -u 'args.arg2={"arg21": 0.4}'
    ```

=== "Specify args via `[UPDATES]` argument"

    ```bash
    # Example of updating task
    labtasker task update --id 9ca765ce-94fe-4e2f-b88b-954b3412e607 -- args.arg1=0.3 args.arg2='{"arg21": 0.4}'
    ```

If you wish to use this command in a bash script, use `--quiet` option to disable unnecessary output and confirmations.

## Delete tasks

```bash
labtasker task delete --help
```
