# Command Workers

The command Worker wraps an existing executable with minimal intrusion:

```bash
labtasker loop --route text-eval -- \
  python evaluate.py --prediction '%{prediction}' --reference '%{reference}'
```

The required `--` cleanly separates Labtasker options from the child argv. Each
template element produces exactly one child argv element. Labtasker does not
join, split, quote, or evaluate a shell command.

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
not consume a Task.

## Process behavior

The child inherits the Worker's environment and receives Labtasker execution
variables, including the Task ID, run ID, Queue, local run directory, and either
the HTTP URL/token or the already selected local socket/directory. It never
re-resolves local mode from the child's CWD.

In an interactive POSIX terminal, Labtasker uses an internal PTY and relays
input, output, and terminal size. In pipelines and schedulers it uses ordinary
pipes, drains stdout and stderr concurrently, and connects stdin to `/dev/null`.
Both modes forward output live and copy the raw bytes to the local `run.log`;
there is no public PTY option.

If the child has not called `finish()`, exit code zero succeeds with `{}` and any
other exit code is a charged failure. After a successful `finish()`, a later
non-zero exit is logged locally but cannot rewrite the succeeded Task.

## Returning a result

Existing code may optionally call `finish()` from the launched program:

```python
import labtasker

labtasker.finish({"score": 0.94}, skip_if_no_labtasker=True)
```

The command process reconstructs its execution context from environment
variables. `finish()` sends the result through the same fenced run protocol and
writes a best-effort local journal update. Failure to write that local backup
does not turn an accepted Server completion into an error.

After completion, the command may keep running for cleanup. The default waits
indefinitely after sending termination to a revoked child process group;
`--force-stop-timeout SECONDS` force-kills any remainder after the deadline.
