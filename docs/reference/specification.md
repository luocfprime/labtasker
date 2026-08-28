# Labtasker v2 specification

Status: reviewed 2.0.0 design specification

This is the authoritative, standalone user-visible contract for Labtasker v2. Its
intended reader has the repository but no access to the design conversation that
produced it. The reader must not need chat history or undocumented assumptions to
interpret a decided behavior.

This document records agreed user-visible changes from Labtasker v1. It is not a
greenfield redesign. V1 is the feature inventory and source of real usage
experience, not an automatic compatibility contract: useful and well-designed
behavior is retained, poorly designed behavior is corrected, and redundant
features are removed. This specification is the sole maintained design contract;
the implementation and tests must agree with it.

Each section is either **Decided** or **Open**. Open choices are added only when a
concrete v1 problem or an already-decided change requires them.

## 0. Scope and minimalism

Status: **Decided**

Minimalism is a hard requirement. A v1 feature is included in v2 only when it is
part of the core experiment-task workflow or is supported by a concrete current
use case. Existing code, documentation or backward compatibility is not by itself
a reason to retain a feature.

Before retaining or adding a feature, require clear answers to:

1. Which real experiment workflow needs it?
2. Can the same outcome be composed from an existing smaller primitive?
3. Does it add a concept, state, default or failure mode users must understand?
4. Can it be deferred without blocking submit, run, recover or inspect workflows?

Minimalism means a small, complete and polished framework, not a broad collection
of shallow features. Every feature admitted to the public surface must be
delivered as one complete vertical slice:

- one canonical user model with unambiguous defaults;
- consistent HTTP, Python and CLI semantics where those surfaces apply;
- explicit validation, error behavior and concurrency guarantees;
- migrations and compatibility behavior when persisted data is affected;
- focused tests for its core invariants and failure paths; and
- concise documentation with at least one real end-to-end workflow.

A feature that cannot meet this bar in the current milestone is omitted entirely.
Do not expose public stubs, experimental parallel APIs, partially implemented
modes or extension points for hypothetical future work. Deferred features should
leave no concepts or configuration burden in the current release.

V2 also rejects ambiguous convenience syntax. If a public form has multiple
plausible readings and the same intent can be written explicitly, the ambiguous
form is invalid rather than assigned a guessed meaning. Prefer one canonical
spelling over aliases, implicit coercion, merge rules or context-dependent
interpretation.

V2 is also a subtractive refactor. Every touched v1 feature must be classified as
retained, redesigned or deleted; adding a replacement does not justify carrying
the old mechanism beside it. When a feature is deleted, remove its public option,
configuration, implementation branches, dependencies, tests and documentation
together. Do not retain dormant compatibility switches for features that have no
current use case.

### 0.1 Standalone specification standard

Every **Decided** section must be understandable and implementable without the
conversation that led to it. Normative text must define, where applicable:

- the problem and concrete workflow motivating the design;
- every public term before relying on it;
- the canonical HTTP, Python and CLI behavior and all defaults;
- valid inputs, invalid inputs, stable errors and observable outputs;
- state, retry, idempotency and concurrency behavior;
- at least one ordinary example and any non-obvious boundary example; and
- deliberately unsupported behavior, especially where v1 offered a nearby form.

Do not write conclusions such as “as discussed,” “use the obvious behavior,” or
“handled normally.” A decision log entry is an index and historical record, not a
substitute for normative prose. If a required choice is unresolved, mark the
relevant section **Open** and state the exact question; do not leave contradictory
examples or silently choose an implementation detail.

When later discussion changes a decision, update the normative section, examples,
error behavior, decision log, implementation plan and comparison table together.
Delete superseded alternatives unless their rejection is necessary to explain a
public boundary.

### 0.2 Agent-first design

Adapting Labtasker to the agent-coding era is a primary v2 objective, not a CLI
formatting preference. An agent must be able to complete every core workflow—set
up, submit, inspect, run, diagnose, recover and mutate tasks—without scraping a
human UI or relying on undocumented state.

Agent-friendly interfaces require:

- explicit operations with deterministic semantics and defaults;
- machine-readable request, response and error structures;
- stable identifiers, field names, error codes and process exit codes;
- non-interactive operation with no behavior changes based on TTY detection;
- safe retry through idempotency or clearly documented conflict behavior;
- complete inspection APIs before mutation, with no silent pagination or output
  truncation;
- actionable errors that identify the failed object, operation and next valid
  actions; and
- one canonical behavior shared by HTTP, Python and CLI instead of separate
  convenience implementations.

Agent-first does not mean embedding an LLM, MCP server or general agent framework
into Labtasker. V2 provides polished, composable primitives; external agents use
those primitives through the ordinary public contract.

Agent-first also does not mean machine-only presentation. Agents can understand
clear natural language, and humans still inspect the same commands and logs.
Machine-facing data keeps a stable structure, but JSON is formatted, error
objects retain a readable `message`, and operational logs use concise natural
language. V2 does not sacrifice first-read clarity merely to maximize structural
encoding or add parallel human/machine output modes without a concrete need.

Agent-first also does not mean agent-in-the-loop execution. An agent configures
and starts workers, observes ordinary logs and state, and performs later
diagnosis or recovery. Once a worker starts, its claim/execute/report loop is
autonomous:

- task progress never waits for an agent response or approval;
- failure handling is selected by deterministic local rules or explicit error
  classes;
- the worker remains correct when no agent is currently connected; and
- supervision may observe or act later but is not part of the runtime protocol.

Labtasker distributes one maintained `labtasker` Agent Skill for those external
agents. `skills/labtasker/` is its canonical package: a short `SKILL.md` entry
point plus its directly linked references. The repository
exposes that same content through two user installation paths: a Claude Code
marketplace rooted at `.claude-plugin/`, and the open Agent Skills repository
layout consumed by `npx skills add`. `.agents/skills/labtasker` is a relative
symlink to the canonical directory for repository-local discovery; it is not an
independent copy. The skill must describe the current v2 names and behavior and
must not preserve obsolete v1 commands or models as compatibility guidance.

The distributable product skill is distinct from contributor-only repository
skills such as release preparation or public-contract changes. Installing the
product skill grants an agent knowledge, not permission to start shared services,
perform destructive mutations, allocate resources, publish releases, or bypass
the ordinary Labtasker authorization and fencing contract.

V2's primary interaction target is an agent or another program. The CLI is an
automation interface over the HTTP API, not an incomplete TUI and not a temporary
substitute for a future UI:

- commands are non-interactive;
- information and mutation commands expose stable structured output and exit
  codes;
- stdout carries machine-readable finite-command responses while diagnostics go
  to stderr;
- successful JSON output is UTF-8, indented by two spaces, contains no ANSI
  styling and ends with one newline; pretty-printing never changes its schema;
- no operation is available only through a human-oriented prompt, pager or
  interactive editor;
- destructive actions require explicit command arguments rather than confirmation
  prompts;
- the core CLI has no table renderer, spinner, syntax highlighter or terminal UI
  state; and
- agent and shell composition replace convenience features whose behavior can be
  expressed by ordinary commands.

The built-in rich pager, custom pager machinery and other presentation-oriented
terminal features are removed. A future TUI or UI must be a separate client of the
same public API rather than presentation logic accumulated inside the CLI. Do not
compromise the CLI contract for a temporary human-facing experience.

The outcomes exposed by v1's failure prompts remain useful, but neither a human nor
an agent participates synchronously after worker startup. V2 expresses those
outcomes as deterministic error classes described separately below.

### 0.3 Packaging and v1 compatibility

V2 publishes three distributions from one monorepo:

```text
labtasker          Convenience installation for the default local experience
labtasker-client   Python Client, Worker API and user CLI
labtasker-server   FastAPI Server, persistence, migrations and Server CLI
```

The `labtasker-client` distribution owns the import package `labtasker` and the
`labtasker` executable. The `labtasker-server` distribution owns the import
package `labtasker_server` and the `labtasker-server` executable. Neither runtime
distribution depends on the other. The `labtasker` distribution is a code-free
convenience metapackage that depends on matching-release Client and Server
distributions, so ordinary `pip install labtasker` provides the complete default
local mode. A deployment or experiment environment that needs only one side
installs `labtasker-client` or `labtasker-server` directly. An extra such as
`labtasker[slim]` is not used because Python extras add dependencies and cannot
subtract the Server from the default installation.

All three distributions use the same release version and are published together
initially, but independently installed Client and Server runtime protocol does
not require exact package-version equality. V2 creates no shared runtime
`labtasker-core` distribution.

The first public v2 package version is `2.0.0` for all three distributions. “V2”
and the `/api/v2` prefix describe the breaking product/protocol generation; the
initial release is not separately called package `0.1.0`.

Compatibility is deliberately one-way at the product boundary: the v2 Client
speaks only `/api/v2`, never probes or falls back to v1, and the v2 Server exposes
no v1 adapter endpoint. V1 and v2 deployments may run separately during a manual
cutover, but their clients, servers and databases are not mixed. V1 MongoDB data
is not imported during v2 startup; a future migration utility must be an explicit
operator action justified by a real migration need.

### 0.4 Platform and release boundary

Linux is the fully supported and release-gated 2.0.0 platform, including Worker
process cancellation and the real single-node torchrun/Accelerate suite. The
ordinary Client, Server and Python Worker are kept portable on macOS and Windows,
and the Command Worker is kept portable on macOS; those paths are best effort in
the initial release, so a platform-specific failure does not block 2.0.0.

The Command Worker is unsupported on Windows. Its execution contract requires
the Worker to create and later terminate or kill the child's entire local process
group. A Windows implementation based only on `Popen.terminate()` or
`Popen.kill()` can terminate the direct child while leaving launcher ranks or
other descendants running. Rather than expose that weaker behavior,
`run_command_worker` checks for POSIX process-group support and raises the built-in
`NotImplementedError` with the detected platform in its message before Client
construction, network access, Task claim, journal creation or child startup. The
CLI catches that exception, writes its message to stderr and exits 1. Windows
ConPTY and Windows distributed-launcher support are outside the v2 contract
because both depend on this unsupported executor.

The automatic local Server is likewise a POSIX feature in the initial release.
It requires an owner-only Unix-domain socket, advisory file locking and a daemon
process detached from its launching terminal. A platform without those required
capabilities rejects implicit local mode before creating `.labtasker`, starting a
process or opening a database, and tells the user to configure an explicit HTTP
URL. Ordinary HTTP Client and foreground HTTP Server operation remain best effort
on Windows as stated above; v2 does not silently substitute a loopback TCP daemon
for the Unix-socket local contract.

“Best effort” and “unsupported” are distinct platform classifications. Best
effort permits an ordinary documented path to run even though that platform is
not in the release gate. It does not permit a feature that this specification
explicitly marks unsupported on the detected platform to run speculatively. A
public Client, Worker or Server entry point for such a feature must perform a
deterministic platform or required-capability check and raise
`NotImplementedError` before network access, Task claim, journal creation,
database mutation or child-process startup. It must not silently substitute
semantically weaker behavior or rely on a later import, spawn, signal or system
call failure. The message identifies both the feature and detected platform.

Absence from a CI or release matrix alone does not make a feature unsupported,
and therefore does not justify rejecting it. A documented implementation choice
that preserves the promised behavior is also not a rejection case: for example,
v2 selects pipe mode for a noninteractive POSIX execution because PTY is not a
public requested feature and terminal preservation affects presentation rather
than Task semantics.

Every release must pass unit tests, real temporary-SQLite integration, HTTP and
OpenAPI contract tests, Client-to-Server end to end, deterministic concurrency
races, concurrent local-daemon startup/recovery, fresh schema plus every supported
Alembic forward-upgrade fixture, the fake distributed launcher, the real Linux
single-node torchrun/Accelerate suite, and—after 2.0.0—the previous released v2
Client core flow against the candidate Server. V2 sets no arbitrary coverage
percentage and does not block release on a large probabilistic stress suite or a
complete macOS/Windows matrix.

### 0.5 Technology baseline

The initial implementation targets Python 3.11 or newer and uses one monorepo
workspace with the three distributions from section 0.3. The selected stack is
deliberately conventional:

- the `labtasker-client` distribution's `labtasker` package uses Pydantic 2 for
  public boundary models and
  `TaskArg` strict-schema validation, synchronous httpx for HTTP transport and
  Typer for its CLI;
- `labtasker-server` uses FastAPI/Pydantic 2 for HTTP, synchronous SQLAlchemy 2.x
  plus Alembic for SQLite persistence and migration, Uvicorn as the single
  `serve` process, and Typer for the Server CLI; and
- tests use pytest against real temporary SQLite databases and real Client/Server
  boundaries where behavior depends on persistence or protocol semantics.

This baseline does not add async HTTP/database variants, SQLModel, a shared core
distribution, repository/plugin abstractions or multiple storage backends. Exact
compatible dependency patch versions belong to package metadata and lock files;
they are not a user-visible protocol negotiation mechanism.

## 1. Explicit routing

Status: **Decided**

### 1.1 Contract

Workers claim with exactly one route. Tasks store one or more compatible routes:

```text
Worker claim:
  route: str

Task:
  routes: non-empty set[str]
```

A task is eligible for a worker only when:

```text
task.status == pending
AND worker.route IN task.routes
```

Queue membership, state and claim ordering still apply. Argument keys and values
do not participate in server-side eligibility.

### 1.2 Defaults and matching

- The default worker route is `default`.
- The default task route set is `{default}`.
- Matching is exact and case-sensitive.
- A task route set is non-empty and unordered.
- Its JSON/Python representation is a duplicate-free list sorted lexicographically.
- A worker declares one route, not a list of routes.
- There are no wildcards, regular expressions, negation, route priority or
  fallback order.
- An unknown route is valid. A task using it remains pending until a worker claims
  with that route.

Route and Queue identifiers use one deliberately plain wire-safe grammar:

```text
[A-Za-z0-9][A-Za-z0-9._-]{0,127}
```

They are 1–128 ASCII characters, retain case and match case-sensitively; `SDXL`
and `sdxl` are distinct. V2 performs no lowercasing or other normalization. The
larger bound leaves room for descriptive Agent-generated route names while still
preventing unbounded identifiers in URLs, indexes, logs and local paths. Human
description belongs in the Task `name`, not by extending route syntax with
whitespace, slashes or arbitrary Unicode.

### 1.3 Meaning of a route

A route is an opaque execution-compatibility label. It is not a persistent Route,
Provider or Worker entity. The server does not register routes, report whether
they are online, or verify the implementation behind a claimed route.

Multiple worker processes may use the same route. Sharing a route means that tasks
do not need to distinguish those workers. Implementations that may require
separate rollout or selection should use separate names, such as
`diffusers-sdxl` and `comfy-sdxl`, rather than a shared `sdxl` route.

### 1.4 Rolling changes

Starting a new worker never changes the routing of existing tasks implicitly:

```text
old worker: route = sdxl
new worker: route = sdxl-v2

new-only task:       routes = {sdxl-v2}
new-or-old task:     routes = {sdxl, sdxl-v2}
old task migrated:   {sdxl} -> {sdxl, sdxl-v2}
```

If a new worker should help with an old backlog, users explicitly add its route to
the selected pending tasks. This makes the compatibility decision visible on the
tasks and prevents a newly started worker from unexpectedly stealing old work.

### 1.5 Task route update

Routes are changed through the ordinary Task update API, not through a separate
route-mutation action. V2 supports both an ID-addressed update and a server-side
batch update selected by the query language:

```python
update_task(task_id, {"routes": ["sdxl", "sdxl-v2"]})
update_tasks(
    filter='status == "pending" and "sdxl" in routes',
    changes={"routes": ["sdxl", "sdxl-v2"]},
)
```

`routes` is always the complete replacement value. V2 does not expose route
add/remove/merge operators: their result depends on hidden prior state, whereas
full replacement makes the requested final contract explicit. Unspecified Task
fields remain unchanged. The initial batch-update use case is route migration;
this section does not authorize patching status, result, attempt or run ownership.

The update:

- competes atomically with claim;
- changes only tasks that are not running when the mutation executes;
- returns `409 task_running` for an ID-addressed update of a running Task;
- permits explicit updates to pending, succeeded, failed and cancelled Tasks;
- returns matched and updated counts;
- validates `routes` as a non-empty deduplicated set of exact strings; and
- is executed by the server rather than a client-side list-then-update loop.

Changing routes on a terminal Task has no immediate scheduling effect. This is
allowed because it is an explicit, local data change; the server does not impose
a paternalistic historical-immutability policy. It still does not make a
succeeded Task eligible for claim or otherwise change lifecycle state.

The successful claim records the route used for that run alongside `run_id`.

### 1.6 Removed v1 routing behavior

- Worker-side task filters no longer participate in claim.
- Query filters remain available for listing and explicit batch actions.
- Argument-shape matching no longer acts as implicit routing.
- No Route/Provider/Worker registry is introduced.
- Routes do not express CPU/GPU requests, capacity or resource reservation.

## 2. Argument handling

Status: **Decided**

### 2.1 Responsibility boundary

The server stores `args` as a JSON object but does not compare its keys with a
worker function or command. Once queue, state and route conditions match, argument
shape cannot make the task ineligible.

Argument binding belongs to the client-side worker adapter after claim.

All submit surfaces share JSON as the Task-argument data model. The Python API
accepts a JSON-serializable `dict`, HTTP accepts a JSON object, and CLI submit
accepts one strict JSON object through `--args`. Standard JSON decoding preserves
the corresponding Python primitive types; neither argparse nor the server
performs Worker-aware type inference.

The client uses this recursive type alias wherever public Python data must be
JSON-compatible:

```python
JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
```

The alias is narrowed by one uniform numeric contract at every Python, CLI and
HTTP boundary and recursively inside every JSON array/object:

- integers are in signed 64-bit range `[-9223372036854775808,
  9223372036854775807]`;
- floating-point values are finite IEEE-754 binary64 values;
- `NaN`, positive/negative infinity and a numeric literal that overflows to one
  of them are invalid; and
- Boolean is a distinct JSON type and is never accepted where integer/number is
  required.

The same domain applies to Task args, metadata and result, ordinary update data,
Worker result payloads, numeric Task fields such as priority/max attempts, and
filter literals. Python validation walks the object rather than relying on
`json.dumps` defaults; CLI/HTTP JSON decoding rejects nonstandard constants, and
canonical serialization uses `allow_nan=False`. An out-of-domain Task/request
value is a normal `422` schema validation error; an out-of-domain filter literal
is `422 invalid_filter`. Query equality continues to treat an in-range integer and
an exactly equal finite float as the same JSON number, as defined in section 10.

Every recursive JSON value stored in Task args, metadata or result has maximum
container depth 64. A scalar has depth 0; an array or object has depth one plus
the maximum depth of its values, with an empty container at depth 1. Object keys
do not add depth. The rule is applied identically to submit, ordinary update and
Worker completion, recursively and before persistence. Exceeding it returns
`422 json_too_deep` with `details.max_depth=64`; Python/CLI validation should fail
before sending when possible, but the Server remains authoritative. V2 has no
per-Queue or per-field depth setting.

Every JSON string and object key must consist of Unicode scalar values. Lone
UTF-16 surrogate code points such as `U+D800` through `U+DFFF` are rejected at
Python, CLI and HTTP boundaries even when written through a JSON `\uXXXX` escape.
They are not valid UTF-8 text and otherwise make canonical serialization,
database storage and logs disagree. This rule does not reject ordinary Unicode,
emoji, CJK text or control characters allowed by the containing field's own
contract. A violation uses that operation's ordinary schema-validation error;
V2 adds no Unicode-repair or replacement-character mode.

V2 removes v1's trailing `-- --key=value` submit shorthand and its
`ast.literal_eval` behavior. That syntax cannot distinguish values such as the
number `30` from the string `"30"` without guessing. Agents should generate the
unambiguous JSON object instead:

```text
labtasker task submit --args '{"prompt":"cat","steps":30,"enabled":true}'
```

### 2.2 Python binding

- `TaskArg()` values are validated by their Python annotations' Pydantic strict
  schemas; Labtasker performs no preparatory cast or fallback conversion of its
  own.
- A missing `TaskArg()` produces a client-side binding error.
- A missing `TaskArg(default=value)` uses that declared default as the input to
  the same resolver/validation pipeline as an explicitly submitted value.
- Extra task arguments do not produce a binding error.
- Extra task arguments are always ignored by named-parameter binding, including
  when the Worker function declares `**kwargs`. Such `**kwargs` receives only
  ordinary keyword arguments supplied when the Worker is started.
- `TaskArg(resolver=callable)` passes the raw JSON value to that callable and uses
  its return value; the return value is then checked by the same strict schema,
  without a second Labtasker conversion layer.
- Resolver and strict-validation failures are execution failures, not route
  mismatches.
- Invalid static Worker definitions, such as an unusable annotation or a
  non-callable resolver, fail before the first claim. A resolver failure caused by
  a particular Task value is an ordinary `TaskError` for that claimed attempt.

V2 removes the special `pass_args_dict` and `required_fields` loop options. Code
that genuinely needs the complete JSON object can read `task_info().args`; this
does not add a second binding mode or affect routing.

The client must not implicitly convert every missing argument to `None`. Workers
express optional values explicitly through Python defaults or dictionary access.
There is no `implicitly_set_undefined_arg_to_none` option.

### 2.3 Command binding

- V2 accepts exactly one command form:

  ```text
  labtasker loop [LABTASKER_OPTIONS] -- COMMAND [ARG...]
  ```

  Everything after the required `--` is one argv template. The Client executes
  the resolved argv directly without a shell and never joins or re-splits it.
- V2 removes `--command`/`--cmd`/`-c`, `--script-path`, command input from stdin,
  `--executable` and an implicit or explicit built-in shell mode. A script is an
  ordinary executable/argument (`python train.py`, `bash run.sh` or `./run.sh`).
  Workloads that deliberately need shell syntax may explicitly make a shell the
  command, such as `bash -lc '...'`; its quoting and interpolation risks then
  remain visible user choices rather than Labtasker behavior.
- Each argv template is compiled independently before the first claim into
  literal and path pieces by a small deterministic scanner. V2 ships neither
  ANTLR/generated parser artifacts nor an unused shadow grammar. The complete
  path grammar is:

  ```ebnf
  path       = segment ("." segment)*
  segment    = start continue*
  start      = "A"…"Z" | "a"…"z" | "_"
  continue   = start | "0"…"9"
  ```

  `%{optimizer.lr}` selects a Task arg through this object-only path. Segments
  are ASCII identifiers: a numeric segment is not an array index or an object
  key, and whitespace, hyphens, Unicode identifiers, wildcards, escapes and
  literal dots in keys are unsupported. Arbitrary JSON keys remain available to
  Python Workers through `task_info().args`.
- `%{{` emits the literal two characters `%{`. It is deliberately checked before
  the `%{` placeholder opener, so ordinary percent characters are never globally
  rewritten:

  ```text
  %{a}       value selected by path a
  %{{a}      literal %{a}
  %%{a}      literal % followed by the value of a
  %%%{a}     literal %% followed by the value of a
  ```

  A lone `%`, `%%` and a stray `}` are literal text. V2 accepts no v1 `%()`
  compatibility form.
- A selected JSON string is inserted exactly. Every other JSON value is inserted
  as deterministic compact JSON: numbers as JSON numbers, booleans as `true` or
  `false`, null as `null`, and arrays/objects as compact JSON with sorted object
  keys and UTF-8 characters preserved. A placeholder may occupy all or part of an
  argv element, and multiple placeholders may be concatenated in that element.
  The resolved element always remains exactly one argv element.
- Empty strings remain empty argv elements. A resolved element containing NUL is
  a binding error because operating-system argv cannot represent it.
- A missing value referenced by a command placeholder is a client-side binding
  error and the subprocess is not started.
- Task arguments not referenced by the command template are ignored.
- The server does not parse command templates.

The scanner contract is total and fail-fast:

| State and next input | Action |
|---|---|
| text + `%{{` | emit literal `%{`; advance three code points |
| text + `%{` | record the opening position and enter path parsing; advance two code points |
| text + any other Unicode code point | emit it literally; advance one code point |
| text + end of input | finish successfully |
| path + valid segment/path input ending in `}` | emit one path piece and return to text |
| path + end of input | report an unterminated placeholder at its opening position |
| path + invalid input | report a syntax error at that input position |

The path parser rejects an empty path, leading/trailing/repeated dots and every
character outside the grammar above. Adjacent placeholders are valid. Static
syntax errors include the 1-based argv-element number and Unicode-code-point
column and abort Worker startup before any Task is claimed. A missing key, a
non-object intermediate value or a NUL introduced during resolution depends on a
claimed Task; it is therefore a `TaskError`, and the child is not started. A NUL
already present in literal template text is a startup error. An empty command is
a startup usage error, while an argv element that resolves to the empty string is
valid.

