# Command Workers

Use a command Worker to run an existing executable for each Task without
changing its argument interface:

```bash
labtasker loop \
  --route text-eval \
  --metadata '{"hostname":"node-7","gpu_ids":["GPU-a"]}' \
  -- \
  python evaluate.py --prediction '%{prediction}' --reference '%{reference}'
```

The required `--` separates Labtasker options from the child argv. Each template
element produces exactly one child argv element. Labtasker does not join, split,
quote, or evaluate a shell command. `--metadata` accepts one strict JSON object
fixed for the Worker invocation. Labtasker does not populate hostname, scheduler,
GPU, or other resource fields automatically.

Command Workers require POSIX process-group support. Linux is release-gated and
macOS is best effort; Windows raises `NotImplementedError` before connecting to
the Server or claiming a Task. Client operations, the Server, and Python Workers
remain available on Windows on a best-effort basis.

## Template syntax

`%{path}` reads a value from the Task args object. A path consists only of ASCII
identifier segments separated by dots:

```text
%{seed}
%{judge.threshold}
```

Traversal is through JSON objects only. Array indices, hyphenated keys, Unicode
keys, quoted segments, defaults, and expressions are intentionally unsupported.
Use `%{{` when the child must receive a literal `%{` opener.

- strings are inserted directly;
- other JSON values use compact deterministic JSON;
- a missing key or non-object intermediate fails the Task before the child starts;
- an empty resolved argv element is valid;
- NUL is rejected.

All templates are compiled before the first claim, so static syntax mistakes do
not claim or fail a Task.

## Process behavior

The child inherits the Worker's environment and receives Labtasker execution
variables, including the Task ID, run ID, Queue, local run directory, and either
the HTTP URL/token or the selected local socket/directory. It also receives the
loop-scoped Worker ID used by Worker telemetry. Changing the child
process's current directory does not select a different Server.

In an interactive POSIX terminal, Labtasker uses an internal PTY and relays
input, output, and terminal size. In pipelines and schedulers it uses ordinary
pipes, drains stdout and stderr concurrently, and connects stdin to `/dev/null`.
Both modes forward output live and copy the raw bytes to the local `run.log`;
there is no public PTY option.

If writing `run.log` fails during execution, the Worker warns and continues
draining and forwarding output. The log may be incomplete; this failure alone
does not change the Task outcome.

If the child has not called `finish()`, exit code zero succeeds with `{}` and any
other exit code is a charged failure. After a successful `finish()`, a later
non-zero exit is logged locally but does not change the succeeded Task.

## Returning a result

Existing code may optionally call `finish()` from the launched program:

```python
import labtasker

labtasker.finish({"score": 0.94}, skip_if_no_labtasker=True)
```

The command process reconstructs its execution context from environment
variables. `finish()` reports the result for the current run and writes a local
journal update when possible. If the Server accepts the result but the journal
write fails, the Task remains succeeded.

The launched program can report a replace-only progress snapshot through Python:

```python
labtasker.report_progress(
    {"completed": 1200, "total": 5000, "metrics": {"val_loss": 0.8}}
)
```

Non-Python commands can use the inherited execution context through the CLI:

```bash
labtasker progress \
  --data '{"completed":1200,"total":5000,"metrics":{"val_loss":0.8}}'
```

The CLI prints `{"reported": true}` when accepted and false for an isolated
best-effort failure. Progress never completes the Task or renews its lease. The
object is otherwise unrestricted; `completed` and `total` are the optional
Labtasker WebUI convention for a determinate progress indicator.

Report Worker-level resource measurements independently of Task progress:

```python
labtasker.report_worker_telemetry({"gpu": {"utilization": 0.82}})
```

Non-Python children use the parallel CLI command:

```bash
labtasker worker telemetry --data '{"gpu":{"utilization":0.82}}'
```

Each synchronous call performs one request and replaces the latest Worker
telemetry object. A reporting failure returns or prints false without changing
the command's Task outcome. Telemetry does not renew Worker presence, and
Labtasker does not sample, retry, throttle, merge, or keep history. If periodic
sampling is useful, the child owns its scheduling or background thread.
All descendants and distributed ranks inherit the same loop-scoped Worker ID.
Their reports replace the same snapshot, so the last report committed by the
Server is visible; Labtasker does not merge fields or select one rank.

After `finish()`, the command may keep running for cleanup. When the Server
cancels or recovers the run, the Worker sends termination to the child process
group. By default it waits without a time limit. Set
`--force-stop-timeout SECONDS` to kill child processes still running after the
deadline.
