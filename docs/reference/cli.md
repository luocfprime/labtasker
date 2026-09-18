# CLI reference

The CLI is designed for both agents and humans: stable non-interactive commands,
formatted JSON for resource operations, and ordinary readable logging for a
long-running Worker.

## Commands

```text
labtasker --version
labtasker [--labtasker-root PATH] [--auto-start-local-server] COMMAND
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

labtasker worker list [OPTIONS]
labtasker worker count [OPTIONS]
labtasker worker telemetry --data JSON

labtasker progress --data JSON
labtasker loop [OPTIONS] -- COMMAND [ARG...]
labtasker-server --version
labtasker-server serve --connection http [OPTIONS]
labtasker-server serve --connection socket [OPTIONS]
labtasker-server status [--labtasker-root PATH]
labtasker-server stop [--labtasker-root PATH] [--force]
labtasker-server logs [--labtasker-root PATH]
```

Run `--help` on any command for its exact options and accepted values.

`--labtasker-root` and `--auto-start-local-server` are global Client options and
must appear before the subcommand. The root defaults to exact
`CWD/.labtasker`; it selects config, journals, and the managed-local endpoint
without searching parents. Auto-start authority is false by default and applies
only when no URL or external socket is configured.

Both executables expose their runtime distribution version without reading
configuration, contacting a Server, or starting the local daemon. `labtasker
--version` prints `labtasker-client VERSION`, because the Client distribution
owns that executable. `labtasker-server --version` prints
`labtasker-server VERSION`. Each result is one line on stdout with exit status
0. Root `--help` lists the option but does not print the current version.

## Command contracts

Finite resource commands are CLI forms of the same Python and HTTP operations.
They do not add hidden prompts, implicit pagination, or alternate lifecycle
rules.

Business responses that report an older Server package version produce a
`[labtasker] warning:` on stderr recommending a Server upgrade. This adds no HTTP
request and changes neither stdout nor exit status. A Client instance warns once
per distinct older Server version, so a long-running Worker does not repeat the
warning on every heartbeat. Separate CLI invocations may each warn. Servers that
do not advertise a usable version do not trigger this warning.