The scanner is the normative implementation of this intentionally regular,
nonrecursive language. Its module documentation repeats the EBNF and transition
table; an unused `.g4` file is not retained as a second source of truth. Required
conformance tests cover all examples above, empty/unterminated/invalid paths,
adjacent placeholders, exact diagnostic locations, generated valid templates and
arbitrary Unicode fuzz input. Tests must establish termination, linear-time
progress and that every scanner iteration advances the input. A parser generator
is reconsidered only if a future design explicitly adds features such as nesting,
quoted key segments, operators or error recovery.

For example:

```bash
labtasker loop --route sdxl -- \
  python train.py --prompt '%{prompt}' --config '%{config}'
```

For Task args `{"prompt":"hello world","config":{"lr":0.001}}`, the final
arguments include the single elements `hello world` and `{"lr":0.001}`. Quotes
used to group the templates in the invoking shell are not part of those values.

The command child inherits the parent Worker's environment, after which
Labtasker overwrites its reserved `LABTASKER_*` execution-context variables; it
also removes a pre-existing `LABTASKER_TOKEN` when Server authentication is
disabled. V2 adds no `--env` mini-language. Static environment variables may be
set on the Worker process itself. A platform environment launcher or wrapper can
express a per-Task value without special Labtasker behavior; for example, on
POSIX:

```bash
labtasker loop -- env 'LR=%{lr}' python train.py
```

Here `env` is the standard POSIX command: after Labtasker resolves the template,
it starts `python train.py` with `LR` set to that value. Labtasker does not add
its own environment syntax or pretend that `env` is anything other than an
external POSIX program.

Command output follows the terminal context automatically and exposes no public
PTY option:

- On POSIX, when Labtasker's own stdin, stdout and stderr are attached to an
  interactive terminal, the Client runs the child through an internal PTY. It
  relays input, output and terminal sizing so buffering, progress displays,
  colors and prompts resemble direct execution.
- Otherwise, including redirected output, pipelines and schedulers, the Client
  uses ordinary subprocess pipes. It drains stdout and stderr
  concurrently and forwards bytes as soon as they arrive, while preserving the
  two streams, and gives the child a null stdin. It cannot force a child that
  detects a pipe to flush its own userspace buffers.
- Both paths forward output live and copy it into the current run's `run.log`.
  PTY output has the same combined stdout/stderr semantics as an ordinary
  terminal; pipe mode preserves their separate terminal destinations even though
  the local run log contains both. Output is relayed and appended as raw bytes;
  Labtasker performs no text decoding, newline normalization or ANSI removal, so
  `run.log` is not guaranteed to be valid UTF-8.

V2 therefore has no `--pty`, `--no-pty` or `--use-pty` option. It does not add a
ConPTY implementation or admit Windows into the Command Worker and then silently
fall back to pipes. On supported POSIX platforms, terminal detection affects
presentation and buffering only; it never changes argv interpolation, Task state
or routing. V2 provides no noninteractive Task-input protocol: a parallel command
Worker that needs data must receive it through Task args, files or another
explicit program-level mechanism rather than consuming the Worker's stdin.

### 2.4 Failure reporting boundary

A binding, resolver or conversion error happens after a successful claim and is
reported through the same ordinary `TaskError` path as user-code failure. It
consumes the normal failure budget, and the Worker continues unless that failure
makes the Task terminal. It is not an argument-matching or routing decision.

### 2.5 Removed v1 argument behavior

The v1 server-side "No More, No Less" rule and `required_fields` claim filtering
are removed. Explicit routes own execution eligibility. Workers remain responsible
for consuming task arguments correctly; ignored arguments are not treated as a
server error.

The v1 `pass_args_dict` injection branch and public `required_fields` option are
also removed rather than retained as client-only compatibility modes.

## 3. Failure handling and retry

Status: **Decided**

### 3.1 v1 behavior being reconsidered

On a task exception, v1 may show two timed interactive prompts:

1. report the attempt as failed, or ignore it and reset the task to pending with
   retries reset to zero; and
2. continue the worker loop, or exit it.

The value is not the terminal UI itself but the distinct recovery outcomes it
exposes. V2 retains those outcomes without placing either a human or an agent in
the worker's runtime loop.

### 3.2 Decided default

- An ordinary task exception is reported to the server as a task failure.
- The server applies the task's retry policy.
- The worker continues claiming subsequent tasks by default.
- A single task failure does not terminate the worker by default.
- There is no default human prompt.

This default preserves unattended throughput and matches the effective v1 default
after its prompts time out.

### 3.3 Client-side error levels

The three levels are a client abstraction, not server or Task domain states. The
server receives only ordinary Task commands: return the current Task to pending
without charging its retry budget, or report a failure through the existing retry
policy. It does not store a client error level or manage Worker lifecycle.

The internal outcome names are `transient`, `fail` and `abort`. `release` is not
used as the client error-level name.

| Client level | Server-facing Task action | Client process action |
|---|---|---|
| `transient` | Return the Task to pending without charging the current incident to its retry budget | Continue the Worker loop |
| `fail` | Report an ordinary failure; the server consumes one retry-budget unit and applies normal pending/failed policy | Continue the Worker loop |
| `abort` | Report exactly the same ordinary failure as `fail` | Exit the Worker process; the Labtasker client does not restart it |

An ordinary user-function exception maps to `fail`. `transient` represents a
recoverable client/worker-side incident that should not be charged to the Task.
`abort` represents a non-recoverable Worker-side failure for which continuing the
process is unsafe. `fail` and `abort` are deliberately indistinguishable to the
server and to the Task; only the local Client action differs.

These mappings apply only while the Client still owns an unresolved running run.
After that run has completed, been revoked or otherwise finalized, an exception
may still control the local Worker process but cannot emit another Task action.
In particular, `FatalWorkerError` after a successful `finish()` exits the Python
Worker without sending `fail` or changing the succeeded Task.

The client selects a level locally from an explicit exception/error type or a
preconfigured deterministic rule. It emits the classification and context through
ordinary logging, but it never waits for an agent response. A transient run may
still be logged for observability even though it does not consume retry budget.

`transient` affects only the current incident. It preserves any retry budget
already consumed by earlier real failures; unlike v1's "ignore" branch, it never
resets the historical counter to zero.

### 3.4 Python exception contract

All three client levels have public exception types so user code can select an
outcome with `raise`. The public names are:

```python
labtasker.TransientError
labtasker.TaskError
labtasker.FatalWorkerError
```

The loop wrapper catches these exceptions and performs the corresponding
server-facing Task action and local Worker action.

- Raising `TransientError` selects `transient`.
- Raising `TaskError` selects `fail`.
- Raising `FatalWorkerError` selects `abort`.
- Any other ordinary user exception has the same behavior as the explicit
  `TaskError` path.

These exception classes belong to the Python client API. They are not serialized
as HTTP domain types and do not add states or error levels to the server. The
existing private `_LabtaskerJobFailed` mechanism should be replaced by the public
`TaskError` contract where their behavior overlaps. No additional public policy
enum or callback is introduced.

### 3.5 Command-process contract

Command workers use only the conventional subprocess contract:

```text
exit code 0     -> success
any other code or signal termination -> the same behavior as TaskError
```

There are no reserved numeric exit codes for `TransientError` or
`FatalWorkerError`, and the client does not inspect stdout/stderr text to infer an
error level. Those outcomes are available to Python workers or selected internally
by the client. This keeps command execution portable and avoids a second hidden
failure protocol. If the command child already completed through `finish()`, its
later exit code or signal is only a local diagnostic and cannot rewrite the
already succeeded Task.

### 3.6 Keyboard interruption

`KeyboardInterrupt` is handled as an explicit Worker stop request rather than an
ordinary Task error. If a Task is currently running, the client makes a best-effort
request to return it to pending without charging the current incident to its retry
budget, then re-raises the original interruption. If that request cannot reach
the server, the interruption still propagates and timeout recovery remains the
fallback. A CLI Worker therefore retains the conventional exit status 130.

This lifecycle path is not a fourth public error-level exception.

### 3.7 Process termination and heartbeat recovery

Every claimed run has a heartbeat. The server uses heartbeat loss as the single
mechanism for recovering a Task whose client disappears:

- v2 has no supported no-heartbeat execution mode;
- `SystemExit` and SIGTERM have no custom Task-reporting protocol; the process
  exits and heartbeat recovery handles any still-running Task;
- heartbeat expiry is reported internally as an ordinary failed execution and
  consumes the same failure budget as `TaskError`; and
- a stale client remains fenced by `run_id` and cannot later finish or fail a
  reassigned run.

The separate task-execution timeout is deleted. V2 does not carry forward
`task_timeout`, `eta_max`, `start_heartbeat=False`, or equivalent configuration
and code paths. Labtasker detects disappearance, not whether a healthy long-running
experiment has taken "too long". Users that need a wall-clock deadline implement
it in their execution program or an external process supervisor.

### 3.8 Attempt naming

The v1 public names `retries` and `max_retries` are replaced by `attempt` and
`max_attempts`.

- A newly submitted or manually requeued Task has `attempt = 0`.
- Claim atomically increments `attempt` before returning the Task, so the first
  real execution observes `attempt = 1`.
- `max_attempts` is the total number of charged executions, including the first;
  it is a positive integer and defaults to `3`.
- A Task is claimable only while `attempt < max_attempts`.
- `TaskError`, `FatalWorkerError` and heartbeat loss keep the incremented value.
  If it is below `max_attempts`, the Task returns to pending; if it equals
  `max_attempts`, the Task becomes failed.
- `TransientError` atomically returns the Task to pending and rolls back only the
  current claim's increment. The next claim may therefore reuse that attempt
  number. Previously charged attempts remain unchanged.
- A manual requeue always resets `attempt` to `0`. There is no
  `reset_attempts` flag or alternate preserve-budget mode.

Every execution still has a unique `run_id`; reusing an attempt number after a
transient incident does not reuse execution ownership or allow stale reporting.

### 3.9 Retry ordering

A charged failure that remains retryable, and an uncharged `TransientError`,
re-enter the end of the pending Tasks at their priority. A transient return rolls
back the current attempt increment but does not preserve the Task's former queue
position: already-waiting equal-priority work runs first. If no other eligible
Task exists, the returned Task may be claimed again immediately.

V2 exposes no retry delay, exponential backoff or retry-policy abstraction. The
Server stores one private `pending_at_us` timestamp on each Task. Submission and
every transition into or explicit requeue within pending set it to the current
Server time; claim and every transition to a non-pending state clear it. Ordinary
Task updates do not change it. Eligibility is ordered by `priority DESC`, then
`pending_at_us ASC`, then `task_id ASC`. The final ID tie-break makes equal
microsecond timestamps deterministic without adding a Queue counter or public
scheduling concept.

## 4. Task lifecycle

Status: **Decided**

### 4.1 Empty-queue grace wait

Status: **Decided**

A Worker does not exit on the first claim response with no eligible pending Task.
It enters a bounded idle grace period and retries claim, allowing a briefly fixed,
retried or newly submitted Task to use the already-started process.

This remains client-side polling. It does not create an idle Worker record,
heartbeat an idle process, or add server long-poll/SSE behavior. The grace timer
starts with the first empty claim response, resets after any successful claim, and
ends in a normal process exit if no Task appears before the deadline. Poll cadence
is an internal constant rather than another public tuning option.

The public `idle_timeout` is a non-negative duration in seconds and defaults to
`300` (five minutes). `idle_timeout=0` preserves immediate exit. There is no
special infinite-wait value or separate daemon mode.
The Python value must be a finite `int` or `float`; booleans, NaN, infinities and
negative values are rejected before the first claim. `None` is not accepted.

### 4.2 States and explicit lifecycle actions

The Task states are exactly:

```text
pending | running | succeeded | failed | cancelled
```

V2 uses `succeeded`, replacing v1's `success` string.

`cancel` accepts pending and running Tasks. Cancelling a pending Task prevents
future claim. Cancelling a running Task atomically sets it to cancelled,
invalidates its current `run_id` and records `finished_at`, so later heartbeat,
success or failure reports from that execution are rejected. Cancellation does
not change `attempt`, `last_error` or `result`; pending cancellation leaves the
latest-run summary unchanged. Repeating cancel on an already cancelled Task is
an idempotent success. Succeeded and failed Tasks reject cancel.

`requeue` accepts pending, failed and cancelled Tasks. It returns or keeps the
Task pending, resets `attempt` to zero, clears `last_error`, and refreshes
`pending_at_us`. It preserves `args`, `metadata`, `routes`, `priority`,
`max_attempts`, `result` and the latest-run summary. Pending-to-pending requeue is
useful for explicitly forgiving already charged failures while a Task is waiting
for another attempt; even an attempt-zero Task is deliberately moved to the end
of its priority group. Running Tasks reject requeue. A succeeded experiment is
rerun by submitting a new Task rather than rewriting the successful record.

Invalid lifecycle actions return an explicit conflict rather than silently acting
as no-ops or force-setting state.

Execution actions obey one stable FSM guard: only a `running` Task with the
matching `active_run_id` may accept `complete`, `fail` or `unclaim`. Once complete
has changed it to `succeeded`, no later exception, heartbeat, exit status or
client-side error classification can move that same Task to failed or pending.
Repeating the same terminal action may be deduplicated, but never replays its
state transition; a contradictory action is rejected. Explicit non-running Task
updates may still change user-owned data under section 11, not lifecycle state.

The public lifecycle operations return the resulting Task:

```text
cancel_task(task_id: str, *, queue: str | None = None) -> Task
requeue_task(task_id: str, *, queue: str | None = None) -> Task
```

```http
POST /api/v2/queues/{queue}/tasks/{task_id}/cancel
POST /api/v2/queues/{queue}/tasks/{task_id}/requeue
```

Both successful HTTP actions return `200 OK` with the Task, and their CLI forms
write that same Task as formatted JSON. Requeue is not idempotent: every accepted
call refreshes `pending_at_us` and `updated_at`, so the Client does not
automatically retry a lost response.

Task deletion is allowed in every state except running. A running Task must first
be cancelled so its run is fenced explicitly. Deletion is idempotent, including
when the Task is already absent:

```text
delete_task(task_id: str, *, queue: str | None = None) -> None
```

```http
DELETE /api/v2/queues/{queue}/tasks/{task_id}
204 No Content
```

The CLI emits no stdout on successful deletion and uses exit code zero. It does
not invent a deletion-receipt object when the public operation has no return
value.

Hard deletion also removes the Task's private `creation_hash`; v2 retains no
tombstone or permanent used-ID registry. The same explicit Task ID may therefore
be used to create a new Task after deletion. Such a Task is a new resource, not
an idempotent replay of the deleted one. A very late create request can likewise
recreate a deleted ID; avoiding that corner case would require permanent state
whose cost is not justified for the initial small-scale trust-domain workload.
Generated IDs make accidental reuse negligible, while deliberate explicit reuse
remains the caller's responsibility.

### 4.3 Failure diagnostics

V2 does not introduce a persistent run/attempt-history table in the first release.
A Task instead has an optional structured `last_error`, separate from experiment
output:

- each charged `TaskError`, `FatalWorkerError` or heartbeat-loss failure replaces
  `last_error`;
- `TransientError` and cancellation do not replace it;
- manual requeue clears it; and
- a later successful retry retains it as the latest recovered failure.

The fixed wire shape is:

```text
last_error: null | {
  type: str
  message: str
  traceback: str | null
  occurred_at: datetime
  attempt: int
  run_id: str
}
```

The client represents the non-null shape as the frozen public Pydantic model
`LastError`; consequently `Task.last_error` and `TaskInfo.last_error` have type
`LastError | None`. This name is intentionally distinct from the public
`TaskError` exception raised by Worker code.

Before the official Client reports `fail`, it serializes the diagnostic body. If
that body would exceed the global 1 MiB request limit, it does not let terminal
reporting fail and later masquerade as heartbeat loss. It instead reports this
bounded fallback while preserving the original exception class name:

```json
{
  "type": "OriginalExceptionType",
  "message": "Failure diagnostics exceeded the 1 MiB limit; see local run.log.",
  "traceback": null
}
```

The full exception and traceback are still emitted through the ordinary local
Worker logging path and therefore into `run.log` when that journal is available.
The journaled `error.json` is the exact compact payload actually sent. V2 does
not add configurable diagnostic limits or a partial string-truncation algorithm.
An independent executor that directly implements HTTP must likewise send a body
within the documented request limit.

Heartbeat loss has `traceback = null`. Exception details are never written into
experiment result data.

Heartbeat expiry uses the stable diagnostic values
`type="HeartbeatTimeout"`, `message="Heartbeat lease expired."` and
`traceback=null`. Its `occurred_at` and the Task's `finished_at` use the same
Server timestamp at which expiry recovery commits; this is detection/transition
time, not a claim about the exact instant the Worker process died.

### 4.4 Result

V1's `summary` is replaced by `result`. It is always a JSON object and defaults to
`{}`. The Task status, rather than nullability, says whether execution has
completed.

Returning a value from a decorated Python function has no Labtasker protocol
meaning. A normal return completes the Task as succeeded and replaces `result`
with `{}`. It never implicitly inherits result data from an earlier state or
attempt. Code that has obtained its intended result may call
`finish(result={...})` explicitly; this immediately and reliably completes the
owned run rather than staging data until the function returns. `finish()` without
an argument stores `{}`. Completion atomically stores the final result and state.
When no run is active, ordinary Task update may also replace the complete
`result` object; this supports explicit correction of stored user data without
changing status. The 2.0.0 initial release has no incremental result/metric merge API.

## 5. Queue, project and authentication boundary

Status: **Decided**

### 5.1 Queue is the only namespace

V2 keeps Queue and does not introduce a persistent Project entity. A Queue is both
the Task namespace and the unified scheduling pool described by the routing
contract. A repository or client configuration may call itself a project, but
that local organizational term has no server lifecycle or API.

Queues are created explicitly. Submitting to an unknown name returns not-found;
submit never creates a Queue as a side effect. A fresh server database creates one
Queue named `default`, and clients use `default` when no queue name is configured.
Deleting that Queue does not cause later submissions or server restarts to recreate
it silently.

### 5.2 Queue representation and operations

A Queue has exactly one public field:

```json
{"name": "default"}
```

The 2.0.0 initial release adds no Queue description, metadata, timestamp, embedded
Task count or other derived statistics. The separate Task count operation does
not change the Queue representation. Queue creation and listing are sufficient for discovery; because an
individual Queue has no additional representation to retrieve, v2 deliberately
has no `get_queue()` function, item `GET` endpoint or `queue get` command.

The complete public operations are:

```text
create_queue(name: str) -> Queue
list_queues() -> list[Queue]
delete_queue(name: str, *, cascade: bool = False) -> None
```

```http
PUT    /api/v2/queues/{queue}
GET    /api/v2/queues
DELETE /api/v2/queues/{queue}?cascade=false
```

Create returns the Queue object with `201 Created`, or the same object with `200
OK` when it already exists. List returns an ordinary JSON array with `200 OK`; it
is not paginated. Delete returns `204 No Content`. The matching CLI is:

```text
labtasker queue create NAME
labtasker queue list
labtasker queue delete NAME [--cascade]
```

Create writes one formatted Queue object, list writes the formatted JSON array,
and successful delete writes no stdout.

### 5.3 Queue deletion

The 2.0.0 initial release provides atomic hard deletion rather than making Queue creation permanent:

- an empty Queue may be deleted directly;
- deleting a non-empty Queue requires an explicit `cascade` request;
- deletion is rejected while any Task in the Queue is running, including with
  `cascade`; callers first cancel those Tasks;
- a successful cascade deletes the Queue and all of its Tasks in one transaction;
- there is no archive, trash or soft-delete state; and
- the non-interactive CLI requires `--cascade` for the destructive form and does
  not add a confirmation prompt.

A concurrent claim and Queue deletion are serialized by the database transaction.
If claim wins, deletion sees a running Task and conflicts; if deletion wins, no
Task remains available to claim.

### 5.4 Authentication

One server deployment is one trust domain. V2 uses at most one server-wide Bearer
token; possession grants access to every Queue and administrative Queue actions.
There are no Queue passwords, per-Queue tokens, users, roles or token-management
endpoints.

An explicitly operated HTTP Server binds to `127.0.0.1` by default and may run
without a token only when bound exclusively to a loopback address. It refuses to
start on any non-loopback bind without a configured token. The token comes only
from the Server environment variable defined below. Rotation means changing that
value and restarting the Server; v2 has no token CRUD or live-rotation protocol.

The automatic local Server instead accepts HTTP over one owner-only Unix-domain
socket and always runs without application-level authentication. Its socket
directory and socket permissions supply the local same-user boundary; it does not
listen on a TCP port or inherit `LABTASKER_SERVER_TOKEN`. This is not a multi-user
sharing mechanism. Users who need another Unix user or host to connect run an
explicit HTTP Server and configure its URL and, when required, token.

For this startup rule, a host is accepted as tokenless only when it is an IP
literal for which Python `ipaddress.ip_address(host).is_loopback` is true
(`127.0.0.0/8` or `::1` in ordinary use), or the hostname is ASCII-case-
insensitively exactly `localhost`. `0.0.0.0`, `::` and every other hostname
require a token even if local DNS currently resolves them to loopback. This keeps
the exception small while preserving the conventional `--host localhost` form.

When Server authentication is disabled, an incoming `Authorization` header is
ignored; a Client token inherited through configuration therefore does not make a
tokenless loopback Server reject an otherwise valid request. When authentication
is enabled, every `/api/v2` request must contain exactly a Bearer token matching
the configured value. A missing, malformed or wrong credential returns the same
`401` error envelope with `code="unauthorized"`, empty details and a standard
`WWW-Authenticate: Bearer` response header. The response never distinguishes why
authentication failed or echoes credential data. `/health` and `/openapi.json`
remain unauthenticated as already specified.

### 5.5 Server transports and process ownership

#### 5.5.1 Explicit HTTP Server

The complete foreground HTTP Server command is:

```text
labtasker-server serve \
  --host 127.0.0.1 \
  --port 8000 \
  --database .labtasker/server.db
```

Those displayed values are the defaults. This command always means an explicitly
operated TCP Server: it runs in the foreground, never daemonizes and never writes
local-daemon PID or socket metadata. A Client with an explicit constructor,
environment or config-file URL uses it as ordinary HTTP and does not start,
restart, stop or otherwise supervise it. The user or an external supervisor owns
that process for its complete lifetime.

`--database` accepts a filesystem path, not a general database URL; a relative
path is resolved against the Server's startup working directory, and the parent
directory is created when absent. When the resolved database path is inside a
directory named exactly `.labtasker`, the Server ensures that directory contains
`.gitignore` with `*` and `!.gitignore` rules. It uses exclusive creation and
leaves any existing `.gitignore` unchanged; custom database parents outside
`.labtasker` receive no version-control files. V2 does not expose `--workers`,
`--reload` or log-level configuration.

The optional credential is read only from `LABTASKER_SERVER_TOKEN`. There is no
`--token` flag or Server config file, avoiding routine disclosure through process
arguments. An unset variable means authentication is disabled; a present empty
value is invalid rather than a second spelling for unset. The existing security
rule remains authoritative: every address represented by a tokenless bind must be
loopback, otherwise startup fails before listening.

#### 5.5.2 Default local endpoint

When no Client URL is configured, v2 uses local mode. Local mode is bound exactly
to the Client's current working directory when that Client is constructed. It
does not search parents, inspect a VCS root, reuse another directory's
`.labtasker`, or introduce a Server-side Project resource. The Client converts
the current directory to its canonical absolute real path once and snapshots it
with the rest of the Client configuration. A later `chdir()` does not retarget an
existing Client.

For local directory `/absolute/work`, the durable state is:

```text
/absolute/work/.labtasker/
  .gitignore
  server.db
  server.log
  runs/...
```

The database and log survive daemon restart and SSH disconnection. Every Server
process, including explicit HTTP `serve`, holds an exclusive non-blocking
advisory ownership lock on an open file descriptor for the actual database file,
not on an adjacent sidecar path. This one ownership lock is also local startup
election: v2 has no separate startup lock. The ownership primitive must be
independent of SQLite's own byte-range transaction locks and preserve the lock on
an explicitly inherited descriptor across the POSIX child launch.

For an automatic local start, the startup coordinator opens or creates `server.db`,
locks that descriptor before launching the daemon and passes the already locked
descriptor to it. The daemon verifies that the descriptor and canonical database
path identify the same device and inode, then retains the descriptor for its
entire lifetime while SQLite opens the database normally by path. An explicit
HTTP `serve` process performs the same open, identity check and lock itself.
Failure to obtain the lock aborts before SQLite schema inspection or migration;
normal process exit and abnormal process death both release it through the
kernel. Labtasker never unlinks or atomically replaces a database file while it
is owned. External removal or replacement of a live database is unsupported.
This turns the rule “one Server process owns one SQLite file” into an enforced
cooperating-process invariant by tying ownership to the actual database inode
rather than a separate pathname. A SQLite database on a filesystem whose
advisory locking semantics cannot uphold that invariant is unsupported.

