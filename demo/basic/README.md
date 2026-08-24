# Basic runnable demo

This demo submits six independent addition Tasks, runs them through a Python
Worker, and records each total as structured Task result data. From the
repository root:

```bash
cd demo/basic
uv run python submit.py
uv run python worker.py
uv run labtasker task list --status succeeded
uv run labtasker-server stop
```

Start `worker.py` in more terminals to process the Tasks concurrently. Replace
the addition function with an inference, evaluation, or experiment function in a
real project.

The documentation includes these exact source files, and
`tests/e2e/test_demo.py` executes them against a real local Server.