| Command | Successful stdout | Contract |
| --- | --- | --- |
| `config show` | One resolved configuration object | Resolves current sources without network access, file creation, or local Server startup; never prints a token. |
| `task submit` | One Task object | `--args`/`--metadata` default to `{}`, `--priority` to `0`, `--max-attempts` to `3`, and omitted routes to `default`. Repeat `--route` for several exact routes; use `--id` for a caller-chosen idempotent Task ID. |
| `task get` | One Task object | ID-addressed; an unknown Task is an error, not `null`. |
| `task list` | `{"items":[...],"next_cursor":...}` | Returns one page. `--status`, exact `--name`, `--name-fuzzy`, and `--filter` combine with AND. |
| `task count` | `{"count":N}` or a grouped page | Counts the complete selection; `--group-by` opts into grouped counts. |
| `task update TASK_ID` | The resulting Task | Replaces supplied fields on one non-running Task. |
| `task update --filter ...` | `{"matched":N,"updated":M}` | Requires an explicit filter and atomically updates all matching non-running Tasks. |
| `task cancel` | The resulting Task | Accepts pending/running; repeating on cancelled is idempotent. |
| `task requeue` | The resulting Task | Accepts pending/failed/cancelled; resets attempt and last error. Succeeded Tasks require a new submission. |
| `task delete` | Nothing | Permanently deletes one non-running Task; absent is idempotent. |
| `worker list` | `{"items":[...],"next_cursor":...}` | Lists unexpired observations by ID ascending; accepts `--filter`, `--limit`, `--cursor`, and `--queue`. |
| `worker count` | `{"count":N}` or a grouped page | Counts unexpired observations; accepts `--filter`, `--group-by`, `--limit`, `--cursor`, and `--queue`. |
| `worker telemetry` | `{"reported":true|false}` | Inside a Command Worker child, synchronously replaces the current Worker invocation's latest strict JSON-object telemetry snapshot. |
| `progress` | `{"reported":true|false}` | Inside a Command Worker child, replaces the current run's latest strict JSON-object snapshot. A best-effort transport/revocation failure reports false without failing the command. |
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
`--max-consecutive-failures INTEGER` defaults to `5` and must be positive.
`--metadata JSON` supplies one strict JSON object describing that Worker
invocation. Labtasker does not automatically populate hostname, scheduler, GPU,
or other resource fields.
The Worker exits `1` after reporting that many consecutive execution failures;
see [failure protection](../guides/failure-recovery.md#consecutive-failure-protection).

Server commands have a separate ownership boundary:

| Command | Contract |
| --- | --- |
| `serve --connection http\|socket` | Runs one foreground Server, or a detached one with `--daemon`. Transport selection is required. `--database-filesystem` defaults to `auto`; one process owns one SQLite file. |
| `status [--labtasker-root PATH]` | Read-only JSON describing the daemon selected by exact root; it creates and cleans nothing. |
| `stop [--labtasker-root PATH] [--force]` | Stops only the reverified daemon for that root; normal stop never sends SIGKILL. |
| `logs [--labtasker-root PATH]` | Prints that daemon's complete log; it does not follow. |

`serve` defaults the root to exact `CWD/.labtasker`, its database to
`<root>/server.db`, and detached mode to false. HTTP defaults to
`127.0.0.1:8000`; socket mode derives an owner-only socket from the root.
`--host`/`--port` and `--socket` are mutually transport-specific. `--daemon`
changes lifecycle only. A matching detached launch is idempotent; a conflicting
launch fails and asks the operator to stop the existing daemon first. There is
no public `start` command.

## Inspect route demand and Worker activity

```bash
labtasker task count --status pending --group-by routes,status
labtasker worker count --group-by route,status
labtasker worker list --filter 'route == "sdxl" and status == "busy"'
labtasker worker list --filter 'metadata.hostname == "node-7"'
labtasker worker count --filter 'telemetry.gpu_utilization < 0.1'
```

`--group-by` is one comma-separated argument with no spaces. Task fields are
`routes` and `status`; Worker fields are `route` and `status`. Either order is
valid. Empty fields, duplicates, unsupported fields and repeated `--group-by`
options are usage errors. Without grouping, count output remains `{"count":N}`.

Grouped output contains `group_by`, the complete matching `count`, one page of
`items` with `key`/`count`, and `next_cursor`. `--limit` (default 100, maximum
1000) and `--cursor` require grouping on count commands. Fetch later pages
explicitly with the same filters and grouping. Multi-route Tasks contribute to
every compatible route group; group counts may overlap. Pages reflect current
data rather than a fixed snapshot.

Worker results are supplementary observations: `idle` means waiting, and `busy`
includes reporting and post-finish cleanup. Delays and temporary missing Workers
are possible. No observed Worker for a route does not prove no process exists.
See [HTTP observation semantics](http-api.md#worker-observations).

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

Successful finite resource commands print one two-space-indented JSON document
with no ANSI styling. Delete commands complete quietly. Handled configuration,
transport, and API errors print the stable Labtasker error envelope to stdout
and exit `1` without an application traceback. stdout is therefore the single
machine-readable response channel for finite commands: callers distinguish a
successful value from an error envelope with the exit status and the top-level
`error` key. CLI argument or usage errors remain natural-language stderr and
exit `2`; an interrupted Worker retains exit `130`.

Every finite Client operation identifies its selected managed-local, external
socket, or HTTP Server on stderr after connecting. The single `[labtasker]
connected` line explicitly names the endpoint and its Unix, HTTP, or HTTPS
transport; managed-local connections also identify the root, database and
socket. Authorized startup transitions are likewise visible. Requested
data or a handled error envelope remains alone on stdout. Finite Client
diagnostics use `[labtasker]`, while
Server CLI diagnostics use `[labtasker-server]`. Detached `serve` and `stop`
report actions on stderr, `status` prints stable JSON on stdout, and `logs`
writes log content to stdout.

`labtasker loop` is different: it is a supervised long-running process, so it
uses ordinary logs whose default format includes a millisecond UTC timestamp,
level and `[labtasker]` prefix, and tees child output in real time. It does not
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

## Search Task names

```bash
labtasker task list --name-fuzzy "tr ev"
labtasker task count --name-fuzzy "tr ev"
labtasker task list --name "train_model_eval"
```

`--name-fuzzy` ignores case and surrounding whitespace. Every whitespace-separated
word must appear as a subsequence in the Task name; words can appear in any order.
`tr ev` and `ev tr` both match `train_model_eval`. Empty searches add no
restriction. Punctuation is literal; this is not the full fzf query language.
The Server searches the Queue before pagination and preserves the chosen ordering.
All supplied selectors combine with AND. Keep the same search input when reusing
a cursor. `--name` and `--filter 'name == "..."'` retain strict equality.