Local discovery uses a short tmux-style per-user runtime directory rather than a
socket below an arbitrarily deep working directory:

```text
/tmp/labtasker-{effective-uid}/
  {sha256-of-canonical-directory}.sock
  {sha256-of-canonical-directory}.json
```

The directory is created with mode `0700`, must be owned by the effective user and
must not be a symlink. The socket is created owner-only. An ownership, type or
permission mismatch is a startup error rather than something the Client repairs.
The full lowercase hexadecimal SHA-256 digest keeps independent CWDs separate
while keeping the Unix socket path below ordinary platform limits. Runtime files
may disappear at reboot and are not durable state; the database never resides in
`/tmp`.

The JSON entry is best-effort runtime metadata, not a lock, durable database or
public resource. It records a random generation, owner role, PID, operating-system
process start marker, database device/inode, automatic-attempt time and Server
version. A short-lived Server-package coordinator writes its identity before launch and
atomically replaces that entry with the spawned daemon's identity immediately
after process creation. Writers use a same-directory temporary file and atomic
replace. Missing, malformed or mismatched metadata never permits breaking a held
database lock or signalling a process; it only reduces diagnosis to an unknown
owner. Because the metadata is ephemeral, reboot naturally clears any old
automatic-start throttle. The local endpoint is single-host; concurrent local
mode against one shared CWD from multiple hosts is unsupported.

The local Client speaks the same HTTP `/api/v2` protocol through an httpx
Unix-domain-socket transport. The nominal HTTP authority used internally has no
discovery, authentication or TCP meaning. OpenAPI, request bodies, response
models, errors and `run_id` fencing are identical across Unix-socket and explicit
HTTP transports.

#### 5.5.3 Local daemon startup and recovery

Importing `labtasker`, constructing `Client`, displaying help and running
`labtasker config show` do not start or connect to a Server. The first real local
Task or Queue request, including a Worker's startup claim path, ensures that the
local Server is available. Later local requests perform the same ensure step when
opening the Unix socket reports that no listener exists. This automatic behavior
applies only to local Unix-socket mode. An explicitly configured HTTP URL is
never health-preflighted for process management and a connection failure never
starts, restarts or stops any Server.

After a local health failure, the Client runs the installed Server module from
the same Python environment through the hidden internal `_ensure-daemon` entry,
passing the canonical directory without a shell. That short-lived process owns
the complete startup decision; the Client package never opens or locks the
database, reads or writes daemon metadata, launches the daemon, or handles the
ownership descriptor. Absence of `labtasker-server` fails visibly before local
state is created and tells the user to install the complete `labtasker` package
or configure an explicit URL.

Each concurrent Server-package coordinator non-blockingly attempts the database
ownership lock. Exactly one succeeds. The winner rechecks `/health`, validates
the existing runtime metadata for throttling, and may remove only stale runtime
artifacts of the expected type and owner. Every loser knows that some live
process still owns the database and never starts or kills a second one merely
because health is unavailable. `labtasker-server start` calls this same internal
coordinator function with only the automatic throttle bypassed; it does not
implement a second launch path.

There is one bounded publication allowance, not another lifecycle state: after
losing the database lock, a coordinator may spend at most one second re-reading health
and runtime metadata so it does not misclassify the ordinary window between the
winner acquiring the lock and publishing coordinator metadata. Once matching
fresh metadata appears, the normal 30-second startup deadline applies. If the
allowance expires without that evidence, the owner is `unhealthy`; the coordinator
does not keep waiting, retry the lock or infer permission to recover it.

While valid runtime metadata remains, automatic launch is limited to one attempt
per canonical CWD in any 10-second interval. The coordinator derives that fixed
throttle from the metadata's automatic-attempt time. If time remains, it closes
its database descriptor, visibly reports the remaining seconds and log path, and
returns a failed machine result with `state="backoff"` and
`retry_after_seconds`; it does not sleep or create a process. The Client maps
that result to `TransportError`. `labtasker-server start` bypasses only this time
gate.
Missing, malformed, future-skewed or mismatched metadata is visibly ignored for
throttling, so it cannot permanently disable startup. There is no failure count,
exponential sequence, probation/stability state or delayed reset task. This
throttle never changes ordinary HTTP-request retry eligibility or makes an
uncertain mutation replayable.

To launch, the coordinator creates a random generation and atomically records its
identity, the database identity and attempt time in runtime metadata, then starts
the installed Server from the same environment as a detached POSIX daemon. The
daemon has no controlling terminal, reads stdin from the null device and appends
stdout/stderr to the absolute `server.log` path. The already locked database
descriptor is explicitly inherited across process creation and exec. Immediately
after a successful spawn, the coordinator atomically replaces the metadata with
the daemon PID, process start marker and same generation, closes its own database
descriptor copy and no longer owns any coordination primitive. As its first
bootstrap action, the daemon independently validates the inherited descriptor and
atomically publishes the same-generation daemon identity; this completes runtime
metadata even if the launching coordinator exits immediately after process creation.
The daemon retains its inherited descriptor until process exit and confirms that
it still denotes the configured database device/inode before SQLite schema work.
Process creation failure leaves only stale metadata and closes the coordinator's
descriptor, so the kernel makes the next post-throttle attempt possible.

The coordinator waits for readiness only by polling `/health` through the
expected Unix socket; v2 adds no private readiness pipe. It waits at most 30
seconds from the recorded attempt time and never holds a separately acquired
coordination lock while waiting; database ownership has already transferred to
the daemon descriptor. It writes one internal JSON result to captured stdout and
keeps launch/wait diagnostics visible on inherited stderr. Success means health
has passed. The Client parses that result, performs one final socket-health
verification, and continues the original request; it does not duplicate the
readiness loop or interpret runtime metadata. A failed or timed-out result maps
to `TransportError` with the observed state and log path and does not terminate a
process or migration. If the daemon really exits, its database descriptor closes
and a later coordinator may win ownership after the fixed throttle. If it
remains alive but hung, the database stays locked, preventing a duplicate Server,
and recovery requires verified explicit stop or external process administration.

The local state detector has these meanings:

| State | Evidence | Automatic action |
|---|---|---|
| `running` | `/health` succeeds through the expected socket | Use it. |
| `starting` | Health fails, the database lock is held and matching verified local metadata is less than 30 seconds old | Poll health only until the 30-second deadline. |
| `unhealthy` | Health fails while the database lock is held without matching fresh local startup metadata | Report; never start or automatically kill the owner. |
| `backoff` | Health fails, the database lock is free and a valid automatic attempt occurred less than 10 seconds ago | Report the remaining delay; do not wait or start. |
| `stale` | Health fails, the database lock is free and owned socket/metadata remains | Safely remove those artifacts and start when the fixed throttle permits. |
| `stopped` | Health fails, the database lock is free and no socket/metadata remains | Start a daemon when the fixed throttle permits. |

The Client ensures availability before initially sending an operation. A later
connect failure that proves no HTTP bytes reached a local Server may start a new
daemon and send that operation once. Once a request may have reached the Server,
any failure retains the operation's existing retry and uncertain-outcome rules:
automatic daemon recovery does not make an update retryable or replay a mutation
whose commit is unknown. Existing idempotent submit, claim, heartbeat and terminal
report logic may reuse the recovered transport under their already specified
rules. In particular, a Worker's heartbeat/report loop can recover from a local
daemon crash without weakening `run_id` fencing.

The daemon has no idle shutdown. It remains alive across terminal detach and SSH
disconnect until explicit stop, process failure or machine shutdown. Host service
or cgroup policy may still kill it; this is ordinary process failure, and the next
local operation starts a replacement when the fixed launch throttle permits.
Unlike tmux, Labtasker has no session or registered idle Worker whose absence
could define a safe `exit-empty` condition.

Because database ownership is the only lock and every acquisition attempt is
non-blocking, the local protocol has no two-lock ordering or circular wait. A
coordinator frozen after obtaining the database lock remains an unavailable live
owner; v2 reports it and does not invent a lease, break the lock or automatically
kill an identity it cannot verify. This rare case may require the user to
terminate the recorded coordinator through ordinary operating-system tools.

#### 5.5.4 Local daemon commands

The Server executable exposes CWD-addressed local management alongside foreground
`serve`:

```text
labtasker-server start
labtasker-server status
labtasker-server stop [--force]
labtasker-server logs
labtasker-server serve [--host HOST] [--port PORT] [--database PATH]
```

`start` runs the same idempotent startup coordinator as an automatic Client start;
an already running daemon is a visible successful no-op, and explicit `start`
bypasses only the fixed launch throttle rather than database ownership or identity
checks. `stop` acts only on the current CWD's verified local daemon, sends
graceful termination and waits up to 30 seconds for its socket and database lock
to be released. Without `--force` it never sends SIGKILL; an unresponsive
verified daemon is a visible failure. With `--force`, failure to stop during that
grace period causes the command to reverify the same PID, process start marker,
generation and database identity immediately before sending SIGKILL, then wait up
to 5 more seconds for kernel cleanup. Failure to reverify or observe cleanup is
reported and never redirects the signal to another process.

An already stopped daemon is a visible successful no-op, and verified stale
socket/metadata may be removed. `stop` is a one-shot action, not a persistent
disable switch: it writes no `disabled` marker, and a later local operation may
automatically start a new daemon. After observing the verified generation exit,
it removes that generation's socket and runtime metadata, so an intentional stop
does not leave the fixed automatic-launch throttle active. `stop` never targets a
configured URL, an explicit foreground HTTP Server or an unverified database
owner. PID metadata is diagnostic rather than authoritative: before signalling,
the command verifies the recorded process identity, start marker, generation,
socket and database identity so a reused PID cannot target an unrelated process.
Successful `start` and `stop` write no stdout and always describe what they did on
stderr.

`status` never starts, stops, repairs or deletes anything. It writes one
two-space-indented JSON object to stdout with stable keys `state`, `directory`,
`database`, `socket`, `log`, `pid`, `version` and `retry_after_seconds`;
unavailable values are null, the retry delay is non-null only for `backoff`, and
`state` is one of the six values in the table above. `logs` never follows or
pages: it writes the current UTF-8 `server.log` contents to stdout and exits. A
missing log is an empty successful result. Server logs are diagnostic rather than
a durable audit contract and may be rotated internally.

### 5.6 Schema initialization and migration

The Server uses Alembic revisions from the first v2 schema. On startup, before
opening the listening socket, it:

1. initializes a new empty database at the current revision and creates the
   `default` Queue;
2. automatically applies every known forward revision to an older v2 database;
3. refuses to start if the database revision is newer than the running binary or
   unknown; and
4. refuses to serve when a migration fails.

V2 exposes no `db upgrade`, downgrade or schema-repair command and creates no
automatic backup. Operators copy the SQLite file before an important upgrade when
they need rollback. Migration tests must cover fresh initialization, every
supported forward upgrade fixture, failure behavior and rejection of a newer
revision. These migrations concern v2 SQLite databases only; v1 MongoDB import is
not an implicit startup migration.

### 5.7 SQLite runtime configuration

The Server fixes and verifies these SQLite settings rather than exposing tuning
options:

```text
PRAGMA journal_mode = WAL
PRAGMA foreign_keys = ON
PRAGMA busy_timeout = 5000
PRAGMA synchronous = FULL
```

Connection-local settings are installed on every SQLAlchemy connection; the
persistent journal mode is established during startup. Failure to apply or read
back any required value aborts startup. `FULL` deliberately favors durability of
an acknowledged Task transition over speculative write throughput. A future
change to these constants requires measured workload evidence and is not a public
per-deployment compatibility contract.

### 5.8 Server shutdown and lease recovery

Server shutdown never rewrites running Tasks. Workers retain their local
executions and retry heartbeat/report requests while the Server is unavailable.
Before a restarted Server listens, it atomically applies the ordinary
heartbeat-expiry transition to every lease already past its Server timestamp;
non-expired leases remain active and may resume heartbeat normally. There is no
restart-specific grace period or separate recovery state.

Consequently a restart shorter than the remaining lease can be transparent,
while downtime beyond the heartbeat timeout has exactly the same semantics as any
other lost heartbeat. The normal background expiry scan continues after startup;
it runs every 60 seconds as an internal implementation constant rather than
another public setting. With the 300-second lease, unattended recovery therefore
commits between roughly five and six minutes after the last accepted heartbeat.

Claim does not opportunistically recover expired leases. Startup recovery and the
single-purpose background scan own that transition, keeping the claim path to one
atomic eligible-Task mutation. A just-expired Task may consequently wait for the
next scan before another Worker can claim it.

### 5.9 Database access and core storage

The Server uses synchronous SQLAlchemy 2.x as its database access layer and
Alembic as its schema migration layer. Private ORM models handle ordinary CRUD;
atomic claim and query-filter translation use SQLAlchemy Core expressions or
small explicit SQL statements where the ORM would obscure concurrency semantics.
Each service command owns one explicit Session/transaction.

V2 adds no async database stack, `aiosqlite`, SQLModel, repository interface,
generic Unit of Work or shared client/server model package. FastAPI runs the
synchronous application operations in its normal worker threads. Background lease
recovery opens the same short-lived synchronous Sessions rather than maintaining a
second persistence implementation.

Task identity is scoped by its Queue:

```text
PRIMARY KEY (queue_name, task_id)
```

The same explicit `task_id` may therefore identify independent Tasks in two
different Queues, and no Task operation omits Queue scope. The active claimant
token is different: a global partial unique index on non-null `active_run_id`
prevents one live run token from owning two Tasks at once. Terminal dedupe values
are historical bounded slots and do not use that active uniqueness rule.

`args`, `metadata` and `result` are stored as compact canonical UTF-8 JSON text,
with sorted object keys and database checks for valid JSON objects. The Server
uses SQLite JSON1 `json_type`/`json_extract` semantics for filtering and does not
adopt SQLite JSONB or expose storage serialization order through the API. Parsed
responses remain ordinary JSON objects; their key order is not contractual.

Database timestamps are UTC Unix microseconds stored in SQLite `INTEGER`
columns. The core names are `created_at_us`, `updated_at_us`, `started_at_us`,
`finished_at_us` and `lease_expires_at_us`; nullable public timestamps remain SQL
null. Only the Server supplies these values through one injectable clock. HTTP
converts them to UTC RFC 3339 strings with `Z` and up to microsecond precision,
and the Python client converts them to timezone-aware `datetime` values. Clients
never submit authoritative lifecycle timestamps.

The private `tasks` row contains these logical fields:

```text
queue_name, task_id
status, name
args_json, metadata_json, result_json
priority, attempt, max_attempts
created_at_us, updated_at_us
last_route, started_at_us, finished_at_us
last_error_json
creation_hash
active_run_id, lease_expires_at_us
last_terminal_run_id, last_terminal_action
pending_at_us
```

The association table below is the sole storage for `routes`; the Task row does
not also contain a route array. `last_error_json` is the latest structured error
from section 4.3 or null. `creation_hash`, active lease fields, terminal-dedupe
fields and `pending_at_us` are Server-private. The pending-position contract is
defined in section 3.9; it uses no Queue-level ticket counter and exposes no new
Task field.

Database checks enforce the core row invariants rather than trusting every code
path to reproduce them:

```text
attempt >= 0
max_attempts > 0

status = pending:
  pending_at_us IS NOT NULL
  active_run_id IS NULL
  lease_expires_at_us IS NULL
  attempt < max_attempts

status = running:
  pending_at_us IS NULL
  active_run_id IS NOT NULL
  lease_expires_at_us IS NOT NULL

status IN (succeeded, failed, cancelled):
  pending_at_us IS NULL
  active_run_id IS NULL
  lease_expires_at_us IS NULL
```

The status column itself is constrained to the five public values. These checks
do not create a new public state machine; they prevent partial or contradictory
persistence of the existing one.

Public Task `routes` is backed by a private many-to-many value table rather than a
JSON array column:

```text
task_routes(
  queue_name,
  task_id,
  route,
  PRIMARY KEY (queue_name, task_id, route),
  FOREIGN KEY (queue_name, task_id) REFERENCES tasks ON DELETE CASCADE
)

INDEX (queue_name, route, task_id)
```

This table is not a Route resource or registry: a route has no independent row,
ID, metadata, status or lifecycle. It merely stores the strings belonging to one
Task. Creation inserts the non-empty set; a routes update deletes that Task's old
association rows and inserts the complete replacement in the same transaction;
Task/Queue deletion cascades them. API assembly sorts the rows lexicographically.

Claim and route-membership filters use indexed `EXISTS`/join predicates against
`task_routes`, avoiding a `json_each` scan across every pending Task. Page reads
load all route rows for the selected Task IDs in one secondary query or equivalent
aggregate, never one query per Task. A successful claim may load its routes after
the atomic state mutation in the same transaction because running Tasks cannot
concurrently change their route set.

Claim chooses eligible Tasks by `priority DESC, pending_at_us ASC, task_id ASC`
and state mutation remains one conditional `UPDATE ... RETURNING` operation.
The idempotent same-`run_id` path may first read an already active claim; if two
identical requests race after both observe no claim, the active-run unique index
allows only one mutation and the loser reads and returns that same claimed Task.

V2 creates only indexes justified by fixed hot paths:

```text
PRIMARY KEY (queue_name, task_id)

claim:
  (queue_name, status, priority DESC, pending_at_us, task_id)

expiry scan:
  (status, lease_expires_at_us)

default list:
  (queue_name, created_at_us DESC, task_id DESC)

status list:
  (queue_name, status, created_at_us DESC, task_id DESC)

active claim lookup:
  UNIQUE (active_run_id) WHERE active_run_id IS NOT NULL

bounded terminal lookup:
  (last_terminal_run_id) WHERE last_terminal_run_id IS NOT NULL
```

The two `task_routes` indexes are defined above. The 2.0.0 initial release does not pre-index name,
arbitrary JSON paths or every optional sort field; measured query plans must
justify later additions.

Every service command that can modify data starts one SQLite `BEGIN IMMEDIATE`
transaction. This acquires the single-writer reservation before multi-step
validation while WAL readers continue, rather than allowing each command to
invent a subtly different transaction mode. Read-only commands use ordinary read
transactions.

If the fixed 5000 ms busy timeout expires before a write lock is acquired, the
Server rolls back and returns `503 Service Unavailable` with code
`database_busy`; it does not retry indefinitely. Claim can safely replay the same
logical request, terminal reporting already retries idempotently, and ordinary
updates/requeue remain explicit caller retry decisions.

### 5.10 Required persistence concurrency tests

Tests use real temporary SQLite files and independent connections, not a mocked
database. At minimum they prove:

- explicit HTTP and local Unix-socket Server processes cannot simultaneously lock
  the same actual database inode, and daemon death releases its inherited
  ownership descriptor;
- many independent Clients racing the first local operation create one daemon,
  all observe one endpoint, and no second process wins ownership during FD
  handoff;
- a launching Client can exit after spawn without releasing the daemon's inherited
  database ownership, while process-creation failure releases ownership;
- repeated fast daemon failure permits at most one automatic launch per 10-second
  interval across independent Clients, while explicit `start` bypasses the fixed
  throttle and malformed metadata cannot suppress launch;
- a live daemon or coordinator hung before readiness retains database ownership,
  causes no duplicate start and remains a visible manual-recovery case rather
  than an automatically broken lock;
- the daemon remains reachable after its launching Client process exits and is
  removed only by verified explicit stop in the ordinary lifecycle test; plain
  `stop` never sends SIGKILL, `stop --force` only kills the reverified daemon
  instance, and a later local operation may start a replacement;
- stale owned socket/metadata is recoverable while a live but unhealthy database
  owner is never removed or replaced;
- local recovery after a pre-send connect failure proceeds, while a mutation
  with an uncertain response is not replayed merely because the daemon restarts;
- different Workers racing for one Task produce exactly one successful claim;
- concurrent retries of one `run_id` return the same Task, while changing its
  route conflicts;
- complete racing heartbeat expiry produces exactly one winning transition;
- after `fail(r1)` commits, `r2` may claim and a duplicate `fail(r1)` cannot
  alter `r2`;
- update racing claim either commits complete new Task data before claim or
  excludes the now-running Task; and
- cancel racing complete produces exactly one winning lifecycle transition.

## 6. HTTP API foundation

Status: **Decided**

### 6.1 Health and schema discovery

Two unauthenticated deployment endpoints exist outside the versioned application
prefix:

```text
GET /health
GET /openapi.json
```

`/health` performs a lightweight real database query. Healthy service returns
`200 OK` with exactly:

```json
{
  "status": "ok",
  "api_version": "2",
  "database": "ok"
}
```

Database failure returns `503 Service Unavailable` with the same keys and
`"status":"error","database":"error"`. It never returns exception text, SQL,
credentials or filesystem paths. V2 adds no capability array: the API version
already identifies one complete mandatory contract without optional protocol
features.

`/openapi.json` exposes the v2 machine-readable HTTP schema for Agents, client
contract tests and tooling. FastAPI's interactive `/docs` and `/redoc` pages are
disabled; Labtasker does not ship a half-maintained Server UI. Authentication is
still required on every `/api/v2` application endpoint.

### 6.2 Versioned application API

The v2 protocol prefix is `/api/v2`. It is an HTTP API version, independent of
the Python package version.

Within `/api/v2`, compatible evolution may add endpoints, optional response
fields and new stable error codes. It may not remove or rename fields, change an
existing field's type/default/meaning, or add a Task status that an existing
`TaskStatus` client cannot parse. Such breaking changes require a new API prefix,
for example `/api/v3`, rather than relying only on a Python package major version.

Validation is intentionally asymmetric. Every Server request schema rejects
unknown fields. Client-owned response models ignore unknown response fields so an
older Client can consume a newer additive Server response; missing required
fields and wrong types for known fields still fail validation. Generic
`APIError.code` similarly permits a newer stable error code without a new Python
exception subclass.

Every HTTP request body is limited to 1 MiB (1,048,576 bytes). If a declared
`Content-Length` already exceeds the limit, the Server rejects it before reading
the body; otherwise it enforces the same cumulative limit while receiving it.
The limit applies uniformly to Task submission, updates, results, failure
tracebacks and internal Worker requests. Exceeding it returns `413` with
`code="request_too_large"` and `details.max_bytes=1048576`. V2 adds no separate
per-field size knobs. Task JSON and result summaries should be compact; artifacts,
checkpoints and large logs do not belong in the Task database.

The same 1 MiB constant also bounds the complete stored user-owned Task data.
After applying creation defaults or any mutation that changes `name`, `args`,
`metadata`, `priority`, `max_attempts`, `routes` or `result`—including
`complete(result)`—the Server canonically serializes an object containing all
seven resulting fields as compact UTF-8 JSON. If it exceeds 1,048,576 bytes, the
mutation is rejected with `422`, `code="task_data_too_large"` and
`details.max_bytes=1048576`. Batch update validates every resulting Task and rolls
back the whole batch if one exceeds the bound. Thus several individually small
PATCH requests cannot accumulate an artifact-sized Task. V2 has no blob, artifact
or large-file storage API.

V2 performs no capability or version-range negotiation. Explicit HTTP Clients
request `/api/v2` directly and add no `/health` process-management preflight; an
incompatible deployment fails through the normal HTTP/protocol error path. A
local Client may call `/health` only for the daemon discovery, startup and status
state machine in section 5.5. It does not use health as a capability handshake or
replace the ordinary operation response. `/health.api_version` remains useful for
deployment diagnosis, local ownership checks and Worker startup validation.

`/openapi.json` is the sole generated machine-readable schema. The repository
does not commit a generated SDK or maintain a second hand-written wire-model
package. CI runs the real client package against the real Server; after the first
v2 release, Server release checks also run the previous released Client through
the core submit/get/list/claim/report workflow. This small compatibility check is
required by independent installation and the lack of exact-version matching.

Queue names are explicit path components because authentication no longer implies
a Queue:

```text
/api/v2/queues/{queue}/tasks
```

Task lifecycle transitions use explicit `POST` action endpoints such as
`/cancel`, `/requeue`, `/complete` and `/fail`. V2 has no generic status patch or
public force-transition endpoint.

Claim returns `204 No Content` when no eligible Task exists. This is a normal
empty result, not an error and not a `200` response containing a nullable Task.

Task creation is addressed by a client-generated ID:

```text
PUT /api/v2/queues/{queue}/tasks/{task_id}
```

The Python and CLI clients generate a compact random ID by default, while callers
may provide one explicitly. Initial creation returns `201 Created` with the Task.
Repeating the same normalized creation request at the same ID returns `200 OK`
with the Task's current representation, even if it has since run or been edited.
Using that ID for a different creation request returns `409 Conflict` and never
overwrites the existing Task.

