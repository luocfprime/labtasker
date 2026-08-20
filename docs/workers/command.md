# Command Workers

The command Worker wraps an existing executable with minimal intrusion:

```bash
labtasker loop --route train -- \
  python train.py --seed '%{seed}' --config '%{config}'
```

The required `--` cleanly separates Labtasker options from the child argv. Each
template element produces exactly one child argv element. Labtasker does not
join, split, quote, or evaluate a shell command.

## Template syntax

`%{path}` reads a value from the Task args object. A path consists only of ASCII
identifier segments separated by dots:

```text
%{seed}
%{optimizer.lr}
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
not consume a Task.

## Process behavior

The child inherits the Worker's environment and receives Labtasker execution
variables, including the Task ID, run ID, Queue, Server URL, and local run
directory. The Worker tees stdout and stderr to both the terminal and the local
run log. Stdin is connected to `/dev/null`.

Exit code zero succeeds with `{}`; any other exit code is a charged failure.

## Returning a result

Existing code may optionally call `finish()` from the launched program:

```python
import labtasker

labtasker.finish({"accuracy": 0.94}, skip_if_no_labtasker=True)
```

The command process reconstructs its execution context from environment
variables. `finish()` sends the result through the same fenced run protocol and
writes a best-effort local journal update. Failure to write that local backup
does not turn an accepted Server completion into an error.

After completion, the command may keep running for cleanup. The default waits
indefinitely; `--force-stop-timeout SECONDS` can terminate a revoked child after
a deadline.
