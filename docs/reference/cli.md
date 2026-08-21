# CLI reference

The CLI is designed for both agents and people: stable non-interactive commands,
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