V2 does not add an `Idempotency-Key` header or idempotency-record table. Because
Task input may later be edited, the server needs a small internal
`creation_hash`—not a public Task field—to recognize the original creation
request. The server expands submit defaults, serializes the normalized creation
body as canonical JSON, and stores its SHA-256 hash. This is request-equality
metadata, not a credential or content-addressed Task ID. Storing a request hash
alongside an idempotency identity is a standard implementation pattern; it rejects
accidental key reuse without duplicating the full original payload.

Generated `task_id` and `run_id` use distinct `t_` and `r_` prefixes followed by
12 URL-safe characters produced from 72 bits of cryptographically secure
randomness. They contain no embedded timestamp. The prefixes make the two ID
types recognizable in logs and catch accidental type swaps; they are not an
authorization mechanism. The Queue-scoped database uniqueness constraint remains
authoritative; an auto-generated collision in that Queue is retried with a new
ID, while an explicitly supplied conflicting Task ID in the same Queue returns
`409`. The same ID in another Queue is unrelated.

Queue creation uses the same create-by-identity style:

```text
PUT /api/v2/queues/{queue}
```

It returns `201 Created` the first time and `200 OK` when that Queue already
exists. Queue has no complex creation payload requiring a creation hash.

Every API error uses one stable envelope:

```json
{
  "error": {
    "code": "task_state_conflict",
    "message": "Only failed or cancelled tasks can be requeued.",
    "details": {"task_id": "...", "status": "running"}
  }
}
```

`code` is a stable machine contract, `message` is human-readable, and `details`
is a JSON object with operation-specific context.

Request validation failures use an already documented operation-specific code
when one exists, such as `invalid_task`, `invalid_update`, `invalid_filter` or
`invalid_cursor`. Every other malformed JSON, unknown field, missing field,
wrong-type field or invalid path/query value is `422 Unprocessable Content` with
`code="invalid_request"`, message `"Request validation failed."`, and `details`
equal to:

```json
{
  "errors": [
    {"location": ["body", "route"], "message": "Expected a string."}
  ]
}
```

Each `location` is a non-empty array of string field names and/or integer array
indexes rooted at `body`, `path` or `query`; each message is concise natural
language. Malformed JSON uses location `["body"]`. The Server translates
framework-native validation output into this envelope rather than leaking
FastAPI/Pydantic's default response shape. V2 does not create separate
`invalid_claim`, `invalid_heartbeat` or `invalid_json` codes.

## 7. Worker HTTP protocol

Status: **Decided**

The next endpoint decisions cover claim, heartbeat and the three server-facing
execution outcomes. They must preserve `run_id` fencing and safe network retries
without introducing a persistent Run entity or history table.

Claim includes exactly one Worker-supplied routing field, `route`. Route is
Worker information in the literal sense, but it is not Worker identity or a
persistent Worker record. Claim does not include a worker ID, name, metadata,
resource inventory or filter. Its other request field, `run_id`, is a protocol
token generated by the Client before sending rather than Worker description:

```http
POST /api/v2/queues/{queue}/tasks/claim
Content-Type: application/json

{"route":"sdxl","run_id":"r_..."}
```

The first request with that `run_id` atomically claims an eligible Task. While it
remains active, the same `queue + route + run_id` returns the same claim rather
than taking another Task. Reusing an active `run_id` with a different Queue or
route returns `409 run_id_conflict`; an idempotency token never silently changes
the logical claim request it identifies. This makes a lost claim response safely
retryable without adding `claim_id` or an Idempotency-Key subsystem. The Client
makes at most three transport attempts for one logical claim, always replaying
the exact same request; if none obtains an explicit response, the Worker exits
nonzero. An explicit empty `204` ends that logical claim and normal idle polling
uses a new `run_id`.

A successful claim returns the complete public Task plus execution ownership:

```json
{
  "task": {"id": "t_..."},
  "run_id": "r_...",
  "lease_expires_at": "2026-08-20T12:00:00Z"
}
```

A retry of an already finalized or expired `run_id` returns `409 stale_run`
rather than assigning new work under that token.

Every active execution sends heartbeat and supports three explicit outcome
actions:

```text
complete  # store result and succeed
fail      # charged failure
unclaim   # undo this claim and return to pending without charge
```

The Python client maps `TransientError` to `unclaim`, and maps both `TaskError`
and `FatalWorkerError` to `fail` while the run remains active. After any terminal
transition, these client exceptions have no further Server-facing mapping.
Heartbeat carries no progress, ETA or Worker status.

An active `run_id` is a per-claim lease handle, not merely a second descriptive
ID. Only the claimant creates/sends it and receives it back; ordinary Task
get/list responses must not expose the active value. Possessing the server-wide
token grants broad API access, but without the active run handle another Worker
cannot accidentally heartbeat or complete that claim. Task IDs use `t_` and run
IDs use `r_`; these prefixes prevent ID-type mix-ups but are not an authorization
boundary.

Task remains the addressed resource. The claimant-only lease is carried in the
request body; v2 does not introduce `/runs/{run_id}` paths:

```text
POST /api/v2/queues/{queue}/tasks/{task_id}/heartbeat
POST /api/v2/queues/{queue}/tasks/{task_id}/complete
POST /api/v2/queues/{queue}/tasks/{task_id}/fail
POST /api/v2/queues/{queue}/tasks/{task_id}/unclaim

body: {"run_id": "r_...", ...}
```

The exact terminal request bodies are:

```text
complete: {"run_id":"r_...","result":{}}

fail: {
  "run_id":"r_...",
  "error": {
    "type":"ValueError",
    "message":"invalid image size",
    "traceback":"..."
  }
}

unclaim: {"run_id":"r_..."}
```

`result` is a strict JSON object. Client-supplied failure fields are exactly
string `type`, string `message` and nullable string `traceback`; the Server adds
the authoritative `occurred_at`, current `attempt` and `run_id` when constructing
`last_error`. Unclaim accepts no reason, result or error and never replaces
`last_error`. Unknown fields are validation errors.
An otherwise valid complete body whose result would push the full stored
user-owned Task data over 1 MiB is rejected as `422 task_data_too_large` without
finalizing the run; the claimant may retry complete with a smaller result or
report failure.

The first accepted complete, fail or unclaim returns `204 No Content`. Repeating
the same `run_id + action` also returns 204 without applying the payload again;
the first accepted body wins. The same run with a different action returns
`409 run_finalized`, and an unrelated old run returns `409 stale_run`. Terminal
actions do not return a Task representation and store no payload hash.

Heartbeat uses one global server setting, `heartbeat_timeout`, fixed at 300
seconds in v2 2.0.0. There is no per-Queue, per-Task or per-Worker override and no
public heartbeat-interval setting. The Client sends every 60 seconds. A
successful heartbeat returns `200 OK` with the renewed
`lease_expires_at`; claim returns the initial value. These timestamps are server
time and make recovery state observable.

Lease expiry is a hard Server-time boundary, not merely a hint to the background
scanner. Heartbeat, complete, fail and unclaim require
`lease_expires_at_us > now` in addition to the matching active run. If any such
request arrives at or after the deadline before the scanner has run, that request
atomically applies the ordinary heartbeat-expiry transition and is then rejected
as `409 run_finalized` with `action="heartbeat_expired"`. A concurrent scan uses
the same conditional transition, so exactly one path wins; a late complete never
revives an expired lease.

Heartbeat transport errors do not by themselves prove that the run is stale.
The Client keeps the current execution and retries. When heartbeat no longer
matches the active run, the Server consults its existing latest-terminal slot
before returning a conflict:

```json
{
  "error": {
    "code": "run_finalized",
    "message": "This run has already been finalized.",
    "details": {"action": "complete"}
  }
}
```

It returns `409 run_finalized` when `last_terminal_run_id` matches this heartbeat,
with the recorded action in details; otherwise it returns `409 stale_run`.
`run_finalized(action=complete)` tells the Client that its own run has already
completed and is not a cancellation signal. Every other finalized action and
`stale_run` activate the local cancellation contract in section 8.1. This lookup
uses the Server terminal slot, not a local file, so correctness does not depend on
the run journal being writable.

Merely passing the last observed `lease_expires_at` does not revoke locally: it is
the Server's recovery deadline and an observability value, not authorization for
a Client-side clock inference. During a partition an old and reassigned run may
temporarily compute concurrently, but `run_id` fencing prevents the old run from
writing Task result/state, Labtasker-managed run directories are distinct, and
arbitrary external side effects remain the experiment's responsibility.

Retry safety uses one active lease plus one bounded terminal deduplication slot:

```text
active_run_id
last_terminal_run_id
last_terminal_action
```

Here “terminal” means the action that ends one claimed run, not necessarily a
terminal Task status. The stored action values are exactly `complete`, `fail`,
`unclaim`, `heartbeat_expired` and `cancel`; the latter applies only when a
running Task is cancelled. For example, a retryable `fail` ends run `r1` while
returning the Task to pending. These are internal storage fields and are not
writable or exposed as ordinary Task data.

An action first performs an atomic transition conditioned on `active_run_id`. If
that misses, the same `last_terminal_run_id + action` returns success as a
duplicate; the same run with another action and every other stale run conflict.
The slot survives the next claim and is overwritten only by the next terminal
transition, so it covers the important "report committed, response lost, next run
claimed" race without creating Run history. This is bounded idempotency, not a
promise to recognize arbitrarily old retries.

Concretely: if `fail(r1)` commits but its HTTP response is lost, the Task may be
claimed again as `r2`. A retry of `fail(r1)` then matches
`last_terminal_run_id=r1` and `last_terminal_action=fail`, returns success, and
does not touch active run `r2`. A contradictory `complete(r1)` conflicts. The next
run-ending action overwrites the slot.

No terminal payload hash is part of the v2 contract: the first accepted
body wins and a duplicate of the same run/action has no effect. A payload hash
would only diagnose a buggy client resending the same action with different data;
it remains deferred unless that real failure mode justifies the extra field. V2
also does not create a Run entity or execution-history table.

Once a terminal action is initiated, the Worker does not claim another Task until
that outcome is resolved and any still-running user function or command child has
returned. It continues heartbeat while retrying the same idempotent terminal
action with internal backoff. Success or a terminal-deduplication hit ends Server
ownership; explicit stale discards the outcome; a non-retryable protocol 4xx logs
the error and exits the Worker nonzero. Transport errors, timeouts and 5xx
responses keep retrying without a public report timeout, protecting an expensive
completed experiment from a brief outage. External process termination still
stops these retries and heartbeat-expiry recovery then applies. An early explicit
`finish()` is the special case where Server ownership ends successfully while the
local executor may continue cleanup; it never permits the Worker to claim a
second Task concurrently.

## 8. Python Worker API

Status: **Decided**

One invocation of a decorated Worker function, or one `labtasker loop` command,
defines one local Worker process lifecycle. The server stores no Worker resource
or process state. A Worker executes at most one Task at a time, while its code,
loaded models and ordinary non-Task function arguments remain fixed and reusable
across successive Tasks in that process. Worker entrypoints are intended to run
as dedicated processes rather than as one responsibility inside an unrelated
long-lived application process.

Every successful claim uses a distinct Labtasker-managed local run journal keyed
by its `run_id`; retries and concurrent old/new executions never reuse that
directory. Section 8.4 defines its stable layout and synchronization boundary.
This isolation covers Labtasker's logs and managed files only. Paths in user code
and third-party tracking/artifact systems remain the experiment's responsibility.

V2 initially supports synchronous Worker functions only. It does not accept
`async def` handlers or add an async client/loop execution branch before a real
workload requires one.

The complete decorator signature is intentionally small:

```text
loop(
    *,
    route: str = "default",
    queue: str | None = None,
    idle_timeout: float = 300.0,
    force_stop_timeout: float | None = None,
)
```

V2 supports only the explicit `@loop(...)` spelling, not a second bare `@loop`
form. Queue uses the ordinary Client resolution chain. The decorator has no
Client, filter, heartbeat, required-fields, full-args-dict or execution-timeout
parameter.

Inside an active Python execution, `task_info()` returns a frozen, local-only
`TaskInfo`. It preserves the flat v1 access style by containing the public Task
fields directly and adds exactly `run_id: str` and `run_dir: pathlib.Path` for the
claimant. `TaskInfo` is not an HTTP response or Server resource and never appears
in get/list; ordinary public `Task` therefore continues to hide active run data.

`finish(result={...})` immediately completes the current Task as `succeeded`, but
it is an ordinary function call and does not raise an internal control-flow
exception. It returns only after the idempotent terminal report has been accepted
or deduplicated; heartbeat remains active while that report is unresolved.
`finish()` is equivalent to `finish(result={})`. Code after it continues to run,
which lets a workload durably publish an already-obtained result before slow,
fragile or indefinitely blocked engine/resource shutdown. The local Worker does
not claim another Task until the function or command child actually returns.

The first successful `finish()` finalizes the run. A second call in the same
execution raises `RuntimeError`, and the wrapper's later normal-return path does
not send another completion. An ordinary exception or nonzero command exit after
a successful `finish()` is logged locally but cannot retroactively fail or change
the already-succeeded Task. `FatalWorkerError` may still terminate an unsafe
Python Worker, but it likewise cannot rewrite the completed Task.

`task_info()` remains available with the same frozen claim snapshot until the
function or command child actually exits, including during code that runs after a
successful `finish()`. V2 does not add a second local `executor_exited_at`
timestamp: public `finished_at` and journal finish/acknowledgement time describe
Server run completion, while post-finish cleanup duration is not modeled.

Task-injected parameters use one explicit `TaskArg` marker, replacing v1's
misleadingly named `Required` marker:

```text
TaskArg(
    *,
    default=...,  # omission-sensitive private sentinel
    path: str | None = None,
    resolver: Callable[[Any], Any] | None = None,
)
```

All arguments are keyword-only. Omitting `default` means required; explicitly
passing any value, including `None`, supplies that default. The omission sentinel
is private and is not another public value users import or submit. `path=None`
selects the top-level key named after the decorated parameter. `resolver`, when
present, is one synchronous callable accepting exactly the selected/default value
and returning the value to validate and inject; Labtasker supplies no Task or
context second argument and does not await it.

```python
@labtasker.loop(route="sdxl")
def run(
    model,
    prompt: str = TaskArg(),
    steps: int = TaskArg(default=30),
): ...


run(load_model())
```

`TaskArg()` requires the corresponding Task field. `TaskArg(default=value)` uses
that value when the field is absent. Whether selected from the Task or supplied by
the default, the value passes through the same resolver and strict-validation
pipeline. Unmarked parameters remain ordinary Python parameters supplied when the
decorated Worker is started. This preserves the
useful v1 distinction between per-Task values and fixed runtime objects without
using every function parameter as an injection point.

`TaskArg(path="optimizer.lr")` may select a nested value. Without `path`, the
top-level field matching the function parameter name is used. This reuses exactly
the same dot-path syntax as command placeholders: every segment is an ASCII
identifier matching `[A-Za-z_][A-Za-z0-9_]*` and traverses JSON objects only.
There are no array indexes, numeric segments, hyphenated or Unicode segments,
wildcards or escapes. A JSON key outside that grammar, including one containing a
literal dot, may still be stored and read through `task_info().args`, but is not
addressable through dot-path syntax. V2 exposes `path`, not v1's ambiguous
`alias` name.

Injected values are checked against their annotations using Pydantic strict mode.
An explicit resolver receives one selected value and fully owns any
application-specific conversion; its result passes through the same annotation
schema. Labtasker itself does not pre-cast the input or add a fallback conversion
after validation. A value-dependent failure is a normal `TaskError`. Static
signature, annotation and resolver-shape errors fail before the Worker claims a
Task. CLI parsing is not part of Worker resolution: the CLI cannot know a future
Worker's signature and therefore only constructs typed JSON.

The implementation compiles one Pydantic
`TypeAdapter(annotation)` for every annotated `TaskArg` during Worker startup and
validates each selected/default/resolved value with
`validate_python(value, strict=True)`. An annotation that Pydantic cannot compile
is therefore a static startup error before claim. For example, an `int` annotation
accepts a JSON integer but rejects `1.0`, `"1"` and `True`. A resolver targeting a
custom type may explicitly construct its final value, but Pydantic models,
dataclasses and custom Pydantic schemas retain the strict behavior defined by that
annotation's own schema. Labtasker neither overrides those schemas nor promises
instance-only validation. Use an explicit resolver when application-specific
conversion is required. V2 does not maintain a second custom typing validator or
a coercive fallback path.

`TaskArg()` without a Python annotation is allowed. It skips final type
validation and injects the selected raw value or resolver result.

V2 does not expose `pass_args_dict` or `required_fields`. Dynamic code reads the
already available `task_info().args` object.

V2 supports only the default-marker declaration shown above; it does not also
accept `Annotated[T, TaskArg(...)]`. `TaskArg` is publicly typed as a generic
factory whose overloads return the resolver's output type, the default's type, or
`Any` when neither can determine a type. At runtime the factory returns a private
marker consumed by `@loop`. This typing facade lets the decorated call omit
injected parameters without reporting an incompatible marker default, while still
checking typed default/resolver combinations where inference is possible.

### 8.1 Revoked runs and local cancellation

Status: **Decided**

An explicit `stale_run`, or `run_finalized` with any action other than `complete`,
means the current local execution has lost ownership. A matching
`run_finalized(action=complete)` instead confirms that this same run already
succeeded, so the Client stops heartbeat but allows post-finish local cleanup to
continue. The distinction comes from Server state and does not rely on the local
journal. Revocation applies only to that run; it does not imply that the reusable
Worker process, loaded model or route is invalid. Transport timeouts,
disconnections and other uncertain heartbeat errors are not treated as confirmed
revocation.

After confirmed revocation the heartbeat stops, and the client never reports a
completion or failure for that run. Once the current executor has stopped, the
same Worker normally clears its local Task context and returns to claim. If the
rejection is first learned from a terminal report after user execution has already
ended, there is nothing left to interrupt and the Worker may proceed directly.

The two executors stop current work differently:

- A command Worker owns a child process group. It sends termination to that group
  and waits for it to end. If a finite force-stop timeout was explicitly
  configured, it force-kills any remainder after that duration; the default null
  value waits naturally. The parent then continues its Worker loop.
- A synchronous Python Worker executes user code inline and cannot safely receive
  an exception injected from its heartbeat thread. Confirmed revocation therefore
  sets a process-local cancellation event. Cooperative code detects it through a
  small public polling function, performs cleanup and returns normally. The
  wrapper then discards the revoked outcome and continues the Worker loop.

Python cancellation waits for natural return by default. The default null
force-stop timeout creates no deadline. If a finite timeout is explicitly set and
the function has not returned when its deadline expires, the client terminates
the whole dedicated Worker process; Python provides no safe way to kill only an
arbitrary inline function while preserving its process. Cooperative code may
explicitly replace the current run's timeout through a setter, allowing either a
bounded cleanup period or an unbounded natural wait without changing the Worker
default for later Tasks.

The Python Worker configuration and cooperative API are exactly:

```text
@labtasker.loop(force_stop_timeout=None)
def run(...):
    ...

labtasker.cancellation_requested() -> bool
labtasker.set_force_stop_timeout(seconds: float | None) -> None
```

`force_stop_timeout` accepts a finite non-negative number of seconds or null and
defaults to null. Zero requests immediate force-stop after confirmed revocation;
null waits for natural return indefinitely. A `labtasker loop` command exposes
optional `--force-stop-timeout FLOAT`; omitting it has the same null/natural-wait
meaning. Python accepts a finite `int` or `float`; Python/CLI reject booleans,
NaN, infinities and negative values before the first claim.

`cancellation_requested()` is a pure local query. The setter replaces the timeout
for the current run only and may be called before or after revocation; it never
changes the Worker default used by the next Task. Null gives that Python run an
unbounded natural wait. Both functions require an active Python Task execution
context and otherwise raise `RuntimeError`.

After a successful `finish()`, the local execution context remains available for
cleanup but the Server run is already final. During that interval
`cancellation_requested()` returns false and `set_force_stop_timeout(...)` raises
`RuntimeError` because there is no longer a cancellable run or revocation deadline.
`task_info()` continues to return the frozen claim snapshot as described above.

If revocation has already occurred, setting a timeout computes the force-stop
deadline as `revoked_at + seconds`, replacing the previous duration. Repeating
the same setter call therefore does not keep moving the deadline forward. A new
deadline that has already passed becomes immediately eligible for force-stop.
This is intentionally named `set_force_stop_timeout`, not `extend_*`: an explicit
setter may either lengthen or shorten the current run's remaining time.

Once revocation is confirmed, an ordinary exception raised during cooperative
cleanup is recorded only in local logging; it cannot be reported as a
failure of a run the Worker no longer owns. The Worker then continues to claim.
`FatalWorkerError` still declares the reusable process unsafe and exits it. A
force-stop deadline that expires terminates the Worker with a nonzero process
status so an external supervisor can decide whether to replace it.

V2 does not use cross-thread asynchronous exception injection, signal tricks,
trace hooks, abandoned live threads or one subprocess per Python Task. Those
approaches either corrupt ordinary Python expectations or defeat process-local
model reuse.

`task_info()`, `cancellation_requested()` and `set_force_stop_timeout()` require
an active Python Task execution. Calling them during Worker startup, idle polling,
ordinary submission code or after execution has ended raises `RuntimeError`.

`finish()` is strict by default but retains one explicit low-intrusion escape
hatch for code intentionally shared between standalone and Labtasker execution:

```text
finish(
    result: dict[str, JSONValue] | None = None,
    *,
    skip_if_no_labtasker: bool = False,
) -> None
```

`result` may be omitted and then means `{}`. It must otherwise be a JSON object.

With `skip_if_no_labtasker=True`, absence of an active Labtasker execution makes
the call a no-op. V2 retains this established v1 name rather than adding a second
`allow_standalone` spelling, but reverses v1's permissive default so accidental
missing Worker context is diagnosed. “No Labtasker” means only that execution
context is absent; invalid result data, duplicate/contradictory completion,
transport failures and Server errors remain visible. V2 uses an argument instead
of recommending `try/except RuntimeError`, which could accidentally swallow
unrelated runtime failures.

### 8.2 Worker startup and exit

Status: **Decided**

Before its first claim, a Worker validates its static arguments and required
platform capabilities, resolves and validates configuration, confirms
authentication and Queue existence, and validates a Python handler's static
signature and `TaskArg` definitions. A platform-capability failure occurs before
Client construction or network access. Other failure at this stage raises the
corresponding Python exception or writes a CLI log diagnostic and exits nonzero.
It cannot create a Task failure because no Task is owned. Exhausting the three
transport attempts for a logical claim has the same Worker failure behavior.

The word “retry” refers to three deliberately separate mechanisms:

| Mechanism | Owner | Effect when exhausted |
|---|---|---|
| Task `attempt / max_attempts` | Server Task state | The Task becomes `failed`; the Worker continues claiming other Tasks. |
| HTTP transport attempts such as claim's three tries | Client request logic | That request fails; for claim/startup failure the local Worker exits nonzero. |
| Worker process restart | External supervisor or Agent | Labtasker itself has no restart counter or policy. |

Accordingly, reaching a Task's `max_attempts` never terminates its Worker. The
Server maintains Task and current-run correctness only: Task lifecycle/retry
fields, `active_run_id`, heartbeat expiry, terminal-deduplication slots and the
latest-run summary. It stores no `worker_id`, Worker row, online/idle/crashed
status, process retry counter, resource inventory, current-process heartbeat or
remote lifecycle command. Claim `route` is used for matching and copied to
`last_route`; it does not register a Worker. Run heartbeat describes one claimed
execution, not the health of a persistent Worker.

An explicit empty claim starts the `idle_timeout`; a successful claim resets it.
When the timeout expires without work, a decorated Python Worker returns `None`
and a command Worker exits zero. Task success, ordinary charged failure and
transient unclaim resolve only the current run and return to claim.

Worker process statuses stay conventional and small:

```text
0    normal idle-timeout completion
1    Worker configuration, protocol, transport, FatalWorkerError or force-stop failure
2    CLI argument/usage error (Typer convention)
130  KeyboardInterrupt
```

An operating-system signal retains its platform signal status rather than being
remapped. A command child process's nonzero status remains a TaskError outcome
handled by the parent Worker and does not directly become the Worker's own exit
status.

Python preserves control-flow causes. `KeyboardInterrupt` performs best-effort
unclaim and is re-raised. `SystemExit` is not caught or converted into a Task
outcome, and Labtasker installs no SIGTERM handler. `FatalWorkerError` first
resolves the idempotent `fail` report under the terminal-report rules only when
the run remains active, and is then re-raised. If `finish()` already succeeded,
it sends no Task action and is simply re-raised to terminate the unsafe Worker;
the Task remains succeeded. Claim/config/protocol/transport failures raise their
corresponding `LabtaskerError`. Only idle timeout returns normally.

