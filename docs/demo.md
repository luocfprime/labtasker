# Run the tested demo

This repository includes a complete demo: submit six independent addition
jobs, run them through a Worker, and record each total as structured result data.
The demo uses simple addition to show the same workflow used for inference,
evaluation, or other ML jobs. Start more Workers to process Tasks concurrently.

## Submit the Tasks

The submission script creates one Task for each pair of numbers and labels all
of them for the same Python implementation:

```python title="demo/basic/submit.py"
--8<-- "demo/basic/submit.py"
```

## Run the Worker

The Worker takes one Task at a time, computes its result, reports it, and asks
for another:

```python title="demo/basic/worker.py"
--8<-- "demo/basic/worker.py"
```

Run the complete workflow from the repository root:

```bash
cd demo/basic
uv run python submit.py
uv run python worker.py
uv run labtasker task list --status succeeded
uv run labtasker-server stop
```

On POSIX systems this needs no configuration: the first submission starts the
local Server for `demo/basic`. To use several Workers, run `worker.py` in several
terminals after submission. Each process claims the next available Task instead
of requiring you to split the six cases manually.

The
[`tests/e2e/test_demo.py`](https://github.com/luocfprime/labtasker/blob/main/tests/e2e/test_demo.py)
end-to-end test runs these exact two files against a real local Server and
verifies all six recorded results.
