# CLI reference

The CLI is designed for both agents and humans: stable non-interactive commands,
formatted JSON for resource operations, and ordinary readable logging for a
long-running Worker.

## Commands

```text
labtasker config show

labtasker queue create NAME
labtasker queue list
labtasker queue delete NAME [--cascade]

labtasker task submit [OPTIONS]
labtasker task get TASK_ID
labtasker task list [OPTIONS]
labtasker task count [OPTIONS]
labtasker task update [TASK_ID] (--filter FILTER) --changes JSON
labtasker task cancel TASK_ID
labtasker task requeue TASK_ID
labtasker task delete TASK_ID

labtasker loop [OPTIONS] -- COMMAND [ARG...]
labtasker-server start
labtasker-server status
labtasker-server stop [--force]
labtasker-server logs
labtasker-server serve [OPTIONS]
```

Run `--help` on any command for its exact options and accepted values.

## Command contracts

Finite resource commands are CLI forms of the same Python and HTTP operations.
They do not add hidden prompts, implicit pagination, or alternate lifecycle
rules.

| Command | Successful stdout | Contract |
| --- | --- | --- |
| `config show` | One resolved configuration object | Resolves current sources without network access, file creation, or local Server startup; never prints a token. |
| `task submit` | One Task object | `--args`/`--metadata` default to `{}`, `--priority` to `0`, `--max-attempts` to `3`, and omitted routes to `default`. Repeat `--route` for several exact routes; use `--id` for a caller-chosen idempotent Task ID. |
| `task get` | One Task object | ID-addressed; an unknown Task is an error, not `null`. |
| `task list` | `{"items":[...],"next_cursor":...}` | Returns one page. `--status`, exact `--name`, and `--filter` combine with AND. |
| `task count` | `{"count":N}` | Counts the complete selection independently of list pagination. |
| `task update TASK_ID` | The resulting Task | Replaces supplied fields on one non-running Task. |
| `task update --filter ...` | `{"matched":N,"updated":M}` | Requires an explicit filter and atomically updates all matching non-running Tasks. |
| `task cancel` | The resulting Task | Accepts pending/running; repeating on cancelled is idempotent. |
| `task requeue` | The resulting Task | Accepts pending/failed/cancelled; resets attempt and last error. Succeeded Tasks require a new submission. |
| `task delete` | Nothing | Permanently deletes one non-running Task; absent is idempotent. |
| `queue create` | One Queue object | Idempotent create-by-name. |
| `queue list` | Complete Queue array | Not paginated. |
| `queue delete` | Nothing | Non-empty requires `--cascade`; running Tasks still block deletion. |

`task update --changes` accepts only `name`, `args`, `metadata`, `priority`,
`max_attempts`, `routes`, and `result`. Supplied objects and lists are complete
replacements, not merges. Status changes use `cancel` and `requeue`; `status` is
not writable.

`labtasker loop` is a continuing Command Worker, not a finite resource command.
It claims through one exact route and executes at most one child at a time. The
required `--` separates Labtasker options from one direct argv template; see
[Command Workers](../workers/command.md).

Server commands have a separate ownership boundary:

| Command | Contract |
| --- | --- |
| `labtasker-server start` | Starts or confirms the automatic Server for the exact current directory. Ordinary local Client use starts it automatically. |
| `status` | Read-only JSON describing the current directory's local daemon state. |
| `stop [--force]` | Stops only the reverified local daemon; normal stop never sends SIGKILL. |
| `logs` | Prints the complete current local Server log; it does not follow. |
| `serve` | Runs one foreground HTTP Server. One process owns one SQLite file; non-loopback binds require `LABTASKER_SERVER_TOKEN`. |

## JSON input

`--args`, `--metadata`, and `--changes` accept one strict JSON object. The CLI
does not offer repeated `--arg key=value` parsing because that would introduce a
second type system and ambiguous coercion.

```bash
labtasker task submit \
  --args '{"seed":1,"enabled":true,"tags":["a","b"]}'
```

Shell quoting protects the JSON from the shell; it is not part of the JSON.

## Output and exit behavior

Successful resource commands print formatted JSON. Delete commands complete
quietly. Validation, configuration, API, and transport errors print a concise
message to stderr and exit non-zero without an application traceback.

Every finite Client operation identifies its selected local or HTTP Server on
stderr. Starting, waiting for, or reconnecting to a local daemon is likewise
visible; requested JSON remains alone on stdout. `labtasker-server start` and
`stop` report actions on stderr, `status` prints stable JSON on stdout, and
`logs` writes log content to stdout.

`labtasker loop` is different: it is a supervised long-running process, so it
uses ordinary timestamped logs and tees child output in real time. It does not
emit JSON Lines or hide the child behind a pager. This Command Worker requires
POSIX process-group support; on Windows it writes the unsupported-platform
message to stderr and exits with status 1 before connecting to the Server or
claiming a Task.

## Pagination

`task list` intentionally returns one page. Agents can read `next_cursor` and
make the next explicit call:

```bash
labtasker task list --limit 100 --cursor OPAQUE_CURSOR
```

There is no automatic pager or interactive confirmation. Destructive scope is
made explicit with identifiers, filters, or `--cascade` instead.