V2 adds no `max_tasks`, `once`, `stop_after_current`, `daemon` or automatic
restart option. Without a server-side Worker identity, a remote
`stop_after_current` would require an otherwise unnecessary control channel;
daemon/restart behavior belongs to the external process supervisor. `max_tasks`
and `once` are omitted until a concrete bounded-worker workflow justifies their
counting and outcome semantics. `idle_timeout=0` means exit on the first explicit
empty claim, not “execute exactly one Task”; a continuously non-empty Queue can
still feed the Worker repeatedly.

### 8.3 Command Worker completion

Status: **Decided**

A command Worker is the child program launched for a claimed Task by
`labtasker loop`. It inherits the parent Worker's ordinary environment and the
Client overwrites the effective execution context through these reserved
environment variables:

```text
LABTASKER_URL             # HTTP mode only
LABTASKER_TOKEN           # HTTP mode only; omitted when authentication is disabled
LABTASKER_SOCKET          # local mode only
LABTASKER_LOCAL_DIRECTORY # local mode only; canonical absolute CWD snapshot
LABTASKER_QUEUE
LABTASKER_TASK_ID
LABTASKER_RUN_ID
LABTASKER_ROUTE
LABTASKER_RUN_DIR
```

Exactly one endpoint form is present. HTTP mode overwrites `LABTASKER_URL` and
removes both local variables. Local mode overwrites `LABTASKER_SOCKET` and
`LABTASKER_LOCAL_DIRECTORY` and removes `LABTASKER_URL` and `LABTASKER_TOKEN`.
If HTTP authentication is disabled, `LABTASKER_TOKEN` is absent even when the
parent environment happened to contain that name. These variables are
Worker-provided execution context, not a second user-facing connection or
environment templating system.

In authenticated HTTP mode the Server token is necessarily available because
child code that calls `finish()` performs the same authenticated, run-fenced
completion as the parent. It remains a server-wide trust-domain credential, not a
per-run authorization mechanism. Local mode instead reconstructs the already
selected Unix-socket endpoint; it never re-resolves from the child CWD. The opaque
`run_id` provides concurrency fencing in both modes.

Importing Labtasker in that child reconstructs the current Task context from the
environment and `task.json`. It may therefore call `task_info()` and
`finish(result)` just as v1 command scripts could. `finish()` attempts to record
the exact complete payload and `reporting` phase in the shared run journal, then
retries the ordinary run-fenced complete endpoint until resolved regardless of
whether that backup succeeded. Once accepted or deduplicated it best-effort
records `acknowledged` and returns to the child program.

Before reporting, `finish()` makes a best-effort atomic write of the exact result
payload and `reporting + complete` phase. A successful write makes the payload
immutable for local recovery, but this journal is a backup rather than part of
the success condition. A write failure produces a visible warning and completion
continues; it does not raise from `finish()`, convert the Task to failure or wait
indefinitely for local storage. Server fencing and terminal deduplication remain
the source of correctness.

The parent owns heartbeat and subprocess lifetime. Heartbeat continues until the
complete report is resolved so a transient network outage does not abandon an
expensive result. The two Server requests may race safely without consulting the
journal:

- If heartbeat commits first, it only renews the same lease and complete may then
  succeed normally.
- If complete commits first, a later heartbeat finds the same run in the Server's
  terminal slot and returns `run_finalized(action=complete)`, not generic stale.
  The parent stops heartbeat and continues waiting for the child to end naturally.
- If another action or lease recovery ended the run first, complete is rejected as
  stale and heartbeat reports stale or a non-complete finalized action; the parent
  then applies the command-child cancellation behavior from section 8.1.

This permits slow, broken or indefinitely blocked engine shutdown after the
desired result has already been secured, even when no local backup could be
written. A heartbeat response never turns a failed complete into success: only a
matching Server terminal record with action `complete` has the benign finalized
meaning.

When the journal write did succeed and the child exits while still `reporting`,
the parent reads `result.json` and takes over retries of that exact complete
action. It does not synthesize `{}` or create another terminal intent. If no
payload was persisted, this optional crash-recovery path is unavailable, but the
child's live `finish()` still reports directly to the Server and local backup
failure is not itself a Task or Worker error. If the child exits while the journal
is still `running`, the ordinary exit-code rule chooses parent-side complete `{}`
or fail.

Python Workers use the same Server protocol and an in-process flag to reject a
second `finish()` call. No additional socket, pipe or command-specific result
protocol is introduced.

If the child never calls `finish()`, exit code zero makes the parent complete with
`{}` and a nonzero exit follows the ordinary `TaskError` path. If the child did
successfully call `finish()`, its later exit status cannot rewrite that outcome;
the parent records any nonzero post-finish exit as a local diagnostic and
continues. A second `finish()` call is an explicit `RuntimeError`, not a silent
no-op or last-write-wins update.

### 8.4 Local run journal

Status: **Decided**

Creating the run directory and its initial `task.json`/`run.json` is part of local
execution setup, not the best-effort terminal backup policy below. If this initial
setup fails after claim, the Client does not start user code or a command child;
it makes a best-effort `unclaim` and exits the Worker nonzero. This avoids running
without the promised `TaskInfo.run_dir`, Task snapshot and log destination. A
successful unclaim restores pending without charging the incident.

The local journal is deliberately semantic enough for a person or Agent to
browse without first querying the Server. Its root is relative to the Worker's
current directory and its stable layout is:

```text
.labtasker/
  .gitignore
  runs/{queue}/
    {task-name-slug}__{task_id}/
      {started-at}__attempt-{attempt}__{run_id}/
        task.json
        run.json
        result.json
        error.json
        run.log
```

Before creating the first run directory, the Client exclusively creates
`.labtasker/.gitignore` with `*` and `!.gitignore` rules. This keeps the entire
local state directory ignored while allowing the ignore file itself to be
committed. An existing file or filesystem entry at that path is never inspected
or overwritten. Failure to create a required new ignore file is an initial local
setup failure under the rule above.

For example:

```text
.labtasker/runs/default/
  sdxl-baseline__t_aB3dE5fG7hJ9/
    20260820T143522Z__attempt-2__r_xY2zA4bC6dE8/
```

`started-at` is compact UTC in `YYYYMMDDTHHMMSSZ` form. The slug starts from the
Task name, or `unnamed` when it is null or empty. It preserves each code point for
which Python `str.isalnum()` is true, replaces every maximal run of all other code
points with one ASCII `-`, strips leading/trailing `-`, and falls back to
`unnamed` if nothing remains. Case is preserved and no Unicode normalization is
performed. It is then truncated to the longest whole-code-point UTF-8 prefix of
at most 80 bytes, with a trailing `-` stripped again; an empty result again becomes
`unnamed`. The `task_id` and `run_id`, not either display component, provide
identity, so truncation or slug collision is harmless. Runs of the same Task are
grouped under the directory whose suffix is that `task_id`; the directory is not
renamed when the Task name or final status later changes. The complete exact name
remains in `task.json` and on the Server.

Each file has one narrow role:

- `task.json` is the complete immutable Task snapshot returned by the successful
  claim.
- `run.json` is the local execution journal. It contains a journal schema
  version, a credential-free Server endpoint object, Queue, Task ID, run ID,
  route, attempt, start and finish timestamps, local phase, terminal action and
  Server acknowledgement time. The endpoint object always has `mode`, `url`,
  `socket`, `directory` and `database`: HTTP mode fills only `url`, while local
  mode fills the other three endpoint paths. This snapshot prevents recovery or
  a command child from silently retargeting after CWD or environment changes.
- `result.json` is present after a completion outcome is prepared and contains
  the exact JSON payload sent by `complete`.
- `error.json` is present after a failure outcome is prepared and contains the
  exact JSON payload sent by `fail`.
- `run.log` receives Python-level stdout/stderr and Labtasker logging from a
  Python Worker, or raw child stdout/stderr from a Command Worker. V2 does not
  promise perfect cross-stream ordering or capture direct native file-descriptor
  writes from arbitrary Python extensions.

Python Worker capture retains v1's useful terminal-and-file tee but replaces its
implementation boundary. Merely importing Labtasker never replaces
`sys.stdout`/`sys.stderr` or configures logging. When a Worker invocation actually
starts, it installs one process-scoped text tee around the then-current streams;
the wrappers are restored when that Worker invocation returns. During one Task,
stdout and stderr share one locked active `run.log` destination, so Python-level
`print()`/stderr from the Task's threads are both displayed and journaled. V2
needs no nested destinations or ContextVar routing because one Worker process
executes at most one Task at a time. A Task must not leave output-producing
threads alive after its function returns; such threads are outside its execution
lifetime.

The tee preserves text, including ANSI sequences, and does not claim to intercept
`os.write`, native-library fd writes or arbitrary child processes. A forked child
disables the inherited run-log destination so multiple processes do not silently
share one Python tee file. Command Workers do not use this text tee at all; their
PTY/pipe path remains the raw-byte contract in section 2.3.

At Worker startup, Labtasker respects an effective user configuration for the
`labtasker` standard-library logger. If no real handler is available, it installs
one INFO stderr fallback handler on that named logger only. The fallback formats
each record as a millisecond UTC RFC 3339 timestamp, level, `[labtasker]`, then
the message. It never calls `logging.basicConfig()`, mutates the root logger,
removes user handlers or resets Loguru. Installing the fallback after the tee
makes Labtasker's own Task-time messages part of `run.log` without taking
ownership of application logging.

An `unclaim` has no result or error payload file. JSON journal files use UTF-8 and
two-space indentation. Labtasker exposes the absolute run directory through
`TaskInfo.run_dir` and as `LABTASKER_RUN_DIR` to a command child, but does not
change the user's working directory. V2 does not retain `LABTASKER_LOG_DIR` as a
second public path contract.

Journal updates follow Worker-observed execution, not every remote Task change:

1. After claim succeeds and before user code starts, write `task.json` and
   `run.json` with phase `running`.
2. Before first sending `complete`, `fail` or `unclaim`, atomically write its
   payload file when applicable and replace `run.json` with phase `reporting` and
   the chosen terminal action.
3. When the Server accepts or deduplicates that action, replace `run.json` with
   phase `acknowledged`, the finish time and acknowledgement time.
4. When the terminal action itself is explicitly rejected as `stale_run`, replace
   `run.json` with phase `revoked`. A racing stale heartbeat does not perform this
   transition while a matching local complete is `reporting`; section 8.3 governs
   that resolution. No terminal result is then accepted for that run.

Writes use a temporary file and same-directory atomic replacement so a reader
does not observe a partially encoded JSON document. A process crash may leave the
journal at its last completed phase; that durable ambiguity is useful diagnostic
information rather than something Labtasker silently rewrites on the next start.

Outcome-journal writes are best effort. Failure to create or replace
`result.json`, `error.json` or a terminal `run.json` phase is warned to stderr and
ordinary logging where available, but never blocks or changes the corresponding
Server complete/fail/unclaim action. In particular, `finish()` proceeds to its
run-fenced Server report and may succeed even when no local result backup was
written. This deliberately prioritizes the authoritative Task outcome; the cost
is only reduced local observability and loss of the optional parent takeover or
future recovery path for that payload.

The journal is a local record of the last state observed by that Worker, not an
authoritative or real-time mirror of the Server. A later remote cancellation,
heartbeat expiry, Task update or deletion need not appear locally. Conversely,
local files never override run fencing or prove that the Server accepted an
outcome.

The stored Server location, identifiers, terminal action and exact payload make
a future explicit recovery tool possible, but v2 does not scan journals on
startup, automatically replay reports, restore deleted Tasks or offer a force
operation that bypasses stale-run fencing. It also performs no automatic cleanup,
retention, compression or cascade deletion of local journals; deleting them is an
explicit local operation outside the Server Task lifecycle.

### 8.5 Single-node distributed launchers

Status: **Decided**

V2 supports single-node `torchrun` and `accelerate launch` by keeping Labtasker
outside the distributed launcher:

```text
Labtasker command Worker: claim + run_id + heartbeat + terminal report
└── one torchrun/accelerate launcher invocation
    ├── rank 0
    ├── rank 1
    └── ...
```

For example:

```bash
labtasker loop --route train -- \
  torchrun --nproc-per-node=8 train.py --lr '%{lr}' --model '%{model}'

labtasker loop --route train -- \
  accelerate launch --num_processes 8 train.py --lr '%{lr}'
```

One claimed Task therefore owns one launcher invocation and all of its ranks.
Labtasker starts only one heartbeat thread in its outer parent process. On POSIX,
a subprocess implementation may use `fork`, `vfork` or `posix_spawn`, but the
command is executed across an `exec` boundary. A plain `fork` child contains only
the thread that called `fork`, not a copy of the parent's heartbeat thread, and
`exec` then replaces that transitional address space with the launcher program.
Ranks subsequently created by torchrun/Accelerate descend from that post-exec
launcher, which never contained the Labtasker heartbeat.

The Client closes every non-required file descriptor when launching the command
(`close_fds` or the platform equivalent), passing only the explicitly configured
stdio/PTY descriptors. It uses supported subprocess session/process-group
options rather than running Python `preexec_fn` code in the multithreaded child.
Ranks inherit argv and the deliberately supplied environment, but not a live HTTP
connection, the parent's in-memory Client state or its heartbeat thread.
Importing Labtasker in a rank performs no network access and starts no background
work; a rank makes a request only if user code explicitly calls an API such as
`finish()`.

The launcher is the ordinary command child under the existing process contract:
zero exit completes with `{}`, nonzero exit or signal behaves as `TaskError`, and
confirmed revocation terminates the launcher's entire local process group. The
launcher remains responsible for propagating rank failure and shutdown. V2 does
not inspect rank logs or add rank-aware failure aggregation.

Only one distributed process may report an explicit result. Labtasker does not
guess which process is main and does not silently ignore calls from other ranks:

```python
# Native PyTorch, after process-group initialization
if torch.distributed.get_rank() == 0:
    labtasker.finish({"accuracy": accuracy})

# Accelerate
if accelerator.is_main_process:
    labtasker.finish({"accuracy": accuracy})
```

Every rank inherits the same claimant context, so concurrent `finish()` calls
would race under first-accepted-payload semantics. They are a user-code error,
not a supported result-reduction mechanism. `RANK == "0"` is acceptable as a
torchrun-specific fallback, but is not the framework-independent Labtasker
contract; framework APIs are authoritative.

The inverse topology is unsupported:

```text
torchrun/accelerate
├── rank 0 -> starts a Labtasker loop -> independently claims Task A
└── rank 1 -> starts a Labtasker loop -> independently claims Task B
```

To prevent this common silent mistake, every Python or command loop performs two
pre-claim guards:

1. Starting a loop while an inherited active Labtasker Task context is already
   present is rejected as a nested Worker.
2. A parseable `WORLD_SIZE > 1` together with `RANK` or `LOCAL_RANK` is rejected
   as a recognized distributed rank environment.

Either guard raises `ConfigError` before any claim and tells the caller to place
`labtasker loop` outside the launcher. The environment check is a safety guard
for the conventions shared by torchrun and common PyTorch-based launchers, not a
universal rank-discovery protocol; v2 adds no override or growing registry of
launcher-specific variables.

V2 deliberately does not support a persistent distributed Python `@loop` whose
ranks stay alive across multiple Tasks. Such a mode would need Task broadcast,
cross-rank failure aggregation, cancellation coordination and rules for reusing a
potentially poisoned process group. For single-node experiment dispatch, starting
one ordinary launcher per Task is the supported complete model and adds no Server
Worker, rank or resource entity.

This ownership boundary receives dedicated tests:

- the ordinary PR suite uses a lightweight fake launcher that starts several
  rank-like subprocesses, imports Labtasker in each and verifies one claim, one
  parent heartbeat source, identical resolved Task input and no child background
  network activity;
- it also verifies zero/nonzero launcher outcomes, process-group cancellation,
  rank-0-only explicit completion and both pre-claim misuse guards; and
- a separately marked distributed integration suite runs real single-node
  `torchrun` and Accelerate cases. Its heavyweight framework dependencies are not
  client runtime dependencies or required by unrelated unit tests, but the suite
  runs before a v2 release and in scheduled CI.

## 9. Client and CLI API

Status: **Decided**

### 9.1 CLI surface and configuration

The v2 client executable has this complete command tree:

```text
labtasker task submit|get|list|count|update|cancel|requeue|delete
labtasker queue create|list|delete
labtasker loop
labtasker config show
```

The Server remains a separate runtime package and executable with the
`start|status|stop|logs|serve` commands from section 5.5; there is no `labtasker
server` command. V2 provides no `worker`, `event`, `admin`, pager or TUI commands
and no abbreviated command aliases such as `ls` or `rm`.

CLI output is command-shaped rather than universally JSON. Finite resource and
inspection commands write their already-specified formatted JSON values to
stdout so Agents can consume them. `labtasker loop` is a continuing execution
process and emits Labtasker operational messages through ordinary Python
`logging` on stderr while relaying user-code output under the command/Python
Worker rules; it does not emit a stream of JSON event objects. The Server also
uses ordinary human-readable Python logging. Labtasker's default formatter for
both long-running processes starts every record with an RFC 3339 UTC timestamp
including milliseconds, then the level and the component prefix `[labtasker]` or
`[labtasker-server]`. An application-provided handler for the `labtasker` logger
retains control of its own format. V2 adds neither JSONL logging nor a
`--log-format` switch, and individual log messages are not an API contract. Both
CLI-owned Worker logging and Server logging default to INFO; v2 adds no
`--verbose`, `--quiet` or `--log-level` flag.

Handled `LabtaskerError`s from finite `task`, `queue` and `config` commands write
one indented, human-readable JSON object to stdout using the same envelope shape
as the HTTP API:

```json
{
  "error": {
    "code": "task_not_found",
    "message": "Task does not exist.",
    "details": {"task_id": "t_..."}
  }
}
```

An `APIError` preserves the Server's code, message and details. Local
configuration and transport failures use their stable Client error code, readable
message and structured details. These handled operational failures exit `1`.
stdout is the single machine-readable response channel for finite commands:
callers distinguish successful data from the top-level `error` envelope using
the process exit status and response shape. Typer argument/usage errors remain
concise natural-language stderr and exit `2`; they are not disguised as an API
response because no valid operation was formed. `loop` startup and runtime
failures likewise remain ordinary logging because it is a continuing operational
command, not a finite data request. V2 adds no output-format switch for these
cases.

Connection selection and automatic local process management are deliberately
visible. On a Client instance's first successful connection, before returning
the requested value, the Client writes one concise `[labtasker] connected`
diagnostic to the then-current stderr. It identifies `server=local` with
`transport=unix`, the canonical directory, database and socket, plus the verified
daemon PID and Server package version when available; unavailable runtime values
are written as `unknown`. An explicit URL identifies `server=remote`, derives
`transport=http|https` from that URL and writes the complete credential-free
base URL. It never prints a token.

A local startup additionally writes component-prefixed diagnostics when it
requests or starts a daemon, waits for another startup, observes readiness or
declines to start during the fixed launch throttle; a later automatic restart is
announced in the same way. `labtasker` Client messages use `[labtasker]`, while
messages emitted by the Server executable use `[labtasker-server]`. Throttle
diagnostics include the remaining seconds and log path. These finite-operation
diagnostics have no timestamp and are required even for direct Python API use
rather than being INFO records hidden by application logging. The successful
connection line occurs at most once per Client instance, plus a new line after
actual local reconnection. Every successful CLI invocation therefore makes its
selected Server and transport visible without contaminating requested stdout.
When a finite CLI operation later fails, transition diagnostics remain on
stderr while the structured error envelope is the only stdout document. The
envelope retains its exact shape, and its details identify a connection target
that could not be reached. Diagnostics never need to be stripped from the
machine-readable response before parsing.

Local Worker exception logging follows the Client outcome abstraction without
changing it: `TransientError` logs at WARNING with type/message but no default
traceback; `TaskError` logs at ERROR with traceback; `FatalWorkerError` logs at
CRITICAL with traceback before the Python Worker exits. A command child failing
by exit code or signal logs one ERROR containing that outcome, but does not copy
its already-relayed output into a second diagnostic message.

Authorization headers and token values must never appear in logs or errors.
Other diagnostic data—including Queue, Task ID, route, run ID, status, action,
attempt, timing, args, metadata, result and traceback—may be logged when useful;
v2 imposes no field-by-field redaction system. Ordinary success logs should still
avoid dumping large payloads without diagnostic value.

Every Task leaf command and `loop` accepts `--queue` at that leaf position, for
example:

```text
labtasker task list --queue experiments
labtasker loop --queue experiments --route sdxl -- python train.py
```

There is no alternate global `labtasker --queue ...` placement and no CLI
`--url` or `--token` connection override. A one-off URL/token override uses
`LABTASKER_URL`/`LABTASKER_TOKEN`; `--queue` remains because choosing a Task
namespace is a routine resource operation rather than connection setup.

V2 does not implement `config init`, `config set` or `config write`. An Agent or
user may create the three-field `.labtasker/config.toml` directly, or use the
corresponding environment variables. The sole diagnostic command is read-only:

```text
labtasker config show
```

It performs no network request, creates no local files and writes exactly this
formatted JSON shape after normal configuration resolution. Unused endpoint
fields are null:

```json
{
  "mode": "local",
  "directory": "/absolute/current/directory",
  "database": "/absolute/current/directory/.labtasker/server.db",
  "socket": "/tmp/labtasker-1000/0123456789abcdef.sock",
  "url": null,
  "queue": "default",
  "token_configured": false
}
```

For an explicit HTTP configuration, `mode` is `"http"`, `url` contains the
normalized base URL, and `directory`, `database` and `socket` are null. The socket
shown above abbreviates the required full SHA-256 filename only for readability;
the real output contains the exact resolved path.

The token value is never printed. Invalid configuration fails through the common
CLI error contract rather than producing a partial result.

The client file format is flat TOML and has exactly these optional keys:

```toml
url = "http://127.0.0.1:8000"
queue = "default"
token = "secret"
```

TOML is used because Python 3.11 reads it through the standard-library `tomllib`;
v2 does not add a YAML/config-framework dependency. Every key, including `url`
and `token`, is optional. An absent effective URL selects the CWD-bound local mode;
an effective URL selects explicitly managed HTTP mode. Omitting `token` means that
the Client sends no Authorization header; this is ordinary for both local mode and
a tokenless loopback HTTP Server. An effective token without an effective URL is
invalid rather than being ignored or sent to the owner-only local socket. A missing
file or omitted key falls through to the next configured source/default. An
unreadable file, invalid TOML, unknown or duplicate key, non-string value, or
present empty string is a `ConfigError`; values are not coerced.

`ConfigError` has exactly two stable codes. `legacy_config_found` is reserved for
the presence guard below. Every other configuration read, TOML parse, unknown or
duplicate key, type, empty-value, URL, Queue or token validation failure uses
`invalid_config`. Its readable message states the problem; `details.source`
identifies `constructor`, `environment` or the config-file path, and
`details.field` is included when one field is responsible. V2 does not create an
exception class or error code for every TOML/parser/field failure.

V2 does not parse or migrate v1 `.labtasker/client.toml`. As a narrow safety guard,
if CWD `.labtasker/config.toml` is absent but CWD `.labtasker/client.toml` exists,
configuration resolution stops with `ConfigError.code == "legacy_config_found"`
before using environment variables or built-in defaults. The error tells the user
to create the new flat file manually, carrying over the URL and Queue name and
adding `token` only when the v2 Server has authentication enabled. This presence-
only check prevents a v1 directory from silently creating and connecting to a new
local Queue `default`; it is not a legacy parser, importer or compatibility layer.

When supplied, `url` must be an absolute `http` or `https` base URL without
userinfo, query or fragment. A trailing slash is removed in the effective value
before appending `/api/v2`; an optional path prefix is otherwise preserved. Unix
socket paths are derived only from CWD and are not encoded into `url` or accepted
through another config key. `queue` follows the Queue/route identifier grammar,
and `token` is an opaque non-empty string of visible ASCII characters (`U+0021`
through `U+007E`) so it can be represented unambiguously in an HTTP Bearer
header. The three matching `LABTASKER_*`
variables use the same validation, including treating a present empty value as
invalid rather than absent.

V2 does not inspect or enforce filesystem permission bits on the client config.
Such checks are inconsistent across POSIX and Windows and do not prevent a token
from being committed to version control. Remote deployments should prefer
`LABTASKER_TOKEN`; regardless of source, token values and Authorization headers
remain prohibited from logs and command output.

### 9.2 Python Client API

The primary Python surface is function-first:

```python
task = labtasker.submit_task(args={"prompt": "cat"})
tasks = labtasker.list_tasks(status="pending")
labtasker.cancel_task(task.id)
```

V2 also exposes `labtasker.Client` for the cases that genuinely need explicit
state: connection pooling across large submission loops, multiple servers, test
isolation and deterministic resource cleanup. It is a synchronous context manager
and has `close()`:

```python
with labtasker.Client(url=..., token=..., queue=...) as client:
    for seed in range(1000):
        client.submit_task(args={"seed": seed})
```

`close()` releases the transport pool and is idempotent. Exiting the context
manager calls it. It does not stop a local daemon, whose lifecycle is shared by
every process using that CWD. Any later operation on that explicit instance fails
locally, before configuration or network access, with exactly
`RuntimeError("Client is closed.")`; a closed Client never reopens itself. The
lazy process-wide default Client has no public close/reset hook and is left to
ordinary process teardown as described below.

Top-level functions are thin facades over one lazily created default Client, not a
second business implementation. Importing `labtasker` does not read configuration,
open a connection, replace process streams, configure logging or install cleanup
hooks. The default Client is initialized on first use and is left to normal
process teardown; long-lived programs that require deterministic cleanup use
explicit `Client`. V2 does not install an `atexit` hook or add an async Client.

The public constructor names are `Client(url=None, token=None, queue=None)`.
`url` deliberately matches `.labtasker/config.toml`, `LABTASKER_URL` and
`config show`; v2 does not expose a competing `base_url`, `socket` or `project`
constructor. For every constructor field, `None` means “not specified here;
continue through the ordinary fallback chain,” including for `token`. For URL,
exhausting that chain selects CWD local mode; it does not select a built-in TCP
address.

Task operations expose `queue: str | None = None`. `None` means "use the next
configured value", never a Queue literally named `None`. Resolution order is:

```text
per-call argument
> explicit Client constructor value
> LABTASKER_URL / LABTASKER_TOKEN / LABTASKER_QUEUE
> current-working-directory .labtasker/config.toml
> built-in defaults
```

The built-ins are CWD local mode, no token and Queue `default`. V2 does not add
profiles, user-level config merging, parent-directory search, VCS-root inference
or automatic multi-file discovery. CLI and Python use this same resolver. An
explicit URL has absolute precedence over local mode; an unavailable HTTP Server
never falls back to or creates a local Server.

Resolution happens once when a `Client` instance is constructed. An explicit
`Client(...)` snapshots its effective endpoint, token, default Queue and, in local
mode, canonical CWD in `__init__`, but performs no connection or startup there.
The process-wide lazy default Client is constructed by the first top-level API
call, so that first call performs the same resolution; importing the package still
does nothing. Later changes to CWD, environment variables or the TOML file do not
silently retarget an existing Client. A per-operation non-null `queue` remains an
explicit override of the snapshotted default. Switching servers or re-reading
configuration uses a newly constructed `Client` (or a new process); v2 adds no
mutable reload/reset API. Each standalone `labtasker config show` invocation
resolves the current sources afresh because it does not reuse a long-lived Client.

Python methods return domain values rather than HTTP response wrappers. A
single-resource operation returns `Task`; paginated listing returns
`TaskPage(items, next_cursor)`; deletion returns `None`. V2 removes v1's `found`,
`content` and message wrappers.

The top-level functions and Client methods use the same resource-qualified names:

```text
submit_task / get_task / list_tasks / count_tasks / update_task / update_tasks
cancel_task / requeue_task / delete_task
create_queue / list_queues / delete_queue
```

V2 provides no shorter `submit`/`cancel` aliases and does not retain v1's `ls`
abbreviation in Python.

These ordinary resource functions are public imports from the package root, both
as `import labtasker; labtasker.submit_task(...)` and as
`from labtasker import submit_task`. The supported package-root import surface and
`labtasker.__all__` are exactly:

```text
Client

submit_task  get_task  list_tasks  count_tasks
update_task  update_tasks  cancel_task  requeue_task  delete_task
create_queue  list_queues  delete_queue

loop  TaskArg  TaskInfo  task_info  finish
cancellation_requested  set_force_stop_timeout

Task  TaskPage  Queue  BulkUpdateResult  LastError
JSONValue  TaskStatus  TaskOrderField  TaskUpdate

LabtaskerError  ConfigError  TransportError  APIError
TransientError  TaskError  FatalWorkerError
```

There are no undocumented compatibility aliases in `__all__`. The Worker wire operations
`claim`, `heartbeat`, `complete`, `fail` and `unclaim` are implementation details
of `loop` rather than public Python convenience functions. Their HTTP contract
remains documented for independent executor implementations; importing a private
client module is not a supported compatibility surface.

`Task` and `TaskPage` are frozen Pydantic models owned by the client package.
Task identity is consistently `task.id`, never `_id` or `task_id`. Top-level
attribute assignment is rejected so local mutation is not mistaken for a server
update; JSON objects in `args`, `metadata` and `result` remain ordinary mutable
dicts rather than introducing deep immutable wrappers. `model_dump(mode="json")`
provides a JSON-ready representation. These response models use `extra="ignore"`
for additive Server compatibility while continuing to require and strictly parse
every known field; Client request and configuration models do not inherit this
leniency.

`list_tasks(limit=100, cursor=None)` fetches exactly one page. V2 does not add an
auto-fetching iterator, streaming list API or implicit "all" mode. Callers follow
`next_cursor` explicitly; server-side batch actions select and process their full
match set independently of Client pagination.

Ordinary Client requests default to a 10-second per-request timeout. The local
daemon's separate 30-second startup wait does not consume or change that request
timeout; the operation timeout begins when its HTTP request is sent. Read-only
GET/list/count operations and Task creation by client-selected-ID `PUT` use at
most three total transport attempts with a short internal exponential backoff.
The same generated Task ID and exact normalized creation request are retained
across submit retries.

For these retry-eligible operations, the Client retries after `TransportError`
or a valid Server `APIError` whose code is exactly `database_busy`. It does not
retry any other valid API error, including authentication, not-found, conflict
and validation errors. A malformed or schema-incompatible response is a
`TransportError` and may therefore consume the same bounded three attempts; it
still surfaces as `transport_error` if none succeeds.

No ordinary lifecycle, update or deletion mutation is automatically retried:
this includes cancel, requeue, Task delete, single/batch update and Queue
create/delete. Their endpoint semantics may still make an explicit repeated call
successful, but a Client transport retry could cross a concurrent state change.
For example, retrying a lost cancel response after another actor requeues the
Task would cancel the newly pending execution; retrying delete after explicit ID
reuse could delete a new Task. Avoiding those rare races with revision tokens,
operation IDs or tombstones would add more machinery than this small-scale tool
needs. An uncertain response therefore raises `TransportError`; callers inspect
the current resource state and explicitly decide what to do. Backoff details for
the permitted read/create retries are implementation constants, not a public
retry-policy object. Worker heartbeat and terminal reporting use a separate
internal reliability policy.

Client-side operational failures use one small hierarchy:

```text
LabtaskerError
├── ConfigError(code, message, details)
├── TransportError(message, details)  # fixed code: transport_error
└── APIError(status_code, code, message, details)
```

Stable server error codes remain data on `APIError`; v2 does not create a Python
exception subclass per HTTP status or domain error code. The Worker outcome
signals `TransientError`, `TaskError` and `FatalWorkerError` are separate and are
not subclasses of these Client-operation errors.

`TransportError` means that the Client did not obtain a usable Labtasker protocol
response. It covers connection failures, local daemon startup/unavailability,
timeouts, invalid HTTP/JSON, a non-error success response that fails the documented
response schema, and an error response that lacks the required API error envelope.
Its stable CLI error code is `transport_error`; structured details may include a
non-sensitive operation, HTTP URL/status or local `state`, `directory`, `database`,
`socket`, `log` path and bounded `retry_after_seconds`, but never credentials or
an unbounded response body. V2 does not add a separate `ProtocolError` or daemon
exception hierarchy. A valid Server error envelope always becomes `APIError`,
including for an HTTP 5xx response.

## 10. Task query and filtering

Task listing and explicit server-side batch actions share one small expression
language. It is a query tool only; it never participates in Worker claim routing.
The public name is `filter` on every surface:

```python
list_tasks(
    queue="default",
    status="pending",
    filter='priority >= 10 and "baseline" in metadata.tags',
    order_by="created_at",
    descending=True,
)
```

```text
labtasker task list --status pending \
  --filter 'priority >= 10 and "baseline" in metadata.tags' \
  --order-by created_at --descending
```

The HTTP query parameter is also named `filter`. Internally an implementation
may call it `filter_expr`, but v2 does not expose competing `where` or `query`
aliases.

The server parses the string with a strict Python-expression AST allowlist; it
never calls `eval`. The initial language contains only:

- fields `id`, `status`, `name`, `priority`, `attempt`, `max_attempts`,
  `last_route`, `created_at`, `updated_at`, `started_at`, `finished_at`, `routes`,
  `args.*`, `metadata.*`, `result.*` and `last_error.*`;
- JSON literals, including `None` for JSON null, and list literals used by
  membership tests;
- comparisons `==`, `!=`, `<`, `<=`, `>` and `>=`;
- Boolean operators `and` and `or`;
- membership operators `in` and `not in`;
- the functions `exists(path)` and `missing(path)`.

The UTF-8 encoding of `filter` is limited to 8192 bytes on every Python, CLI and
HTTP surface, including the filter embedded in a batch-update body. A longer
expression is rejected before AST parsing with `422 filter_too_large` and
`details.max_bytes=8192`. This single public bound also prevents pathological URL
and AST growth; V2 exposes no separate filter-depth, node-count or per-operation
limit knobs.

Each non-membership comparison contains exactly one path and one scalar literal.
V2 rejects path-to-path comparisons, chained comparisons, standalone path
truthiness and array/object equality. For example, callers write
`args.x > 0 and args.x < 1`, not `0 < args.x < 1`.

Membership has exactly two canonical syntactic forms, each containing exactly one
path:

```text
path in [scalar_literal, ...]       # scalar candidate-set membership
scalar_literal in path              # array containment
```

Both forms also support `not in`. The first form declares that the runtime path
value must be scalar; the second declares that it must be an array. List elements
must be scalar JSON literals. All other operand shapes—including path-to-path,
list-on-the-left and constant-only membership—are `invalid_filter` errors. The
language does not guess which containment operation the caller intended.

`in` never means object-key membership. Use `exists(metadata.key)` or
`missing(metadata.key)` explicitly; a statically object-valued expression such as
`"key" in metadata` is `invalid_filter`. For a dynamic path,
`"key" in args.container` still declares array containment: an object-valued row
does not match and is never reinterpreted as a key lookup. If keys that cannot be
represented by the canonical dot-path grammar later become a repeated real need,
they require a separately named explicit operation rather than overloading `in`.

Unsupported names, functions, attribute forms and AST nodes are validation
errors. In particular, v2 does not support the general unary operator `not`.
Callers express negative predicates with `!=` and `not in`, and handle path
absence explicitly with `missing(path)`. This deliberately avoids expressions
such as `not (result.accuracy >= 0.9)` unexpectedly selecting Tasks whose
`result.accuracy` does not exist.

Every ordinary comparison or membership predicate requires each referenced
path to exist. If a referenced path is absent, the predicate does not match,
including `!=` and `not in`. This is a guarded two-valued rule at the public
language level, not SQL `UNKNOWN` and not a user-visible missing value. To
include absent paths, write that choice explicitly:

```text
missing(result.accuracy) or result.accuracy < 0.9
missing(metadata.tags) or "deprecated" not in metadata.tags
```

`exists(path)` is true whenever the path is present, including when its JSON
value is null. `missing(path)` is its exact complement. JSON null remains a real
value distinct from an absent path:

| Path state | `exists(x)` | `missing(x)` | `x == None` | `x != None` | `x == 1` | `x != 1` |
|---|---:|---:|---:|---:|---:|---:|
| absent | false | true | false | false | false | false |
| JSON null | true | false | true | false | false | true |
| number `1` | true | false | false | true | true | false |
| string `"1"` | true | false | false | true | false | true |

Consequently, `x != None` means that `x` is present and non-null, while
`x == 1 or x != 1` matches `exists(x)`, not every Task.

Comparisons use strict JSON types with no implicit coercion. Booleans are
distinct from numbers, strings such as `"1"` are distinct from numbers, and
integer and floating-point spellings share the JSON number domain, so `1` and
`1.0` compare equal. Every numeric literal must satisfy the signed-int64/finite-
binary64 contract in section 2.1. Ordering requires a present value of a compatible type;
missing, null and incompatible values do not match. On dynamic JSON paths,
`<`, `<=`, `>` and `>=` support numbers only; arbitrary string ordering is not
part of the language. The built-in `created_at`, `updated_at`, `started_at` and
`finished_at` timestamp fields accept strictly validated RFC 3339 string
literals. A null nullable field does not match an ordering comparison.

Fixed built-in fields always exist in the Task representation even when their
value is null. Therefore `started_at != None`, `finished_at != None` and
`last_route != None` are the canonical tests for a populated value.
`exists(started_at)` is merely always true and `missing(started_at)` is merely
always false. `exists` and `missing` are useful for dynamic JSON paths that may
actually be absent; they are not aliases for non-null/null tests.

The server validates comparisons against statically typed built-in fields before
query execution. Expressions such as `status == 1`, `priority == "10"` or an
invalid RFC 3339 timestamp are `invalid_filter` errors rather than empty results.
A dynamic JSON path has no declared type, so a row whose present value is
incompatible with an otherwise valid predicate simply does not match.

For membership, a scalar path compared with a list literal must exist and uses
the same strict JSON equality. A scalar literal tested against an array-valued
path requires that path to exist and contain an array. A dynamic path whose
runtime shape violates the shape declared by the syntax does not match either
`in` or `not in`; it is not reinterpreted as another membership operation.
Missing and null likewise do not match. For example,
`"deprecated" not in metadata.tags` excludes Tasks whose `metadata.tags` is
missing, null or non-array.

This language is intentionally not closed under arbitrary Boolean complement
or De Morgan rewrites. General `not` may be added only after repeated real use
cases justify its semantic and implementation cost. V2 also removes raw Mongo
filter dictionaries and does not initially include regex, natural-language date
helpers, arithmetic, arbitrary function calls, wildcards or user-defined
extensions.

The parser, validation layer and backend translator must preserve these rules
independently of storage. The SQLite translator should use JSON type/existence
checks rather than relying on SQL null behavior. Agent-facing help should state
the rule directly: “All comparisons require the referenced path to exist. Use
`missing(path) or ...` to include Tasks where it is absent.” This also makes a
hallucinated path in a negative predicate fail closed with zero matches.

Filters are not accepted by cancel, requeue or delete operations; those actions
remain ID-addressed. Listing, counting and the non-running batch Task update
described below are the only initial filter consumers. V2 does not expose a
generic status or active-run patch through that update surface.

Sorting accepts one built-in scalar Task field through `order_by` plus one
`descending` Boolean. The allowed fields are exactly:

```text
id
name
status
priority
attempt
max_attempts
last_route
created_at
updated_at
started_at
finished_at
```

The exported typing alias `TaskOrderField` is the `Literal` of exactly those
eleven strings; it is not a runtime Enum.

The default is `created_at` descending. Null values sort last in both directions.
Unless `id` is itself selected, the server adds `id` as a deterministic
tie-breaker in the same direction so cursor pages do not overlap or skip equal
sort values. V2 does not support sorting by JSON paths, multiple user-selected
sort fields or a free-form sort expression.

V2 has no stored or virtual `duration` field and does not filter or order by
duration. A caller that needs the latest coarse runtime subtracts non-null
`started_at` and `finished_at` values locally. This keeps heartbeat detection
delay and still-running Tasks from acquiring a deceptively precise server-side
duration meaning.

## 11. Task updates

Status: **Decided**

Task update is an explicit data operation, not a lifecycle transition. The server
rejects an update only while the Task is `running`, because changing data being
consumed by an active run would violate execution consistency. Pending,
succeeded, failed and cancelled Tasks may be updated. The server does not prohibit
a clear, local update merely to protect the user from intentionally changing an
old record.

The writable user-owned fields are exactly:

```text
name
args
metadata
priority
max_attempts
routes
result
```

The Python client describes this JSON shape with an exported typing-only
`TypedDict`; callers pass an ordinary dict and do not instantiate a request
model:

```python
class TaskUpdate(TypedDict, total=False):
    name: str | None
    args: dict[str, JSONValue]
    metadata: dict[str, JSONValue]
    priority: int
    max_attempts: int
    routes: list[str]
    result: dict[str, JSONValue]
```

The following classes of fields are server-owned and not writable:

- resource identity: `id`, `queue`, `created_at`;
- lifecycle and retry accounting: `status`, `attempt`, `last_error`;
- execution ownership: active `run_id` and lease expiry, plus the server-owned
  latest-run summary (`last_route`, `started_at`, `finished_at`);
- terminal deduplication fields; and
- `updated_at`, which the server refreshes after every effective update.

This boundary protects resource identity, lifecycle transitions, retry accounting
and concurrency fencing; it does not attempt to keep non-running historical data
immutable. Cancel, requeue, complete, fail and unclaim retain their explicit
action endpoints. `last_error` remains the server-generated diagnostic record;
`result` is user data and may be explicitly replaced while no run is active.

Every supplied object or list field is a complete replacement. There is no
implicit shallow/deep merge, `replace_fields`, add/remove operator or dot-path
patch language. Unspecified fields remain unchanged. This makes both setting and
deleting nested values unambiguous:

```python
task = get_task(task_id)
args = dict(task.args)
args["steps"] = 40
args.pop("obsolete", None)
updated = update_task(task_id, {"args": args})
```

The function-first and `Client` APIs use the same signatures:

```text
update_task(
    task_id: str,
    changes: TaskUpdate,
    *,
    queue: str | None = None,
) -> Task

update_tasks(
    *,
    filter: str,
    changes: TaskUpdate,
    queue: str | None = None,
) -> BulkUpdateResult
```

`update_task` is ID-addressed. It returns the updated `Task`, returns
`404 task_not_found` for an unknown ID, or returns `409 task_running` if a run
became active before the conditional update committed.

`changes` must contain at least one field. Unknown fields, server-owned fields,
wrong JSON types and an empty object are `422 invalid_update`; they are never
ignored. `name` alone may be JSON null. `args`, `metadata` and `result` must be
JSON objects; `routes` must be a non-empty array of strings; `priority` and
`max_attempts` must be integers, with booleans rejected as integers.
Non-null `name` follows the same 256-code-point rule as submission.
An otherwise valid change whose complete resulting user-owned Task data exceeds
1 MiB is `422 task_data_too_large` under section 6.2.

`max_attempts` must always be a positive integer. For a pending Task it must also
be greater than the current `attempt`; otherwise the request is rejected as
invalid rather than creating a pending Task with no remaining execution budget or
silently changing its status. A non-pending Task may store any positive value;
manual requeue resets `attempt` to zero under the lifecycle rules.

`update_tasks(filter=..., ...)` performs one server-side bulk update and requires
a non-empty `filter`; omitting it is a validation error. A caller intentionally
updating every non-running Task writes an explicit filter such as
`status != "running"`. The server atomically applies the update only to rows that
both match the filter and remain non-running. A concurrent claim either observes
the new values or wins first and excludes that Task from the update.

Bulk update returns `BulkUpdateResult(matched, updated)`. `matched` counts rows
that satisfied both the caller's filter and `status != running` at execution time;
`updated` counts those whose stored value actually changed. Running rows are not
included in either count. The operation does not fail merely because a matching
Task became running concurrently.

All non-running matched rows are validated before any value is written. If even
one would violate a state-dependent invariant such as pending
`max_attempts > attempt`, the entire batch rolls back with `409 update_conflict`;
the error details identify at least one conflicting Task and field. The server
does not silently skip invalid non-running rows. Concurrently running rows are the
only exclusion because they lost the update-versus-claim race rather than failing
request validation.

Concurrent ordinary updates use last-write-wins. The 2.0.0 initial release has no revision field,
ETag, `If-Match` or compare-and-swap option. Because object/list fields are full
replacements, a caller doing read-modify-write accepts that a later concurrent
update may replace its value. Update calls are not automatically retried by the
Client.

### 11.1 HTTP

Single-resource update uses standard `PATCH` with the `TaskUpdate` JSON object as
the body:

```http
PATCH /api/v2/queues/{queue}/tasks/{task_id}
Content-Type: application/json

{"args":{"prompt":"cat","steps":40}}
```

Success returns `200` with the updated Task. Collection `PATCH` performs filtered
batch update:

```http
PATCH /api/v2/queues/{queue}/tasks
Content-Type: application/json

{
  "filter": "status == \"failed\"",
  "changes": {"routes": ["sdxl-v2"]}
}
```

Success returns `200` with `{"matched": N, "updated": M}`. A missing or empty
batch filter is `422 invalid_filter`; there is no implicit update-all request.

### 11.2 CLI

The CLI accepts the same strict JSON object through one `--changes` option. It
does not retain v1's repeated `-u field=value`, per-field update flags,
`replace_fields` or dot-path patch syntax:

```text
labtasker task update t_123 \
  --changes '{"priority":10,"routes":["sdxl-v2"]}'

labtasker task update \
  --filter 'status == "failed"' \
  --changes '{"routes":["sdxl-v2"]}'
```

Exactly one selection form is required: a positional Task ID for single update,
or `--filter` for batch update. Supplying both or neither is a CLI usage error.
Success writes the same Task or `BulkUpdateResult` JSON used by the Python API;
diagnostics and structured API errors follow the common CLI rules.

## 12. Task submission

Status: **Decided**

Submission creates one complete Task definition. All surfaces share these fields
and defaults:

```text
name          null
args          {}
metadata      {}
priority      0
max_attempts  3
routes        ["default"]
```

`result` starts as `{}`, `attempt` starts as `0`, status starts as `pending`, and
all identity, lifecycle, diagnostic and execution fields are server-owned rather
than creation inputs.

### 12.1 Python

The function-first and `Client` APIs use the same signature:

```text
submit_task(
    args: dict[str, JSONValue] | None = None,
    *,
    name: str | None = None,
    metadata: dict[str, JSONValue] | None = None,
    priority: int = 0,
    max_attempts: int = 3,
    routes: list[str] | None = None,
    task_id: str | None = None,
    queue: str | None = None,
) -> Task
```

Python `None` for `args`, `metadata` or `routes` means “use the documented
default”; the Client sends the normalized object rather than JSON null. Callers
may therefore submit a no-argument Task with `submit_task()`.

`name` is either null or a Unicode string of at most 256 Unicode code points;
empty string is valid and distinct from null in the stored Task even though both
use the journal slug fallback `unnamed`. V2 performs no Unicode normalization.
No code point whose Unicode general category is `Cc` is allowed, including NUL,
newline, carriage return and Tab; other normal Unicode remains valid. Submission
or update of a longer name or one containing `Cc` returns
`422 invalid_task_name`. This restriction applies only to the display name, not
to string values inside args, metadata or result. The name is a human label, not
identity; the opaque Task ID remains authoritative.

`routes` accepts only `list[str]`; a bare string, tuple, set or arbitrary iterable
is rejected rather than coerced. The list must be non-empty, every route must be a
non-empty exact string, and duplicates are invalid. Route order has no semantics:
the server stores and returns the unique list in lexicographic order.

When `task_id` is omitted, the Client generates it once before the first network
attempt and reuses it for transport retries. An explicit ID must match:

```text
^t_[A-Za-z0-9_-]{12}$
```

Human-readable identity belongs in `name`; Task IDs remain opaque. Invalid IDs
are `422 invalid_task_id`.

### 12.2 HTTP and idempotent creation

Creation uses the client-selected ID in the resource path:

```http
PUT /api/v2/queues/{queue}/tasks/{task_id}
Content-Type: application/json

{
  "name": null,
  "args": {},
  "metadata": {},
  "priority": 0,
  "max_attempts": 3,
  "routes": ["default"]
}
```

Every body field is optional. The server expands omitted fields to the defaults
above before validation and creation-hash calculation. Explicit JSON null is
valid only for `name`; `args`, `metadata` and `routes` must be their declared JSON
types when present. Unknown fields and server-owned fields such as `result`,
`status` or `attempt` are `422 invalid_task`; they are never ignored.

`args` and `metadata` must be JSON objects, `priority` must be an integer,
`max_attempts` must be a positive integer, and booleans are not accepted as
integers. Routes use the validation and canonical ordering above. The normalized
creation hash ignores JSON object key order, route input order and the difference
between an omitted default and the same default written explicitly.
Normalized creation data exceeding the complete 1 MiB stored-Task bound is
`422 task_data_too_large`.

Initial creation returns `201` with the created Task. An identical normalized
request at the same ID returns `200` with the Task's current representation. A
different normalized creation request at that ID returns `409 task_id_conflict`
and never acts as update. An unknown Queue returns `404 queue_not_found` and is
not created implicitly.

### 12.3 CLI

CLI submit exposes only typed top-level flags plus strict JSON objects:

```text
labtasker task submit \
  --id t_AbCdEf0123-_ \
  --name baseline \
  --args '{"prompt":"cat","steps":30}' \
  --metadata '{"group":"ablation"}' \
  --priority 10 \
  --max-attempts 3 \
  --route sdxl \
  --route sdxl-v2
```

`--args` and `--metadata` accept strict JSON objects only; the CLI does not infer
types through `literal_eval` or trailing `--key=value` arguments. `--route` is
repeatable and the collected list follows the same non-empty/duplicate rules.
All flags are optional and use the canonical defaults; omitted `--id` is generated
by the Client. Success writes exactly one Task JSON object to stdout. Handled
errors write the common error envelope to stdout with exit `1`; diagnostics go
to stderr.

## 13. Task representation and retrieval

Status: **Decided**

The public Task representation in 2.0.0 contains exactly:

```text
id
queue
status
name
args
metadata
priority
attempt
max_attempts
routes
result
last_error
last_route
created_at
updated_at
started_at
finished_at
```

This is the complete initial model, not a prompt for implementations to invent
additional fields. A later additive `/api/v2` Server release may append optional
response fields under section 6.2; older clients ignore them, and they become
public only when that later contract documents them.

Including `queue` makes a returned Task self-locating for later resource API
calls. Active `run_id`, lease expiry, terminal-deduplication state,
`creation_hash`, `pending_at_us` and other database-only fields are never exposed in
ordinary Task get/list responses. `last_route` is observability data: it records
the route used by the most recently claimed run, rather than participating in
future eligibility.

The client uses strings rather than an Enum for status:

```python
TaskStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
]
```

All public timestamps are timezone-aware Python `datetime` values and UTC RFC
3339 strings on the wire. `last_error` uses the frozen client-owned `LastError`
Pydantic model. `routes` remains `list[str]`; `args`, `metadata` and `result` remain ordinary
dicts. `Task` itself is a frozen client-owned Pydantic model, but mutating one of
its contained list/dict objects is only local and never updates the server.

Retrieval is canonical and ID-addressed:

```text
get_task(task_id: str, *, queue: str | None = None) -> Task
```

```http
GET /api/v2/queues/{queue}/tasks/{task_id}
```

```text
labtasker task get t_...
```

Success returns one Task; an unknown ID returns `404 task_not_found`. CLI success
writes exactly that Task JSON object to stdout. Get/list never reveal active run
or lease data.

Listing uses the same selection and ordering contract on every surface:

```text
list_tasks(
    *,
    status: TaskStatus | None = None,
    name: str | None = None,
    filter: str | None = None,
    order_by: TaskOrderField = "created_at",
    descending: bool = True,
    limit: int = 100,
    cursor: str | None = None,
    queue: str | None = None,
) -> TaskPage
```

`status`, `name` and `filter` are optional and are ANDed when combined. `name`
means exact string equality. Listing has no `task_id` shortcut because
`get_task()` is the canonical ID lookup. `TaskPage` is a frozen client-owned
Pydantic model containing `items: list[Task]` and `next_cursor: str | None`.

HTTP uses:

```http
GET /api/v2/queues/{queue}/tasks?status=...&name=...&filter=...&order_by=created_at&descending=true&limit=100&cursor=...
```

The CLI mirrors those names:

```text
labtasker task list \
  --status succeeded \
  --name baseline \
  --filter 'result.acc >= 0.9' \
  --order-by finished_at \
  --descending \
  --limit 100 \
  --cursor '...'
```

`--descending` and `--ascending` are mutually exclusive; descending is the
default. CLI success writes the complete `TaskPage` as indented standard JSON.
There is no table, pager, TTY-dependent output, `--ids-only` schema or implicit
request for every page. An empty page is a successful result:

```json
{
  "items": [],
  "next_cursor": null
}
```

Counting is a separate, deliberately small operation because backlog size is a
useful experiment/Agent diagnostic and fetching every page merely to count rows
is wasteful:

```text
count_tasks(
    *,
    status: TaskStatus | None = None,
    name: str | None = None,
    filter: str | None = None,
    queue: str | None = None,
) -> int
```

It uses exactly the same `status`, exact `name`, and `filter` selection semantics
as `list_tasks`, with supplied predicates ANDed. It has no `order_by`, direction,
limit, cursor, grouping or per-route aggregation. HTTP uses:

```http
GET /api/v2/queues/{queue}/tasks/count?status=...&name=...&filter=...
```

and returns one strict object:

```json
{"count": 123}
```

The Python method unwraps that object to an ordinary non-negative `int`. The CLI
mirrors the three selectors and Queue:

```text
labtasker task count --status pending --filter 'priority >= 10' --queue experiments
```

and writes the same formatted `{"count": ...}` JSON object. `TaskPage` does not
gain a `total` field: listing remains one selection/ordering query, and callers
pay for a full count only when they explicitly request it. A count is a snapshot
of the database transaction serving that request; concurrent mutations may make
a subsequent list differ normally.

`limit` is an integer from 1 through 1000. The default is 100. `cursor` is an
opaque, stateless continuation token. It carries the last ordering position and
a summary of the effective Queue, selection and ordering inputs. It may be reused
with a different `limit`, but all other selection and ordering inputs must be
identical to the request that produced it. A malformed cursor or a mismatch
returns `422 invalid_cursor`; the server never silently restarts or reinterprets
pagination. The token is not a credential and creates no server-side pagination
session.

Pagination is ordinary stateless keyset pagination, not a database snapshot.
Each page is internally consistent at the time of its own query. With no
concurrent mutations, the documented ordering and ID tie-breaker prevent overlap
or omission across pages. Concurrent create, update, lifecycle or delete actions
may move rows across the cursor boundary, so a multi-page traversal may observe
or miss those changes. V2 adds no snapshot ID, pagination transaction or
server-side cursor session; callers needing a later stable experiment record use
the returned Task data or an external snapshot/export workflow.

`last_route`, `started_at` and `finished_at` form one latest-run summary. Their
transitions are deliberately small and overwrite history rather than creating a
Run resource:

- A newly created Task has all three fields set to null.
- A successful claim atomically sets `last_route` to the claim route and
  `started_at` to the claim time, and clears `finished_at`.
- Complete, fail, unclaim, heartbeat-expiry recovery and cancellation of a running
  Task set `finished_at` to the time of that server transition. A retryable failure
  or unclaim may therefore leave a pending Task with a complete non-null pair.
- Cancelling a pending Task does not alter the summary; a never-run Task retains
  null values. Manual requeue and ordinary Task update also preserve it.
- The next successful claim replaces the previous summary. No earlier run history
  is retained in 2.0.0 initial release.

When both timestamps are non-null, `finished_at - started_at` is the coarse
server-observed duration of that most recent run. For heartbeat expiry it extends
through failure detection, and for cancellation it ends at logical cancellation;
neither claims to measure the exact lifetime of remote user code. Because routes
can later be edited while a Task is not running, historical `last_route` need not
belong to the Task's current `routes` set.

`created_at` never changes. `updated_at` changes after claim, complete, fail,
unclaim, heartbeat-expiry recovery, cancel, requeue and any effective ordinary
Task update. An ordinary heartbeat only renews the private lease and does not
change `updated_at`; otherwise routine heartbeat traffic would make Task ordering
and change inspection noisy.

## Decision log

| Date | Decision |
|---|---|
| 2026-08-28 | Make stdout the single machine-readable response channel for finite Client commands: successful data or a handled `LabtaskerError` envelope is written there, diagnostics remain on stderr, and exit status distinguishes success from failure. Keep usage errors and continuing `loop` failures as natural-language stderr, with no output-mode flag or response wrapper. |
| 2026-08-24 | Standardize finite diagnostics as `[labtasker]` or `[labtasker-server]`, emit one explicit successful Client connection line with local/remote Server kind and Unix/HTTP(S) transport, and give default long-running Worker and Server logs millisecond UTC timestamps, levels and component prefixes. |
| 2026-08-21 | Make CWD-bound local mode the default endpoint when no URL is configured: store the durable SQLite database under that exact canonical CWD, derive an owner-only tmux-style `/tmp/labtasker-UID` Unix socket without parent/VCS discovery, and let every explicit HTTP URL disable all local process management. |
| 2026-08-21 | Make local endpoint selection and daemon transitions unconditionally visible on stderr for CLI and direct Python use, while preserving requested data on stdout and never printing credentials. |
| 2026-08-21 | Use the actual database inode's inherited ownership FD as both local startup election and lifetime ownership, with no separate startup lock or readiness pipe; poll socket health for at most 30 seconds and never break or automatically kill a live owner. |
| 2026-08-21 | Reuse ephemeral per-CWD runtime metadata for a fixed one-automatic-launch-per-10-seconds throttle; add no durable startup-state file, failure counter, exponential backoff, probation/stability phases or delayed reset task. |
| 2026-08-21 | Detach the local daemon from its launching terminal and SSH connection, give it no idle shutdown, and stop it only explicitly or through ordinary process/machine failure; expose CWD-addressed `start`, `status`, `stop [--force]` and `logs` commands, make stop one-shot, and keep explicit HTTP `serve` foreground and user-managed. |
| 2026-08-21 | Permit automatic recovery only for the default Unix-socket transport and preserve every operation's existing uncertain-outcome/retry rules; an explicit HTTP URL never causes Client-owned Server startup, restart or shutdown. |
| 2026-08-21 | Publish `labtasker` as the full-install metapackage over independent `labtasker-client` and `labtasker-server` runtime distributions; use direct `labtasker-client` installation for the slim/remote case because extras cannot subtract default dependencies. |
| 2026-08-21 | Reject the Command Worker with built-in `NotImplementedError` on Windows before Client construction because the current executor cannot uphold whole-process-group cancellation; keep the CLI diagnostic readable without adding a public platform-error type, retain Client, Server and Python Worker as Windows best effort, and retain Command Worker as macOS best effort. |
| 2026-08-21 | Distinguish best-effort platforms from explicitly unsupported platform features: allow the former to run, but reject the latter deterministically before network, claim, journal, database or process side effects, while permitting documented behavior-preserving fallbacks such as noninteractive POSIX pipe mode. |
| 2026-08-21 | Protect local state by exclusively creating `.labtasker/.gitignore` with `*` and `!.gitignore` from both the default Server storage path and Worker journal setup; preserve any existing entry and do not modify custom database parents outside `.labtasker`. |
| 2026-08-21 | Restore one canonical v2 Labtasker Agent Skill with both Claude Code marketplace and open `npx skills add` installation paths; use a repository-local symlink rather than maintaining a third copy. |
| 2026-08-20 | Make this file the authoritative standalone user-visible contract: a reader with no chat history must be able to implement every Decided section; companion plan/comparison files cannot supply missing semantics. |
| 2026-08-20 | Name the task-selection expression `filter` consistently in Python, CLI and HTTP; add no public `where` or `query` aliases. |
| 2026-08-20 | Keep a strict Python-AST filter subset with comparisons, guarded membership, `and`/`or`, and `exists`/`missing`; omit unary `not`, raw Mongo filters and regex/date/arithmetic/extensions. |
| 2026-08-20 | Require referenced paths to exist for every ordinary predicate, including `!=` and `not in`; distinguish absent paths from explicit JSON null and use strict JSON types without coercion. |
| 2026-08-20 | Bound every recursive JSON number and filter literal to signed int64 or finite binary64, rejecting NaN, infinities and overflow while keeping bool distinct from number. |
| 2026-08-20 | Bound args, metadata and result to recursively defined container depth 64 and return `json_too_deep` beyond it; add no per-field depth configuration. |
| 2026-08-20 | Restrict comparisons to one path and one scalar literal; reject path-to-path, chained and structured-value comparisons. |
| 2026-08-20 | Reject ambiguous convenience forms when an explicit canonical spelling exists; do not guess intent through coercion, aliases or context-dependent merge semantics. |
| 2026-08-20 | Restrict membership to `path in [scalar literals]` and `scalar literal in array_path` (plus guarded `not in`); reject every other operand shape. |
| 2026-08-20 | Reserve `in` for scalar candidate sets and array containment; require `exists(path)`/`missing(path)` for object-key presence and never infer membership meaning from a row's runtime container type. |
| 2026-08-20 | Treat route changes as ordinary Task updates with exact full-set replacement; allow updates in every state except running and provide no route add/remove/merge actions. |
| 2026-08-20 | Restrict dynamic JSON ordering to numbers and validate built-in timestamp comparisons as RFC 3339; reject statically invalid built-in-field comparisons. |
| 2026-08-20 | Keep cancel, requeue and delete ID-addressed; only listing, counting and non-running Task update consume filters initially. Require a filter for batch update. |
| 2026-08-20 | Add an explicit `count_tasks`/`task count`/HTTP count vertical slice using the list selectors, while keeping `TaskPage` free of an implicit total and adding no grouping. |
| 2026-08-20 | Fix the package-root `__all__` to the explicitly listed ordinary APIs, models, types, Worker helpers and exceptions; keep claim/heartbeat/terminal Worker transport calls out of the public Python API. |
| 2026-08-20 | Name the explicit Client constructor `Client(url=None, token=None, queue=None)` so connection vocabulary matches config/env; add no `base_url` alias. |
| 2026-08-20 | Let `None` on every Client constructor field, including token, continue through env/CWD config/built-in fallbacks; snapshot resolution at Client construction and never hot-reload it. |
| 2026-08-20 | Construct the lazy default Client on the first top-level API call, not import; later environment/CWD/config changes do not retarget it, and switching configuration uses a new Client/process. |
| 2026-08-20 | Name the frozen `Task.last_error` model `LastError`, keeping it distinct from the Worker outcome exception `TaskError`. |
| 2026-08-20 | Make the documented 2.0.0 Task fields exact while permitting only later documented optional response additions under the `/api/v2` compatibility rule. |
| 2026-08-20 | Enforce one 1 MiB HTTP request-body limit with `413 request_too_large`; add no per-field size limit or artifact-upload behavior. |
| 2026-08-20 | Apply the same 1 MiB bound to complete canonical user-owned Task data after create, update or complete; reject an oversize resulting record with `task_data_too_large` so multiple patches cannot store large files indirectly. |
| 2026-08-20 | If an official fail diagnostic would exceed the request limit, preserve the original exception type but replace message/traceback with one fixed pointer to local run.log rather than stranding the run or adding truncation controls. |
| 2026-08-20 | Do not enforce client-config filesystem permission bits; keep token optional, recommend environment configuration remotely, and prohibit credential logging. |
| 2026-08-20 | Let cancel move pending/running to cancelled, fence a running run and be idempotent on cancelled; preserve attempt, diagnostics and result. |
| 2026-08-20 | Let explicit requeue accept pending/failed/cancelled, reset attempt and last error, refresh pending order, and preserve user data plus the latest-run summary; running and succeeded reject it. |
| 2026-08-20 | Allow idempotent Task deletion in every non-running state, returning HTTP 204/Python None/empty CLI stdout; require explicit cancellation before deleting a running Task. |
| 2026-08-20 | Use complete replacement for every supplied Task object/list field; provide no implicit merge, `replace_fields` switch or dot-path patch language. |
| 2026-08-20 | Return the updated Task from `update_task`; return matched/updated counts from filtered `update_tasks`, excluding running Tasks atomically rather than failing the batch. |
| 2026-08-20 | Allow ordinary update of `name`, `args`, `metadata`, `priority`, `max_attempts`, `routes` and `result` in every state except running; keep identity, lifecycle, retry-diagnostic and run-fencing fields server-owned. |
| 2026-08-20 | Require a pending Task's updated `max_attempts` to remain greater than `attempt`; reject an exhausted pending budget rather than applying an implicit state transition. |
| 2026-08-20 | Represent updates as one strict `TaskUpdate` TypedDict/plain JSON changes object across Python, HTTP and CLI; distinguish omitted fields from explicit `name: null` without a request model or public sentinel. |
| 2026-08-20 | Use `PATCH` on a Task for one update and collection `PATCH` with `filter + changes` for batch update; use CLI `--changes` JSON and delete v1 field-expression update syntax. |
| 2026-08-20 | Validate a filtered batch atomically and roll it back if any non-running matched Task violates an invariant; only Tasks that concurrently become running are excluded. |
| 2026-08-20 | Use last-write-wins for concurrent ordinary updates in 2.0.0 initial release; add no revision/ETag precondition and do not automatically retry update calls. |
| 2026-08-20 | Give Python `submit_task` defaults of empty args/metadata, priority zero, three attempts, route `default`, no name and a client-generated ID; allow `submit_task()` for a no-argument Task. |
| 2026-08-20 | Accept Task routes only as a non-empty duplicate-free string list and store/return it lexicographically; do not coerce strings, sets, tuples or arbitrary iterables. |
| 2026-08-20 | Require explicit Task IDs to use the same opaque `t_` plus 12 URL-safe character format as generated IDs; keep human-readable identity in `name`. |
| 2026-08-20 | Normalize omitted creation defaults, JSON object key order and route order before creation hashing; reject unknown/server-owned creation fields. |
| 2026-08-20 | Keep CLI submit field-oriented but strict: JSON-only `--args`/`--metadata`, repeatable `--route`, optional `--id`, scalar flags and exactly one Task JSON result. |
| 2026-08-20 | Include `queue` and a public latest-run summary (`last_route`, `started_at`, `finished_at`) while keeping active run/lease and internal database fields private; each claim replaces the summary and each run-ending transition finishes it. |
| 2026-08-20 | Refresh `updated_at` for lifecycle transitions, requeue and effective ordinary updates, but not for routine heartbeat lease renewal. |
| 2026-08-20 | Represent Task status as a string `Literal`, timestamps as timezone-aware datetime/RFC 3339, `last_error` as a frozen model, routes as a list and JSON fields as ordinary dicts. |
| 2026-08-20 | Use canonical ID-addressed `get_task`, Task HTTP GET and `task get`; return one Task or `404 task_not_found` without active run data. |
| 2026-08-20 | Define keyword-only `list_tasks` with exact `status`/`name` shortcuts ANDed with `filter`, one-page `TaskPage` results and no redundant Task-ID list selector. |
| 2026-08-20 | Bound list pages to 1–1000 Tasks with default 100; use a stateless opaque cursor tied to the Queue, selection and ordering inputs while allowing the next page size to change. |
| 2026-08-20 | Make CLI data output two-space-indented UTF-8 JSON with no ANSI styling; `task list` always returns the `TaskPage` schema and has no table, pager or IDs-only output mode. |
| 2026-08-20 | Make `last_route`, `started_at` and `finished_at` filterable; fixed nullable built-ins always exist, so test population with `field != None` rather than `exists(field)`. |
| 2026-08-20 | Support one explicitly allowlisted built-in scalar `order_by` field plus `descending`, sort nulls last, default to `created_at` descending, and add `id` as the stable cursor tie-breaker; omit JSON and multi-field sorting. |
| 2026-08-20 | Add no stored or virtual duration field, filter or ordering; callers derive the coarse latest-run duration from a non-null timestamp pair. |
| 2026-08-20 | Use the same resource-qualified Python names on top-level functions and Client methods; keep `submit_task`/`list_tasks` etc. and add no short aliases. |
| 2026-08-20 | Return client-owned frozen Pydantic `Task`/`TaskPage` models with `task.id`; keep nested JSON dicts ordinary and provide `model_dump(mode="json")`. |
| 2026-08-20 | Fetch exactly one explicit cursor page from `list_tasks`; add no auto iterator, stream or implicit-all mode, and keep server-side batch selection independent of pagination. |
| 2026-08-20 | Resolve `queue=None` through per-call, Client, environment, current-project config and finally `default`; treat Queue as a configurable default rather than auth identity. |
| 2026-08-20 | Use only `LABTASKER_URL`, `LABTASKER_TOKEN` and `LABTASKER_QUEUE` as user-facing Client configuration variables; read only CWD `.labtasker/config.toml`, with no profiles, parent search, user config or multi-file merge. The 2026-08-21 local endpoint adds reserved Worker execution-context variables, not new user configuration sources. |
| 2026-08-20 | Restrict the client CLI tree to full-name Task/Queue actions, `loop` and read-only `config show`; keep `labtasker-server serve` separate and add no aliases, Worker/Event/Admin commands or config mutation commands. Superseded on 2026-08-21 only for the Server executable's local-daemon management commands. |
| 2026-08-20 | Put `--queue` only on each relevant Task leaf command and `loop`; add no global option placement or CLI URL/token flags, using environment variables for one-off connection overrides. |
| 2026-08-20 | Give Queue only a public `name`; expose create/list/delete without item get or pagination, and return one object, an array and no content respectively. |
| 2026-08-20 | Make `config show` a network-free JSON diagnostic containing effective URL, Queue and only a boolean for token presence; never print the token. Superseded on 2026-08-21 by the discriminated local/HTTP endpoint diagnostic, while retaining network-free behavior and token secrecy. |
| 2026-08-20 | Publish independent `labtasker` and `labtasker-server` distributions at synchronized versions without a shared core package; support only `/api/v2` with no v1 fallback, adapter or startup data import. Superseded on 2026-08-21 by independent Client/Server runtime distributions plus the full-install metapackage. |
| 2026-08-20 | Release both first v2 distributions as package version 2.0.0 and call the milestone the initial release rather than package 0.1.0. Superseded on 2026-08-21 to cover all three synchronized distributions. |
| 2026-08-20 | Make Linux the fully release-gated 2.0.0 platform; initially keep ordinary macOS/Windows Client, Server and pipe Worker behavior best effort without requiring ConPTY, launcher or process-tree parity. Superseded on 2026-08-21 for Windows Command Workers. |
| 2026-08-20 | Gate releases on unit, real SQLite, API/OpenAPI, e2e, deterministic races, schema upgrades, fake launcher, real Linux torchrun/Accelerate and prior-v2-Client contract tests, but no coverage target, probabilistic stress or full cross-platform matrix. |
| 2026-08-20 | Keep finite CLI data commands on formatted JSON stdout, but use ordinary human-readable Python logging for `loop` and Server operations; add no JSONL or log-format switch. |
| 2026-08-20 | Prohibit tokens and Authorization headers from logs while allowing all other diagnostic fields when useful, without a mandatory per-field redaction framework or routine large-payload dumping. |
| 2026-08-20 | Fix CLI-owned Worker and Server logging at INFO with no verbosity/log-level flags; log transient, task and fatal outcomes at WARNING/ERROR/CRITICAL respectively, omitting only the transient traceback by default and never duplicating full command output. |
| 2026-08-20 | Preserve Python Worker terminal-and-run-file tee only during an actual Worker invocation: use one locked process-level active destination, restore streams afterward, disable it after fork, preserve ANSI, and leave native fd/child capture to their own mechanisms; perform no stream or logging mutation at import. |
| 2026-08-20 | Respect existing `labtasker` logging configuration at Worker startup and otherwise install only a named INFO stderr fallback handler; never configure root logging or remove user/Loguru handlers. |
| 2026-08-20 | Define `.labtasker/config.toml` as a flat strict three-string TOML file (`url`, `queue`, `token`) read by stdlib `tomllib`; reject unknown/duplicate/empty/ill-typed values and add no YAML/config framework. |
| 2026-08-20 | Make every client config key optional, including `token`; an omitted token sends no Authorization header, while a present empty token remains invalid. |
| 2026-08-20 | If the new CWD config is absent but v1 `.labtasker/client.toml` exists, fail with `legacy_config_found` before all other resolution; do not parse or migrate the legacy file. |
| 2026-08-20 | Give Queue and route one case-preserving, case-sensitive 1–128 character ASCII identifier grammar, `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`, with no normalization. |
| 2026-08-20 | Limit `labtasker-server serve` to host, port and SQLite path flags with defaults `127.0.0.1:8000` and `.labtasker/server.db`; read the token only from `LABTASKER_SERVER_TOKEN` and leave process supervision external. Superseded on 2026-08-21 only for the new CWD local daemon; explicit HTTP `serve` retains this user-owned foreground contract. |
| 2026-08-20 | Automatically initialize or forward-migrate known v2 Alembic revisions before listening; reject newer/unknown/failed schemas, add no migration CLI or automatic backup, and do not treat v1 MongoDB as an implicit startup migration. |
| 2026-08-20 | Fix SQLite to WAL, foreign keys, 5000 ms busy timeout and FULL synchronous durability; apply per-connection settings and fail startup if required values cannot be verified. |
| 2026-08-20 | Leave running Tasks unchanged on Server shutdown; before listening after restart, recover already expired leases through the ordinary heartbeat-loss transition while preserving non-expired leases without a special grace state. |
| 2026-08-20 | Expose unauthenticated exact-shape `/health` with a real DB check and `/openapi.json`; add no capabilities list and disable FastAPI Swagger/ReDoc pages while keeping every `/api/v2` endpoint authenticated. |
| 2026-08-20 | Permit only additive endpoints, optional response fields and error codes within `/api/v2`; require a new API prefix for removed/renamed/retyped/redefined fields or Task states, independent of package version. |
| 2026-08-20 | Reject unknown request fields but let Client response models ignore unknown additive fields while still requiring strict known fields; perform no routine health preflight or capability/version-range negotiation. Superseded on 2026-08-21 only to permit local daemon health discovery; explicit HTTP and capability negotiation remain unchanged. |
| 2026-08-20 | Treat live `/openapi.json` as the sole generated schema, ship no generated SDK/shared wire package, and test each new Server against both the current real Client and the previous released v2 Client's core workflow. |
| 2026-08-20 | Scope Task identity to `(queue_name, task_id)` while enforcing a global partial uniqueness constraint on non-null active run IDs; allow the same explicit Task ID in different Queues. |
| 2026-08-20 | Store args/metadata/result as compact canonical JSON text with valid-object checks and query through SQLite JSON1; do not adopt SQLite JSONB or make object-key order contractual. |
| 2026-08-20 | Standardize Server persistence on synchronous SQLAlchemy 2.x plus Alembic: private ORM for CRUD, Core/explicit SQL for atomic claim and filter expressions, one transaction per command, and no async/repository/SQLModel layer. |
| 2026-08-20 | Store public Task routes in a private indexed `task_routes` value-association table with composite FK/cascade, full-set transactional replacement and batched loading; do not create a Route registry or scan JSON arrays during claim. |
| 2026-08-20 | Store database times as Server-generated UTC Unix microseconds in SQLite INTEGER columns and convert only at HTTP/Python boundaries; organize Task persistence as one private lifecycle row plus the separate routes association, without treating the ORM row as the public model. |
| 2026-08-20 | Order eligible Tasks by priority descending, private pending-entry time ascending and Task ID ascending; refresh `pending_at_us` whenever a Task enters or is explicitly requeued within pending, including TransientError, but not on ordinary updates, and add no Queue ticket counter. |
| 2026-08-20 | Create only hot-path claim, expiry, default/status list, active-run, terminal-run and route indexes; leave name, JSON-path and uncommon-sort indexes to measured query plans. |
| 2026-08-20 | Start every mutating service command with SQLite `BEGIN IMMEDIATE`; after the fixed five-second busy wait, return retryable `503 database_busy` rather than hiding indefinite Server retries. |
| 2026-08-20 | Require real-SQLite independent-connection race tests for claim, claim replay, route conflict, completion versus expiry, old terminal retry versus new run, update versus claim, and cancel versus complete. |
| 2026-08-20 | Return `Task` for single-resource operations, `TaskPage(items,next_cursor)` for listing, `int` for counting and `None` for deletion; remove HTTP-style response wrappers. |
| 2026-08-20 | Keep Client-operation exceptions to `ConfigError`, `TransportError` and structured `APIError` under `LabtaskerError`; do not subclass every status/code or mix in Worker outcome signals. |
| 2026-08-20 | Make top-level functions the primary Python API and expose synchronous `Client` only for pooled batch use, multiple servers, tests and deterministic cleanup. |
| 2026-08-20 | Implement top-level functions as thin wrappers over a lazy default Client; perform no config read, network access or hook installation at import time, and add no `atexit` cleanup hook. |
| 2026-08-20 | Make explicit `Client.close()` idempotent and context-managed; operations afterward raise exact `RuntimeError("Client is closed.")` without reopening, while the lazy default has no close/reset API. |
| 2026-08-20 | Support only `parameter: T = TaskArg(...)`, not an additional `Annotated` form; expose generic overloads for type-checker compatibility while returning a private marker at runtime. |
| 2026-08-20 | Support `TaskArg(path=...)` using the same object-only dot-path syntax as command templates; omit array indexing, wildcards and escaping, and replace the v1 name `alias`. |
| 2026-08-20 | Allow an unannotated `TaskArg()` and skip final type validation for it. |
| 2026-08-20 | Always ignore extra Task args during named binding, even when the Worker declares `**kwargs`; runtime `**kwargs` remains ordinary Python call input. |
| 2026-08-20 | Pass `TaskArg(default=...)` through the same resolver and strict-validation pipeline as an explicitly submitted value. |
| 2026-08-20 | Retain the familiar `resolver` name and constrain it to a synchronous one-value conversion callback rather than introducing a new `convert` term. |
| 2026-08-20 | Strictly validate resolver output against the parameter annotation without further coercion. |
| 2026-08-20 | Reject invalid static Worker binding definitions before claim; treat resolver failures caused by a claimed Task value as ordinary `TaskError`s. |
| 2026-08-20 | Validate each annotated `TaskArg` through its Pydantic strict schema; Labtasker performs no preparatory cast, fallback conversion or second typing implementation. |
| 2026-08-20 | Implement annotated `TaskArg` validation with startup-compiled Pydantic TypeAdapter and `validate_python(strict=True)`; honor each annotation's own Pydantic schema, use explicit resolvers for application-specific conversion, and add no second typing engine. |
| 2026-08-20 | Require every JSON string/key to contain only Unicode scalar values and reject lone surrogates without repair or replacement. |
| 2026-08-20 | Bound every public filter expression to 8192 UTF-8 bytes with one `filter_too_large` error and no separate public AST complexity knobs. |
| 2026-08-20 | Emit handled finite-command errors as one readable JSON envelope on stderr with exit 1; keep Typer usage errors and continuing `loop` diagnostics as natural-language stderr. Superseded on 2026-08-28 by the stdout response-channel decision. |
| 2026-08-20 | Treat Agent-friendly as stable, explicit and composable rather than machine-only; retain readable messages, formatted JSON and concise natural-language operational logs without adding format modes. |
| 2026-08-20 | Automatically retry only read operations and create-by-Task-ID PUT; do not retry ordinary lifecycle/update/delete/Queue mutations because a retry can cross an explicit concurrent state change. |
| 2026-08-20 | Allow an explicit Task ID to be reused after hard deletion and retain no permanent tombstone/used-ID registry. |
| 2026-08-20 | Use stateless keyset pagination without cross-page snapshot guarantees or server-side pagination sessions. |
| 2026-08-20 | Treat network, timeout and malformed/nonconforming protocol responses as `TransportError` with fixed code `transport_error`; add no `ProtocolError`, while valid Server error envelopes remain `APIError`. |
| 2026-08-20 | Target Python 3.11+ in one two-package monorepo; use Pydantic 2/httpx/Typer in the Client and FastAPI/Pydantic 2/Uvicorn/synchronous SQLAlchemy 2.x/Alembic/Typer in the Server, with pytest and no parallel async/shared-core stack. |
| 2026-08-20 | Use `422 invalid_request` as the fallback for request validation without a more specific documented code; normalize details to located readable errors and never expose FastAPI/Pydantic's native envelope. |
| 2026-08-20 | Give `ConfigError` only `invalid_config` and `legacy_config_found`; use message plus source/field details instead of code/class proliferation. |
| 2026-08-20 | Retry eligible read/create calls only after `TransportError` or exact Server code `database_busy`; never retry other valid API errors. |
| 2026-08-20 | Require `idle_timeout` and `force_stop_timeout` to be finite non-negative non-Boolean numbers; only force-stop accepts null, while zero retains its documented immediate behavior. |
| 2026-08-20 | Let an explicit `TaskArg(resolver=...)` fully own conversion from its raw JSON value; resolver failures are ordinary `TaskError`s. |
| 2026-08-20 | Remove both `pass_args_dict` and public `required_fields`; dynamic handlers may inspect `task_info().args` instead. |
| 2026-08-20 | Keep CLI Task submission but accept args only as a strict JSON object through `--args`; remove trailing `-- --key=value`, `literal_eval` and CLI type guessing. |
| 2026-08-20 | Give command Workers one input form, `loop [OPTIONS] -- COMMAND [ARG...]`; direct-exec the resolved argv and remove command-string, script-path, stdin, executable and built-in shell modes. |
| 2026-08-20 | Preserve one-template-to-one-argv-element boundaries; insert strings exactly and all other JSON values as deterministic compact JSON without any shell quoting or second word split. |
| 2026-08-20 | Replace the command-template ANTLR stack with a compiled deterministic scanner whose complete EBNF, transition table, error timing and conformance obligations are part of the public design; retain no shadow `.g4`. |
| 2026-08-20 | Restrict command and `TaskArg` paths to object-only ASCII identifier segments, banning numeric/hyphenated/Unicode segments and array syntax rather than assigning them surprising meanings. |
| 2026-08-20 | Use `%{{` as the literal `%{` escape so unrelated `%%` remains untouched and a literal percent can directly precede interpolation. |
| 2026-08-20 | Inherit the Worker environment and overwrite only reserved `LABTASKER_*` context; add no `--env`, using explicit platform launchers or wrappers for dynamic environment values. |
| 2026-08-20 | Relay stdin only for an interactive POSIX PTY; use null stdin in noninteractive pipe mode and add no Task-input protocol. |
| 2026-08-20 | Relay and journal command output as raw bytes without decoding, normalization or ANSI stripping; `run.log` need not be valid UTF-8. |
| 2026-08-20 | Hide PTY as terminal-preserving implementation behavior: automatically use it on POSIX only when Labtasker is attached to an interactive terminal, otherwise concurrently relay pipes; expose no PTY switch and always copy live output to `run.log`. |
| 2026-08-20 | Support single-node torchrun/Accelerate only through one outer Labtasker command Worker owning one launcher invocation; keep claim, heartbeat and terminal ownership solely in that parent and add no distributed Server concepts. |
| 2026-08-20 | Reject nested loops and recognized `WORLD_SIZE > 1` rank environments before claim; treat rank variables only as an error guard, not a universal coordination protocol. |
| 2026-08-20 | Require distributed user code to select exactly one result reporter through its framework (`torch.distributed.get_rank() == 0` or `accelerator.is_main_process`); do not make `finish()` silently rank-aware. |
| 2026-08-20 | Defer persistent multi-Task distributed Python Workers because safe reuse requires broadcast, failure aggregation, cancellation coordination and process-group recovery. |
| 2026-08-20 | Treat the launcher exec boundary as the heartbeat ownership boundary: fork does not duplicate the heartbeat thread, exec replaces transitional state, and ranks descend from the post-exec launcher; close unrelated file descriptors and avoid Python `preexec_fn`. |
| 2026-08-20 | Cover distributed ownership with an always-on fake-launcher suite plus separately marked real torchrun/Accelerate release and scheduled integration tests. |
| 2026-08-20 | Use the same JSON argument model across Python, CLI and HTTP submission; Python submit rejects values that are not JSON-serializable. |
| 2026-08-20 | Replace `Required()` with `TaskArg()`: no default means the Task field is required, an explicit default handles absence, and unmarked parameters remain ordinary Worker-start arguments. |
| 2026-08-20 | Support synchronous Python Worker functions only in v2; defer `async def` support. |
| 2026-08-20 | Fix `@loop(...)` to route, Queue, idle timeout and force-stop timeout only; support no bare decorator or hidden filter/heartbeat/binding modes. |
| 2026-08-20 | Return a flat local-only frozen `TaskInfo` from `task_info()`, containing public Task fields plus claimant-only `run_id` and `run_dir` without exposing active execution through ordinary Task APIs. |
| 2026-08-20 | Make Task-context inspection/cancellation helpers fail explicitly outside active execution; keep `finish` strict by default but retain v1's narrow `skip_if_no_labtasker=True` escape hatch for intentionally standalone-compatible training code. |
| 2026-08-20 | Define one decorated-function or command-loop invocation as one dedicated local Worker process with at most one active Task and reusable fixed process state; create no server-side Worker entity. |
| 2026-08-20 | Give every claimed `run_id` a distinct Labtasker-managed local run directory; do not pretend to isolate arbitrary paths or third-party side effects chosen by user code. |
| 2026-08-20 | Give each local run journal a semantic Queue/Task/start-time/attempt/run-ID path and stable task, run, outcome and log files so it remains human- and Agent-browsable without a Server query. |
| 2026-08-20 | Limit Task name to 256 Unicode code points and derive an exact alphanumeric journal slug capped at 80 UTF-8 bytes, retaining the full name in Task data and using Task ID for directory identity. |
| 2026-08-20 | Reject Unicode `Cc` control characters only in Task name, while continuing to allow ordinary Unicode and arbitrary valid JSON strings in Task data. |
| 2026-08-20 | Best-effort atomically record running, reporting, acknowledged or revoked Worker-observed phases and exact terminal payloads; local write failure only reduces observability/recovery and never blocks or changes the Server action. |
| 2026-08-20 | Add no automatic journal replay, stale-run override, retention, compression, cleanup or remote-delete cascade in v2. |
| 2026-08-20 | Scope confirmed stale heartbeat ownership to the current run: command execution terminates its child and continues, while inline Python uses cooperative cancellation and continues if it returns. |
| 2026-08-20 | Let revoked Python and command execution wait for natural return by default; only an explicitly configured finite force-stop timeout terminates non-cooperative work, and a current-run setter may change the Python choice. |
| 2026-08-20 | After confirmed revocation or successful finish, keep ordinary cleanup exceptions local; continue honoring `FatalWorkerError` as a Worker exit without attempting to rewrite an already finalized Task. |
| 2026-08-20 | Name the Worker option `force_stop_timeout` and expose pure `cancellation_requested()` plus current-run `set_force_stop_timeout()`; anchor replacement deadlines at confirmed revocation rather than each setter call. |
| 2026-08-20 | Validate Worker configuration/static bindings before claim; make idle timeout the sole normal automatic return and let ordinary Task outcomes continue the loop. |
| 2026-08-20 | Keep Worker statuses conventional (`0` idle, `1` Worker failure, `2` CLI usage, `130` KeyboardInterrupt), preserve OS signal status, and distinguish command-child failure from Worker failure. |
| 2026-08-20 | Re-raise `KeyboardInterrupt` after best-effort unclaim, leave `SystemExit`/SIGTERM unhandled, and re-raise `FatalWorkerError` after resolving fail only when its run remains active. |
| 2026-08-20 | Guard complete/fail/unclaim by `running + matching active_run_id`; once complete succeeds, later exceptions and process outcomes cannot move the Task away from succeeded. |
| 2026-08-20 | Keep `cancellation_requested()` false after finish, reject post-finish `set_force_stop_timeout()`, and retain `task_info()` through local cleanup. |
| 2026-08-20 | Require initial run-directory/snapshot setup before executing user code; on failure best-effort unclaim and exit the Worker nonzero, while keeping later terminal journal writes optional. |
| 2026-08-20 | Separate Server Task attempts, Client HTTP transport attempts and external Worker restarts; exhausting Task attempts fails only the Task, while the Server stores run fencing but no Worker identity or lifecycle state. |
| 2026-08-20 | Add no `max_tasks`, `once`, `stop_after_current`, `daemon` or automatic restart Worker controls; keep process supervision external and do not misrepresent `idle_timeout=0` as once semantics. |
| 2026-08-20 | Make `finish(result=None)` an ordinary call that immediately and reliably succeeds the Task, defaults the result to `{}`, allows cleanup code to continue, and rejects a second call. |
| 2026-08-20 | Make Python normal return and command exit zero without `finish()` overwrite the complete result with `{}`; successful execution never implicitly inherits an older result. |
| 2026-08-20 | Keep `task_info()` available through post-finish local cleanup, while adding no separate local executor-exit timestamp. |
| 2026-08-20 | Preserve command-child `finish()` through inherited URL/token/Queue/Task/run/route/run-directory context; add no command-specific result or IPC protocol. Superseded on 2026-08-21 to inherit a discriminated HTTP-or-local endpoint snapshot while retaining the same run-fenced HTTP completion protocol. |
| 2026-08-20 | Have heartbeat distinguish the same Server-terminal run as `run_finalized(action=...)`; complete is benign post-finish cleanup while every other action revokes, making the finish/heartbeat race independent of local journal writes. |
| 2026-08-20 | When a best-effort result backup exists and a command child exits mid-report, let the parent resume that exact payload; do not make this optional recovery path a precondition for Server completion. |
| 2026-08-20 | Address heartbeat and terminal actions through the canonical Queue/Task path and carry `run_id` in the request body; do not add `/runs/{run_id}` endpoints. |
| 2026-08-20 | Generate `run_id` client-side before claim and reuse it across at most three exact claim transport attempts; only the same Queue and route may recover that active claim, while mismatched reuse returns `run_id_conflict`. |
| 2026-08-20 | Use one global 300-second heartbeat timeout and a fixed 60-second Client interval; return `lease_expires_at` from claim/heartbeat and add no Queue/Task/Worker heartbeat overrides. |
| 2026-08-20 | Scan expired leases every 60 seconds at startup/background, keep recovery out of claim, and make the Server deadline a hard boundary that a late claimant action can atomically expire but never revive. |
| 2026-08-20 | Enforce pending/running/non-running lease and pending-time invariants plus attempt bounds with database CHECK constraints rather than relying only on service code. |
| 2026-08-20 | Record heartbeat expiry as terminal action `heartbeat_expired` and stable latest error `HeartbeatTimeout` at the actual Server recovery transition time. |
| 2026-08-20 | Give complete/fail/unclaim exact strict bodies, let the Server add authoritative failure time/attempt/run fields, and return 204 for both first acceptance and same-action dedupe; contradictory or stale actions conflict and no terminal action returns Task data. |
| 2026-08-20 | Trigger local cancellation only after explicit `stale_run` or `run_finalized` with a non-complete action; treat matching finalized complete as successful post-finish cleanup and never infer revocation from Client time passing `lease_expires_at`. |
| 2026-08-20 | Keep heartbeat active while retrying an idempotent terminal action until accepted, deduplicated, explicitly stale, externally stopped or rejected by a non-retryable protocol error; add no report timeout. |
| 2026-08-19 | Treat `route` as the only Worker-supplied claim information; do not add Worker identity, metadata, resources or filter fields. |
| 2026-08-19 | Keep heartbeat payload free of progress, ETA and Worker status. |
| 2026-08-19 | Name the no-charge server action `unclaim`; map transient to it and map both fail/abort client outcomes to the ordinary `fail` action. |
| 2026-08-19 | Do not expose the active `run_id` through ordinary Task get/list responses; only the successful claimant receives the lease handle. |
| 2026-08-19 | Compute an internal SHA-256 creation hash over canonical normalized submit JSON to distinguish an idempotent retry from conflicting Task-ID reuse. |
| 2026-08-20 | Prefix generated IDs by type: `t_` for Tasks and `r_` for runs, followed by 12 URL-safe characters carrying 72 bits of secure randomness and no timestamp. |
| 2026-08-20 | Keep one active run slot and one latest-terminal `(run_id, action)` slot for fencing and bounded retry deduplication. |
| 2026-08-20 | Do not add a Run entity, execution-history table or terminal payload hash in v2. |
| 2026-08-19 | Return `201 + Task` for initial Task creation and `200 + current Task` for an identical retry, even after later lifecycle or input changes. |
| 2026-08-19 | Use idempotent create-by-name `PUT /api/v2/queues/{queue}` for Queue creation. |
| 2026-08-19 | Keep generated Task IDs compact rather than exposing a 36-character hyphenated UUID. |
| 2026-08-19 | Put Queue names explicitly in `/api/v2/queues/{queue}/...`; server auth no longer implies `/queues/me`. |
| 2026-08-19 | Use explicit lifecycle action endpoints and delete generic status patch/force-transition APIs. |
| 2026-08-19 | Represent an empty claim as `204 No Content`. |
| 2026-08-19 | Make Task creation retryable through client-generated IDs and create-by-ID `PUT`; do not introduce a separate idempotency key API. |
| 2026-08-19 | Standardize API errors as `{error:{code,message,details}}`. |
| 2026-08-19 | Version the rewritten HTTP contract under `/api/v2`. |
| 2026-08-24 | Require Client and Server Bearer tokens to use visible ASCII so invalid header values fail during configuration rather than at request handling. |
| 2026-08-19 | Use one optional server-wide Bearer token as the entire auth model; do not carry v1 Queue passwords or add per-Queue credentials, users or roles. |
| 2026-08-20 | Ignore Authorization when Server auth is disabled; when enabled, return indistinguishable `401 unauthorized` plus Bearer challenge for missing, malformed or wrong credentials. |
| 2026-08-20 | Permit tokenless bind only for `ipaddress.is_loopback` literals or case-insensitive exact `localhost`; wildcard and every other hostname require a token. |
| 2026-08-19 | Allow tokenless operation only on an exclusively loopback bind; refuse non-loopback startup without a configured token. |
| 2026-08-19 | Configure and rotate the token through server config/environment plus restart; provide no token-management API. |
| 2026-08-19 | Delete Queue atomically: empty directly, non-empty only with explicit cascade, and always reject while a running Task exists. |
| 2026-08-19 | Keep Queue as the sole server namespace and do not introduce Project. |
| 2026-08-19 | Require explicit Queue creation; submit to an unknown Queue never creates it. |
| 2026-08-19 | Create `default` only when initializing a fresh server database and use it as the client default Queue. |
| 2026-08-19 | Include explicit Queue deletion in 2.0.0 initial release. |
| 2026-08-19 | Default client empty-queue `idle_timeout` to 300 seconds; allow zero for immediate exit and provide no infinite-wait mode. |
| 2026-08-19 | Replace v1 `summary` with an always-object `result`; Python return values carry no implicit result protocol and persistence uses explicit `finish(result=...)`. |
| 2026-08-19 | Fix `last_error` to type/message/traceback/time/attempt/run_id, retain it after a recovered success, and clear it only on manual requeue. |
| 2026-08-19 | Use the state string `succeeded`, replacing v1's `success`. |
| 2026-08-19 | Allow cancel only from pending or running; running cancel invalidates `run_id` but does not promise remote process termination. |
| 2026-08-19 | Store only a structured Task `last_error` for the latest charged failure in 2.0.0 initial release; keep it separate from experiment output and do not add run-history storage. |
| 2026-08-19 | On an empty claim, keep the Worker alive for a bounded client-side polling grace period before normal exit; do not add an idle Worker entity or server wait protocol. |
| 2026-08-19 | Treat v2 as a subtractive refactor: every touched v1 feature is retained, redesigned or fully deleted rather than accumulated beside its replacement. |
| 2026-08-19 | Require heartbeat for every claimed run and use heartbeat loss as the only abandoned-run recovery mechanism. |
| 2026-08-19 | Delete task-execution timeout, `eta_max`, no-heartbeat execution and their public/configuration branches. |
| 2026-08-19 | Give `SystemExit` and SIGTERM no special Task protocol; process exit is recovered through heartbeat expiry. |
| 2026-08-19 | Treat heartbeat expiry as an ordinary charged execution failure. |
| 2026-08-19 | Treat binding, resolver and conversion errors as ordinary `TaskError` failures; charge the normal budget and continue the Worker. |
| 2026-08-19 | Replace retries with a 1-based charged `attempt`: claim increments it, transient rolls back only the current increment, and `max_attempts=3` caps total charged executions. |
| 2026-08-19 | Put a retryable charged failure at the end of its priority class without adding retry delays, backoff or policy abstractions. |
| 2026-08-19 | Make manual requeue reset `attempt` to zero unconditionally; do not expose a reset/preserve flag. |
| 2026-08-19 | Handle `KeyboardInterrupt` as a best-effort no-penalty Task return followed by Worker exit; timeout recovery is the fallback. |
| 2026-08-19 | Keep command-process failure binary: exit code zero succeeds and every nonzero code behaves like `TaskError`; reserve no special outcome codes. |
| 2026-08-19 | Name the public client outcome exceptions `TransientError`, `TaskError` and `FatalWorkerError`. |
| 2026-08-19 | Preserve previously consumed retry budget on a transient incident; only the current incident is uncharged. |
| 2026-08-19 | Expose all three client error levels as public Python exceptions that user code may raise; unclassified ordinary exceptions behave like task failure. |
| 2026-08-19 | Keep transient/fail/abort-style levels entirely in the client: abort reports the same Task failure as fail and differs only by exiting the Worker process. |
| 2026-08-19 | Make workers autonomous after startup: agents configure and supervise but never participate synchronously in claim, execution or failure decisions. |
| 2026-08-19 | Replace v1's runtime prompts with deterministic `transient`, `fail` and `abort`-style client outcomes; ordinary exceptions fail and continue. |
| 2026-08-19 | Make adaptation to agent coding a primary v2 principle across HTTP, Python, CLI, errors and idempotency without embedding an agent framework. |
| 2026-08-19 | After an ordinary task failure, report it through retry policy and continue the worker by default. |
| 2026-08-19 | Retain no-consequence transient recovery, retry-consuming failure and non-recoverable Worker abort without an in-loop decision maker. |
| 2026-08-19 | Prefer a small, complete and polished framework over broad but shallow feature coverage; every admitted feature must ship as a finished vertical slice. |
| 2026-08-19 | Make the CLI agent-first and non-interactive; defer TUI/UI as separate API clients instead of embedding presentation features in CLI. |
| 2026-08-19 | Treat minimalism as a hard requirement; use v1 as an inventory rather than an automatic compatibility contract. |
| 2026-08-19 | Remove built-in pager machinery and do not make human-oriented failure prompts the v2 contract; require scriptable structured CLI behavior. |
| 2026-08-19 | Use explicit worker `route` and task `routes`; remove worker claim filters and implicit argument routing. |
| 2026-08-19 | Move argument binding to the client; missing required inputs fail, declared defaults apply, and extra inputs are not errors. |
