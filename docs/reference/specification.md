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

Section 8.6 defines supplementary Worker observations and restricted grouped
counts. Task ownership and scheduling remain independent of these observations.
Section 3.0 clarifies the high-priority network-resilience boundary: protect
started Task execution and isolate supplementary observation failures, while
preserving bounded retry and failure-exit behavior during startup and claim.

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
formatting preference. An agent must be able to complete every core workflow:
set up, submit, inspect, run, diagnose, recover and mutate tasks without
scraping a human UI or relying on undocumented state.

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

Only the Client distribution exposes a supported public Python API. The Server
distribution is operated through its executable and HTTP contract; importing
`labtasker_server.app`, persistence, migration, CLI, or ownership modules is an
internal implementation dependency rather than a supported embedding surface.

All three distributions support Python 3.10 or newer. Client-only installations
remain useful in established ML environments because they avoid the Server
dependency tree, not because they have a different Python requirement.

All three distributions use the same release version and are published together
initially, but independently installed Client and Server runtime protocol does
not require exact package-version equality. V2 creates no shared runtime
`labtasker-core` distribution.

Both runtime executables expose an eager root `--version` option. It writes one
line to stdout and exits zero without reading configuration, contacting a Server
or starting a local daemon. `labtasker --version` writes `labtasker-client
VERSION`, identifying the distribution that owns the executable rather than the
code-free `labtasker` metapackage. `labtasker-server --version` writes
`labtasker-server VERSION`. Root `--help` lists `--version` but does not include
the current version number.

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
ordinary HTTP Client and Python Worker are kept portable on macOS and Windows;
the Server and Command Worker require POSIX and remain best effort on macOS.
Those non-Linux paths are outside the release gate, so a platform-specific
failure does not block 2.0.0.

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

Every Server mode is a POSIX feature. Foreground HTTP still requires the same
host-local advisory ownership lock as socket and daemon modes; v2 provides no
weaker Windows ownership substitute. On Windows, every operational
`labtasker-server` command fails deterministically with exit status 1 before
creating a Labtasker root, opening or mutating SQLite, binding a listener or
starting a process. Help and version inspection remain available. Windows
Clients and Python Workers may connect to an explicit HTTP Server running on a
POSIX host on a best-effort basis. V2 never silently starts a loopback TCP Server
as a substitute for managed local.

“Best effort” and “unsupported” are distinct platform classifications. Best
effort permits an ordinary documented path to run even though that platform is
not in the release gate. It does not permit a feature that this specification
explicitly marks unsupported on the detected platform to run speculatively. A
public Client, Worker or Server entry point for such a feature must perform a
deterministic platform or required-capability check before network access, Task
claim, journal creation, database mutation or child-process startup. A Python
entry point raises its documented error; an executable writes a readable
diagnostic to stderr and exits nonzero. It must not silently substitute
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
races, concurrent local-daemon startup/recovery, fresh schema plus every
supported Alembic forward-upgrade fixture, the fake distributed launcher, and
the real Linux single-node torchrun/Accelerate suite. The complete Client suite
must also pass on every supported Python version, 3.10 through 3.14, with every
direct runtime dependency at its declared minimum and, in a separate fresh
Python 3.10 resolution, with the newest versions allowed by its metadata. The
complete Server suite must likewise pass at its direct dependency minima on
every supported Python version, 3.10 through 3.14. Built Client and Server
wheels are installed independently, and all three distributions are installed
together, on Python 3.10 through 3.14. After 2.0.0, each release must pass the previous
released v2 Client core flow against the candidate Server. V2
sets no arbitrary coverage percentage and does not block release on a large
probabilistic stress suite or a complete macOS/Windows matrix.

### 0.5 Technology baseline

The Client, Server, full metapackage, and development workspace target Python
3.10 or newer. The three distributions live in the one monorepo workspace
described in section 0.3. The selected stack is deliberately conventional:

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
distribution, repository/plugin abstractions or multiple storage backends.
Distribution metadata declares the oldest dependency versions exercised by the
release gate and otherwise avoids upper bounds unless crossing the bound is
expected to break the supported API. The workspace lock file tracks current
compatible releases for the ordinary matrix. Automated dependency updates must
update that lock file without raising published lower bounds. A lower bound is
raised only for a concrete implementation need, an upstream support boundary, or
a security requirement, and its minimum-version test is raised in the same
change. When an older dependency release cannot run on a newer Python version,
environment markers declare the smallest compatible floor for that interpreter
without raising the floor for older environments. A separate Python 3.10 Client
test resolves the newest versions allowed by package metadata rather than
treating the workspace lock as a fresh upper-edge resolution. Minimum tests use
the package metadata itself with `lowest-direct` resolution and verify the
installed direct versions equal the active declared inclusive floors. They do
not maintain a second minimum lock or force transitive packages to their oldest
releases.
The fresh highest resolution is an early-warning canary rather than the
reproducible stability gate; the release workflow still requires it before
publication. Dependency versions are not a user-visible protocol negotiation
mechanism.

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

They are 1 to 128 ASCII characters, retain case and match case-sensitively; `SDXL`
and `sdxl` are distinct. V2 performs no lowercasing or other normalization. The
larger bound leaves room for descriptive Agent-generated route names while still
preventing unbounded identifiers in URLs, indexes, logs and local paths. Human
description belongs in the Task `name`, not by extending route syntax with
whitespace, slashes or arbitrary Unicode.

### 1.3 Meaning of a route

A route is an opaque execution-compatibility label. It is not a persistent Route,
Provider or Worker entity. The Server does not register routes or verify the
implementation behind a claimed route. Route presence can be derived from
unexpired Worker observations; it is approximate and does not imply spare capacity.

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
- No Route/Provider registry is introduced. Worker observations are defined in section 8.6.
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

The same domain applies to Task args, metadata, result and progress, ordinary update data,
Worker result/progress payloads, numeric Task fields such as priority/max attempts, and
filter literals. Python validation walks the object rather than relying on
`json.dumps` defaults; CLI/HTTP JSON decoding rejects nonstandard constants, and
canonical serialization uses `allow_nan=False`. An out-of-domain Task/request
value is a normal `422` schema validation error; an out-of-domain filter literal
is `422 invalid_filter`. Query equality continues to treat an in-range integer and
an exactly equal finite float as the same JSON number, as defined in section 10.

Every recursive JSON value stored in Task args, metadata, result or progress has maximum
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
- After command execution starts, a `run.log` write failure produces a warning
  and disables further writes to that log sink. The Worker continues draining
  and relaying child output so storage failure cannot leave the child blocked
  on a full pipe or PTY. This logging failure alone does not change the Task
  outcome. Initial journal setup failures retain the behavior in section 8.4.

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

### 3.0 Network resilience: high-priority boundary

Status: **Decided** — scope clarified on 2026-09-09.

**A Labtasker transport failure must not directly interrupt an already-started
Task execution or be classified as a workload failure. Supplementary Worker
observation failures must not affect the Worker's normal operation.** This is
not a blanket requirement that every network failure keep the loop alive:
startup and claim retain their existing bounded retry and failure-exit behavior.

- Startup checks may fail and exit before Task execution starts. Claim retries
  retain the same logical request and `run_id` for at most three transport
  attempts. If none obtains a usable response, propagate the transport failure
  and exit the Worker; do not start unconfirmed work or issue a new logical claim
  to hide the uncertain outcome. Any unacknowledged Server claim is recovered
  through the existing lease mechanism. A transport error is not an empty Queue.
- During Task execution, heartbeat transport errors trigger continued heartbeat
  attempts, not cancellation, termination of a command child or an exception
  injected into user code. A timeout or lost response is not proof of revocation.
- Completion, failure and unclaim reports retain their existing idempotent
  retry-until-resolved behavior. Waiting for a terminal acknowledgement can
  delay the next claim; it is not a workload failure. Transport retries do not
  themselves consume Task retry budget or increment `max_consecutive_failures`.
- Worker-observation registration, renewal and withdrawal errors remain fully
  isolated as specified in section 8.6, including during startup and claim.
  They must not cause loop exit, pause claiming, cancel execution or alter Task
  outcomes. The one-second observation shutdown wait starts only after an
  independent lifecycle reason has already selected exit; it cannot initiate it.

An explicit, valid Server decision is different from uncertain communication.
Continue to honor authentication/validation errors, missing Queues, cancellation
and confirmed ownership loss under their existing contracts. A long partition
can expire a Task lease and allow reassignment. On confirmed loss of ownership,
stop or cooperatively cancel the old execution as specified in section 8.1,
then normally continue the loop. Never weaken `run_id` fencing to accept stale
results. This clarification does not change lease expiry or automatic recovery.

Standalone Client/CLI requests keep their existing finite retry/error behavior.
Network I/O inside user workload code remains subject to workload-owned retry
and the existing exception classification; Labtasker does not transparently
resume an arbitrary failed user call or replay its side effects.

Validation must distinguish the phases: startup/claim transport exhaustion may
exit; heartbeat and terminal-report transport failures must not synthesize
workload failure; observation errors must not affect any Task/loop operation;
confirmed ownership loss must retain fencing and cancellation semantics.

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

This remains client-side polling with no Server long-poll/SSE behavior.
Independent Worker observations in section 8.6 also cover idle periods. The grace timer
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
not change `attempt`, `last_error`, `result` or the last progress snapshot; pending cancellation leaves the
latest-run summary unchanged. Repeating cancel on an already cancelled Task is
an idempotent success. Succeeded and failed Tasks reject cancel.

`requeue` accepts pending, failed and cancelled Tasks. It returns or keeps the
Task pending, resets `attempt` to zero, clears `last_error`, and refreshes
`pending_at_us`. It preserves `args`, `metadata`, `routes`, `priority`,
`max_attempts`, `result`, progress and the latest-run summary. Pending-to-pending requeue is
useful for explicitly forgiving already charged failures while a Task is waiting
for another attempt; even an attempt-zero Task is deliberately moved to the end
of its priority group. Running Tasks reject requeue. A succeeded experiment is
rerun by submitting a new Task rather than rewriting the successful record.

Invalid lifecycle actions return an explicit conflict rather than silently acting
as no-ops or force-setting state.

Execution actions obey one stable FSM guard: only a `running` Task with the
matching `active_run_id` may accept `progress`, `complete`, `fail` or `unclaim`. Once complete
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
changing status. Progress reporting never merges into `result`; the separate
latest-snapshot contract below carries provisional values while the run remains active.

### 4.5 Latest progress snapshot

An active run may replace its Task's optional `progress` object without changing
Task status, renewing its lease or changing `updated_at`. Progress is a strict,
user-defined JSON object with no required business keys. It may contain work
position, current metrics, best-so-far values or other compact provisional data
needed by a dashboard or an external early-stop controller. It is not a final
result, artifact store or metric-history series.

The ecosystem display convention for determinate progress uses top-level
`completed` and `total` values. A consumer may calculate a percentage only when
both values are finite JSON numbers, `0 <= completed <= total`, and `total > 0`.
This is a WebUI and integration convention, not a Server validation rule. The
Server continues to accept any strict JSON object and assigns no special
business meaning to other keys.

The Server records `progress_updated_at` from its own UTC clock and
`progress_attempt` from the current Task attempt. All three public fields are
null before the run reports progress. Every accepted report is a complete
replacement, including `{}`; there is no recursive merge. A new successful claim
clears all three fields so values from an older run never appear as current.
Completion, failure, unclaim, heartbeat expiry and cancellation retain the last
accepted snapshot for diagnosis. Requeue likewise preserves it until the next
claim clears it.

Progress is supplementary and never affects scheduling, retry budgets or the
Task outcome. Reporting is one-shot and best effort in the bundled Worker API:
validation errors are raised locally, while transport failures and Server
rejections are warned and return false without interrupting execution. A
confirmed `run_finalized` or `stale_run` response still updates the existing
local revocation state, so an external `cancel` can be observed sooner than the
next heartbeat. Applications choose an appropriate reporting cadence; the first
version does not add automatic throttling, coalescing, history retention or a
Server-side early-stop policy.

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

Any Unix-socket Server accepts the same HTTP API over one owner-only socket and
runs without application-level authentication. Its socket
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

### 5.5 Server storage, transports and process ownership

#### 5.5.1 One `serve` command

The complete Server launch surface has two equal, explicit transport forms:

```text
labtasker-server serve --connection http
  [--labtasker-root PATH]
  [--database PATH]
  [--database-filesystem auto|local|shared]
  [--host HOST]
  [--port PORT]
  [--daemon]

labtasker-server serve --connection socket
  [--labtasker-root PATH]
  [--database PATH]
  [--database-filesystem auto|local|shared]
  [--socket PATH]
  [--daemon]
```

`--connection` is the only unconditionally required option. It has no default;
omitting it is a command-line usage error with exit status 2, before root,
database, lock, socket, listener or process creation. The remaining requirements
and defaults are:

| Setting | Requirement or default |
| --- | --- |
| `--labtasker-root` | `.labtasker` relative to the Server startup directory |
| `--database` | `<labtasker-root>/server.db` |
| `--database-filesystem` | `auto` |
| `--connection` | required; exactly `http` or `socket`; no default |
| HTTP `--host` | `127.0.0.1`, only with `--connection http` |
| HTTP `--port` | `8000`, only with `--connection http` |
| Unix `--socket` | the owner-only runtime socket derived from the canonical Labtasker root, only with `--connection socket` |
| `--daemon` | false; the Server remains in the foreground |
| daemon log | `<labtasker-root>/server.log`, only when `--daemon` is present |

A relative root, database or explicit socket path is resolved against the
startup working directory and then canonicalized. The database need not be
inside the Labtasker root. The root identifies one managed daemon instance and
its durable log; the database path identifies the SQLite file being owned.
Management commands therefore select a daemon by root, while database ownership
is enforced independently by database path.

Root and database paths resolve their complete symlink aliases. A socket path
canonicalizes its parent but deliberately preserves the final directory entry:
that entry must be absent or an owned Unix socket and is rejected when it is a
symlink. This keeps normal parent aliases stable without allowing socket-target
validation to be bypassed.

`--connection http` accepts `--host` and `--port`, fills their HTTP-specific
defaults only after selecting that transport, and rejects an explicitly supplied
`--socket`. `--connection socket` accepts `--socket`, derives its default only
after selecting that transport, and rejects explicitly supplied `--host` or
`--port`. Implementations must preserve whether those conditional options were
supplied rather than mistaking the HTTP defaults for an invalid socket request.
A Unix socket is a supported public
transport for a manually operated Server, including a Server whose database is
on shared storage. It uses the same HTTP API over the socket and has no
application-level token. An explicit Client socket is externally managed; the
Client never starts, restarts, stops or reconfigures it.

Every Server-created socket is owner-only. Its parent must be a directory; a
group/world-writable parent is accepted only when it has the sticky bit, as with
ordinary `/tmp`. Startup rejects a symlink, an entry not owned by the effective
user or a non-socket target. It acquires the canonical socket-path lock before
inspecting or removing an owned stale socket and proves that no listener remains;
it never replaces a live or unverified endpoint.

`--daemon` changes only process lifecycle. Without it, `serve` stays attached,
uses standard input/output/error normally and reports an existing database owner
as an error. With it, the launcher detaches the Server from the terminal and
session, redirects stdin from the null device, appends logs to the default log
path, publishes runtime metadata and waits for readiness. It does not change the
connection, database, filesystem strategy, API or authentication. In particular,
`serve --daemon` without an explicit `--connection` is invalid; daemonization
never selects a transport.

V2 exposes no separate public `start` command, `--workers`, `--reload`,
`--log-file` or log-level option. Uvicorn always runs one Server worker. The
optional HTTP credential comes only from `LABTASKER_SERVER_TOKEN`. The loopback
and non-loopback authentication rules in section 5.4 remain unchanged.

The Labtasker root is created when an explicit `serve` invocation needs it. A
new root receives the ordinary owner-protecting `.gitignore`. Server launch does
not create or rewrite `config.toml`, and v2 provides no persistent Server
configuration file. Operators preserve a manual launch declaration in their
service manager, shell command or deployment configuration.

#### 5.5.2 Runtime identity and host-local locks

On POSIX, per-user runtime artifacts live below an owner-only host-local
directory:

```text
/tmp/labtasker-<effective-uid>/
  root-<sha256-of-canonical-labtasker-root>.lock
  root-<sha256-of-canonical-labtasker-root>.json
  root-<sha256-of-canonical-labtasker-root>.sock
  socket-<sha256-of-canonical-socket-path>.lock
  db-<sha256-of-canonical-database-path>.lock
```

The directory is mode `0700`, owned by the effective user and not a symlink.
Every lock file is an ordinary permanent sidecar path in this runtime directory.
Labtasker never unlinks it, gives it a TTL or steals it. The kernel releases an
advisory `flock` when every process holding its open descriptor exits.

All Server transports and lifecycle modes require POSIX advisory file locking.
Windows Server operation is unsupported; the executable rejects `serve`,
`status`, `stop`, `logs`, and private coordinator/daemon execution before root,
database, listener or process side effects. Root and command help plus
`--version` remain side-effect-free and available for diagnosis.

Every Server, foreground or daemon, holds the database-path lock for its complete
lifetime. Every Unix-socket Server also holds the socket-path lock, preventing a
foreground or detached process with a different database from racing for the
same default or explicit socket. A detached daemon additionally holds the root
lock for its complete lifetime so only one managed daemon can own that root's
runtime metadata. A daemon launcher acquires and passes only the root-lock
descriptor across exec. The daemon process itself acquires its socket lock, when
applicable, and then its database lock before removing a stale socket, opening
SQLite or listening. A failed child startup releases those locks and exits;
temporary creation of two children from different roots is harmless because
only one can acquire the database lock. Foreground HTTP Servers acquire only the
database lock; foreground socket Servers acquire socket then database. They are
not managed by `status`, `stop` or `logs`.

The first release that changes from the v2.5 database-inode ownership lock to
these sidecars has one bounded compatibility rule. For an effective `local`
strategy it additionally acquires and retains the legacy inode lock, after the
database-path sidecar and before opening SQLite, so a still-running v2.5 Server
cannot become a second owner during an ordinary upgrade. Failure to acquire that
lock aborts startup and emits one deterministic deprecation diagnostic explaining
that a legacy Server must be stopped before retrying. The legacy lock is
transitional internal compatibility, not a second public ownership mode; its
eventual removal must be announced by the release that removes it.

The compatibility lock is deliberately not used by the `shared` strategy, whose
filesystem locking behavior is the reason for using host-local sidecars. An
upgrade of a shared database from v2.5 therefore requires a clean stop of the old
Server before installing or launching the new version. Labtasker does not migrate
or take over a running legacy Server. A manually operated legacy Server whose
custom runtime identity cannot be discovered is likewise the operator's
stop-before-upgrade responsibility.

Canonicalization collapses normal symlink aliases. Hard links, bind mounts or
inconsistent path spellings that intentionally make one database appear as
several canonical paths are unsupported operator misuse.

These per-user locks exclude cooperating Server processes with the same effective
user on one host. Different Unix users have different runtime namespaces.
Opening one database from multiple effective users is unsupported unless the
operator provides external single ownership, regardless of whether the
filesystem is classified local or shared. On `shared` storage the locks are
defense in depth, not a cross-user or cross-node ownership protocol. The
deployment must externally guarantee exactly one Server. Labtasker adds no
distributed lease, TTL file lock, leader election or split-brain recovery.
Network partitions, incorrect shared-filesystem locking, external processes that
open the database, and broken remote `fsync` semantics remain outside the
guarantee.

The runtime JSON is generated metadata, not configuration or authority. It
contains a random generation, PID and process-start marker, Server version, the
canonical root and database, resolved filesystem strategy, connection/address,
log path, whether HTTP authentication is enabled, and an internal listener-bound
marker. It contains no token or reusable token digest. Writers use a
same-directory temporary file and atomic replace. Missing or malformed metadata
never permits breaking a held lock or signalling an unverified PID.

#### 5.5.3 Filesystem strategy

`--database-filesystem` selects the SQLite safety strategy:

| Requested value | Detection result | Effective strategy | Diagnostic |
| --- | --- | --- | --- |
| `local` | not consulted | `local` | none |
| `shared` | not consulted | `shared` | none |
| `auto` | known local filesystem | `local` | none |
| `auto` | known NFS, WekaFS, Lustre or other shared filesystem | `shared` | none |
| `auto` | unknown filesystem | `shared` | deterministic warning on stderr |

Detection is a guard, not a correctness proof. The implementation uses native
filesystem-type information for the database path or its nearest existing
parent, including Linux mount information and macOS mount data. It
maintains explicit known-local and known-shared type sets. A type not in either
set is unknown; v2 never guesses that an unknown filesystem is local. Explicit
`local` or `shared` is the operator's override and bypasses classification.

The current normalized type sets are exact:

```text
known local:
  apfs btrfs ext2 ext3 ext4 f2fs hfs hfsplus jfs overlay tmpfs ufs xfs zfs

known shared:
  beegfs ceph cifs fuse.sshfs gpfs lustre nfs nfs4 smbfs wekafs
```

Linux selects the longest matching mount point from `/proc/self/mountinfo`.
macOS selects the longest matching mount from `mount` output. Failure to obtain a
type is the same conservative unknown result. Additive recognition of another
filesystem requires evidence for its classification and tests; a new name is
never inferred from a substring such as `nfs` or `lustre`.

The strategies fix and verify these settings:

| Setting | `local` | `shared` |
| --- | --- | --- |
| `journal_mode` | `WAL` | `DELETE` |
| `synchronous` | `FULL` | `EXTRA` |
| `foreign_keys` | `ON` | `ON` |
| `busy_timeout` | `5000` ms | `5000` ms |
| SQLAlchemy pool | SQLAlchemy's ordinary file-SQLite pool; not forced to one connection | `QueuePool(pool_size=1, max_overflow=0, pool_timeout=5)` |
| transactions | concurrent reads, SQLite-serialized writes | every read and write serialized by checkout of the one connection |

`DELETE` means SQLite uses a rollback journal and removes it at commit instead
of retaining WAL and shared-memory coordination files. `EXTRA` includes the
directory durability step associated with deleting that journal. This is the
conservative shared-storage strategy, not a claim that SQLite can survive a
filesystem with incorrect advisory locking, cache coherence, or `fsync`
semantics. `foreign_keys=ON` enforces relational invariants on every connection;
`busy_timeout=5000` bounds SQLite lock waits independently of the shared pool's
five-second checkout wait.

Before listening, the Server obtains its host-local database ownership lock,
changes WAL/rollback-journal mode when necessary, installs connection-local
settings and reads every required value back. Failure, including an inability to
leave WAL cleanly or establish DELETE mode, aborts startup. This conversion is
not attempted while another cooperating Server under the same effective user
owns the path.

In `shared` mode checkout of the one pooled connection is the serialization
boundary. Every read and write service command, `/health` database query,
startup recovery and background expiry scan uses that same engine and holds the
connection until its transaction closes. Pool checkout waits at most five
seconds and never interrupts the transaction holding the connection. Timeout on
an application endpoint returns the existing retryable `503 database_busy`
envelope; `/health` retains its dedicated `503` health body from section 6.1.
After checkout, SQLite's separate five-second busy timeout still protects
against an external database lock.

Internal work never converts either timeout into an HTTP result. A pool-checkout
or SQLite-busy timeout during mandatory startup recovery aborts startup before
the Server listens. The same timeout during a background expiry scan rolls back
with no Task mutation, increments the applicable metric, emits one warning and
skips that scan; the background task remains alive and retries on its next
ordinary 60-second interval. It neither spins nor extends the expired leases.

The Server records low-cardinality in-process measurements:
`db_connection_wait_seconds`, `db_transaction_seconds`, pool timeouts and SQLite
busy failures, classified only by coarse operation kind. It emits structured
slow-operation records and periodic summaries. V2 adds no metrics HTTP endpoint,
waiter/peak counters or high-cardinality Task/Queue labels.

Synchronous SQLAlchemy and synchronous FastAPI endpoints remain the first
implementation. FastAPI runs endpoint functions in its worker-thread pool.
Moving HTTP handlers to async plus one bounded database executor is permitted
only after profiling shows thread-pool saturation or responsiveness problems; it
is not part of the shared-storage correctness contract.

#### 5.5.4 Daemon launch and state

`serve --daemon` is an idempotent ensure-running operation for its canonical
Labtasker root. The launcher compares effective configuration, so `auto` resolved
to `local` matches an explicit `local` request with otherwise identical values.

| Observed state | `serve --daemon` action |
| --- | --- |
| healthy daemon, matching effective configuration | succeed without starting another process |
| matching startup in progress | wait within the existing 30-second readiness deadline |
| no root owner | acquire the root lock, publish starting metadata and launch one child; the child acquires its socket/database locks |
| root lock held but health unavailable | fail; never steal the lock or kill the owner |
| healthy daemon with a different Server version, database, filesystem strategy, connection, address or authentication mode | fail with a configuration-conflict diagnostic |
| database owned through another root | child startup fails before schema work, SQLite access or listening |

A configuration conflict prints the non-secret differing fields and instructs
the operator to run `labtasker-server stop --labtasker-root PATH` before rerunning
the requested `serve --daemon` command. It never stops or reconfigures the
existing daemon automatically.

Server package version is part of matching so rerunning `serve --daemon` after a
package upgrade cannot silently retain the old binary/schema. The conflict uses
the same explicit stop-then-rerun remedy.

HTTP matching includes only whether authentication is enabled, not token
contents. Labtasker never persists a token or reusable digest and does not issue
an authenticated management probe. Changing `LABTASKER_SERVER_TOKEN` while a
daemon is running is not a supported hot reconfiguration: the operator stops the
daemon and runs the desired `serve --daemon` command again.

A successful launcher records its generation and effective configuration, starts
the installed Server from the same environment, and passes the root-lock
descriptor plus a private one-shot readiness channel. The daemon verifies the
inherited root identity, publishes its PID/start marker with its internal
listener-bound marker false, then acquires any socket lock and its database lock
before schema work. Only after Uvicorn has successfully established the configured
listener does that child atomically set the marker true and publish its generation
on the private channel. Other launchers require that marker before reusing the
daemon. The original launcher first verifies this bind confirmation came from its
child and generation, then requires `/health` through the selected connection,
all within the same 30-second deadline. A health response observed before the
matching bind confirmation cannot satisfy readiness; in particular, another
Labtasker Server already occupying the requested HTTP address cannot make a child
whose bind failed appear ready. This handshake is private process coordination,
not a public health field, endpoint or daemon state.

For a wildcard HTTP bind, the health phase uses the corresponding loopback
address without changing the configured bind identity. Readiness failure reports
the state and log path but does not automatically kill a process that may still
own a lock.

The daemon has no idle shutdown. It outlives the launching command, Client,
terminal and SSH session until explicit stop, process failure or machine
shutdown.

The managed-daemon state model is:

| State | Evidence |
| --- | --- |
| `running` | the listener-bound marker is true, health succeeds and runtime identity matches the root owner |
| `starting` | health fails, the root lock is held and matching launch metadata is younger than 30 seconds |
| `unhealthy` | the root lock is held without a matching healthy daemon or fresh starting record |
| `stopped` | the root lock is free |

Old metadata or socket files do not create additional public states. With no root
owner the daemon is `stopped`; a later launch validates and cleans its own stale
artifacts only after acquiring the applicable locks. A foreground Server is not
a managed daemon even if a Client can reach it at the root-derived socket.
`status` and `stop` intentionally ignore that process.

Each explicitly authorized Client auto-start invocation makes at most one launch
attempt. There is no persistent throttle, retry timestamp or backoff state.
Concurrent attempts are coordinated by the root lock: one launches, and the
others wait within the same 30-second readiness deadline without starting or
killing another process.

#### 5.5.5 Client-managed local Server

When no explicit, environment or root-config URL/socket wins, the Client falls
back to the managed local endpoint for its resolved Labtasker root. That endpoint
always uses:

```text
connection = socket
database = <labtasker_root>/server.db
database_filesystem = auto, but automatic startup requires known local
socket = runtime socket derived from canonical labtasker_root
```

The Client may connect to a healthy daemon at that socket without permission to
manage its process. It does not create the root, database, log, config or runtime
metadata merely by resolving configuration or attempting that connection.

A manually launched socket daemon is discoverable through its root only when it
uses the root-derived default socket. A custom `serve --socket PATH` must be
selected by `Client(socket=...)`, `LABTASKER_SOCKET` or config `socket`; that
explicit socket is externally managed even if the same process was launched with
`--daemon`.

Automatic creation or recovery requires the explicit, invocation-scoped
`--auto-start-local-server` CLI flag or
`Client(auto_start_local_server=True)`. The default is false, and the authority
is never read from or written to environment variables or `config.toml`. When
authorized, the hidden Server-package coordinator performs the same root-lock,
launch and readiness protocol as `serve --connection socket --daemon`. The child
then acquires its socket/database locks and cleans verified stale artifacts before
opening SQLite or listening.

The Client distribution does not import or depend on the Server distribution.
If the coordinator executable/module is unavailable, auto-start fails before
local state creation and instructs the user to install the complete `labtasker`
package or configure an existing URL/socket.

After an authorized operation fails to connect to managed local, the Client may
start the short-lived hidden Server coordinator. That coordinator, not the Client
distribution, owns filesystem classification so the platform-specific detector
is not duplicated across packages. It inspects the default database location or
nearest existing parent without first creating the root or database. Automatic
startup proceeds only when `auto` positively identifies known local storage.
Known shared storage and unknown filesystem types are rejected before root,
database, runtime metadata or daemon-child creation; starting the coordinator
process itself is permitted and is not the managed Server creation this boundary
forbids. Those deployments use an explicitly operated `serve` command with the
desired `--database-filesystem` value. Once a manually launched daemon is
healthy, an ordinary Client whose configuration resolves to managed local can use
its standard socket; absence never causes a shared or unknown replacement to be
started.

Importing `labtasker`, constructing `Client`, displaying help and running
`labtasker config show` perform no network or process action. A managed-local
operation without auto-start authority attempts only its resolved socket. If no
Server is available, it raises `TransportError` with the resolved root and
socket plus concise remedies: rerun the CLI operation with
`--auto-start-local-server`, explicitly launch
`labtasker-server serve --connection socket --daemon --labtasker-root PATH`, or
configure a URL/socket. The diagnostic substitutes the resolved root for `PATH`.
It does not mention rejected parent-search behavior.

Repeated and concurrent authorized auto-start calls are idempotent. One launcher
wins the root lock; others observe the matching startup and wait for readiness.
A healthy matching daemon is reused. A held but unhealthy owner is reported and
never killed. After winning the root lock, the daemon child removes only verified
stale metadata and removes a stale socket only while holding its canonical
socket-path lock.

Automatic recovery preserves every operation's existing retry and
uncertain-outcome rules. A pre-send connect failure may ensure the daemon and
send once. A request that may have reached the Server is not replayed merely
because the daemon restarts. Existing idempotent submit, claim, heartbeat and
terminal-report rules remain authoritative.

The Client auto-start contract always assumes the standard database and local
strategy. Combining prior manual custom-Server operation for a root with later
Client default auto-start assumptions is unsupported operator misuse; v2 adds no
persistent managed-instance marker or launch-configuration inference.

#### 5.5.6 Daemon management commands

The public management surface is:

```text
labtasker-server status [--labtasker-root PATH]
labtasker-server stop [--labtasker-root PATH] [--force]
labtasker-server logs [--labtasker-root PATH]
```

The root defaults and canonicalization match `serve`. These commands never infer
a database path, search parent directories or select a daemon by CWD ancestry.
`stop` exposes `--force`, defaulting to false.

`status` is read-only. It performs no cleanup, launch, stop, database access or
lock-file creation; an absent root lock path is treated as unlocked.
It writes one two-space-indented JSON object:

| Field | Value |
| --- | --- |
| `state` | `running`, `starting`, `unhealthy`, or `stopped` |
| `labtasker_root` | canonical absolute root |
| `database` | canonical absolute database path or null |
| `database_filesystem` | effective `local` or `shared`, or null |
| `connection` | `http` or `socket`, or null |
| `host`, `port` | HTTP bind values or null |
| `socket` | canonical Unix-socket path or null |
| `log` | canonical daemon log path |
| `pid` | verified daemon PID or null |
| `version` | verified Server package version or null |

Only `state`, `labtasker_root`, and `log` are populated without verified runtime
metadata. It reports only managed-daemon state; a foreground Server is outside
this command even if it happens to use the root-derived socket.

`stop` is idempotent for an already stopped root. It acquires the free root lock
before removing verified stale metadata and additionally acquires the socket-path
lock before removing a stale socket. For a verified daemon it sends
graceful termination and waits up to 30 seconds for the verified process and root
lock to end. The daemon's database/socket descriptors close with that process;
`stop` does not require their sidecar locks to remain globally free because a
different valid process may acquire them immediately afterward. Without
`--force` it never sends SIGKILL. With `--force`, failure to
stop during that period causes one final re-verification of PID, process-start
marker, generation and root identity before SIGKILL, followed by at most five
seconds for cleanup. It never signals an unverified PID, writes no persistent
disable marker and does not prevent a later explicitly authorized start. After
the verified generation exits, it removes that generation's socket/metadata so
an intentional stop does not leave stale runtime artifacts behind. Cleanup first
rechecks that metadata still names the stopped generation and acquires the
socket-path lock before unlinking its socket. A newer generation, a live listener
or an unreacquirable socket lock is left untouched.

`logs` writes the current UTF-8 `<labtasker_root>/server.log` contents to stdout
without following or paging. A missing log is an empty successful result.
Foreground Server output is not redirected there.

Successful launch/stop actions are quiet on stdout and described on stderr.
Server management failures use readable stderr and exit status 1; they do not
pretend to be application HTTP error envelopes. Internal Typer commands remain
hidden at command level with leading-underscore names, but their options remain
visible when their direct `--help` is requested.
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

The filesystem strategy, PRAGMA matrix, journal transition, connection-pool
limit, shared connection serialization and observability contract are defined in section
5.5.3. They are fixed Server safety behavior rather than public SQLite tuning
options. A future change to those constants requires measured workload evidence.

The profile does not weaken the service transaction contract. Every mutating
service command still begins one explicit `BEGIN IMMEDIATE`; read-only commands
still use one ordinary read transaction. In shared mode checkout of the single
pooled connection serializes both kinds.
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
synchronous application operations in its normal worker threads. Background
lease recovery opens the same synchronous transaction boundary and, in shared
mode, uses the same single-connection engine rather than maintaining a second
persistence path.

Task identity is scoped by its Queue:

```text
PRIMARY KEY (queue_name, task_id)
```

The same explicit `task_id` may therefore identify independent Tasks in two
different Queues, and no Task operation omits Queue scope. The active claimant
token is different: a global partial unique index on non-null `active_run_id`
prevents one live run token from owning two Tasks at once. Terminal dedupe values
are historical bounded slots and do not use that active uniqueness rule.

`args`, `metadata` and `result` are stored as compact canonical UTF-8 JSON text;
nullable `progress` uses the same representation when populated. Stored objects
have sorted keys and database checks for valid JSON. The Server
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
progress_json, progress_updated_at_us, progress_attempt
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
fields and `pending_at_us` are Server-private. Progress columns are all null or
all populated, and `progress_json` is checked as a valid JSON object. The pending-position contract is
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

### 5.10 Required storage, daemon and concurrency tests

Tests use real temporary SQLite files, independent connections and real
subprocesses where process ownership matters. At minimum they prove:

- filesystem detection maps known local and representative NFS/WekaFS/Lustre
  identities correctly, maps unknown to shared with one deterministic warning,
  and honors explicit overrides;
- local startup establishes and reads back WAL/FULL, shared startup establishes
  and reads back DELETE/EXTRA, and a failed WAL-to-DELETE transition aborts
  before listening;
- shared mode uses exactly one pooled connection, serializes read/read,
  read/write, health and expiry transactions, records wait/hold metrics, and
  returns `503 database_busy` after a five-second pool-checkout timeout without
  interrupting the holder; commit, rollback, cancellation and exception paths
  always return the connection, and no database path bypasses that engine;
- mandatory startup recovery aborts before listening on a pool/SQLite-busy
  timeout, while a background expiry timeout rolls back, records one warning and
  metric, skips that scan and successfully retries at the next ordinary interval;
- local mode retains concurrent WAL reads while every mutation still begins
  `BEGIN IMMEDIATE`;
- two roots targeting one canonical database as the same effective user contend
  on the database lock, two socket Servers targeting one canonical socket contend
  on the socket lock, and two daemon launches targeting one root contend on the root lock;
  process death releases every applicable lock and persistent lock sidecar paths are never
  deleted or TTL-stolen;
- a daemon launcher passes only its root lock; its child acquires socket then
  database locks before cleanup, SQLite access or listening, and a child losing
  either contention exits without touching the protected resource;
- during the bounded ownership transition, local startup also holds the v2.5
  database-inode lock and rejects a live legacy owner with the deprecation warning and
  stop-before-upgrade diagnostic; shared-storage upgrade tests require the old
  Server to be stopped rather than relying on the legacy remote lock;
- socket startup rejects symlinks, wrong-owner/non-socket entries and unsafe
  non-sticky writable parents, and stale-socket cleanup cannot race a new listener;
- the shared-storage documentation and tests never claim cross-host exclusion;
  a deliberately separate-host/simulated lock namespace demonstrates that
  external single ownership remains required;
- `serve --daemon` is a no-op only for a healthy matching effective
  configuration, waits for a matching startup, and reports every non-secret
  mismatch with the stop-then-rerun remedy; version mismatch conflicts, but token
  contents are never probed and token rotation requires stop then rerun;
- daemon readiness requires a matching private child bind-confirmation before
  health succeeds, and a different healthy Server already occupying the requested
  HTTP port cannot satisfy a new launcher's readiness check;
- omitting `--connection` fails as a usage error before creating a root,
  database, lock, socket, listener or process; HTTP fills only its host/port
  defaults, socket fills only its derived socket default, and transport-specific
  flags reject invalid mixtures;
- foreground `serve` never becomes a detached no-op and `--daemon` never selects
  or changes a connection;
- `status`, `stop` and `logs` select by canonical Labtasker root even when
  the database is elsewhere, while the database lock remains keyed by canonical
  database path; a foreground Server is outside daemon status and is never
  signalled by `stop` even if it uses the root-derived socket;
- normal stop never sends SIGKILL, forced stop signals only a reverified
  generation, post-exit cleanup cannot remove a newer generation or live socket,
  and a daemon outlives its launching CLI or Client;
- state classification exposes only `running`, `starting`, `unhealthy` and
  `stopped`; stale artifacts create no public state and repeated failed automatic
  attempts have no persistent throttle;
- many concurrent `--auto-start-local-server`/Client requests create one
  known-local daemon, reuse it idempotently and preserve pre-send versus
  uncertain-send retry boundaries; a Client-only installation fails before
  creating local state;
- endpoint resolution, `config show` and finite Client connection attempts do
  not create a root, database, config or process merely because a daemon is absent;
  known-shared and unknown storage reject Client auto-start before those side
  effects; and an already running manually launched shared daemon remains usable;
- an ancestor `.labtasker` directory and daemon are never selected from a child
  working directory unless that exact root is explicitly supplied;
- the complete explicit/environment/root-config/default endpoint, Queue and token
  precedence matrix resolves deterministically; the Labtasker root remains an
  independent config/journal location, the first endpoint layer wins, only a
  conflict in that winning layer fails, and explicit URL/socket Clients never
  supervise a Server;
- managed-local and Unix-socket operations reject unsupported platforms before
  network, root, database, journal or process side effects;
- different Workers racing for one Task produce exactly one successful claim;
- concurrent retries of one `run_id` return the same Task, while changing its
  route conflicts;
- a claim using the latest retained terminal `run_id` returns `stale_run`, while
  an older overwritten token has no promised recognition and every new logical
  claim uses a fresh private token;
- complete racing heartbeat expiry produces exactly one winning transition;
- after `fail(r1)` commits, `r2` may claim and a duplicate `fail(r1)`
  cannot alter `r2`;
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
per-field size knobs. Task JSON, progress snapshots and result summaries should
be compact; artifacts, checkpoints and large logs do not belong in the Task
database.

The same 1 MiB constant also bounds the complete stored user-owned Task data.
After applying creation defaults or any mutation that changes `name`, `args`,
`metadata`, `priority`, `max_attempts`, `routes`, `result` or `progress`, including
`complete(result)` and a progress report, the Server canonically serializes an
object containing all eight resulting fields as compact UTF-8 JSON. If it exceeds
1,048,576 bytes, the mutation is rejected with `422`,
`code="task_data_too_large"` and `details.max_bytes=1048576`. Batch update
validates every resulting Task and rolls back the whole batch if one exceeds the
bound. Thus several individually small mutations cannot accumulate an
artifact-sized Task. V2 has no blob, artifact or large-file storage API.

V2 performs no capability or version-range negotiation. Explicit HTTP Clients
request `/api/v2` directly and add no `/health` process-management preflight; an
incompatible deployment fails through the normal HTTP/protocol error path. A
managed-local coordinator and management commands may call `/health` only for the
daemon discovery, startup and status state machine in section 5.5. They do not use health as a capability handshake or
replace the ordinary operation response. `/health.api_version` remains useful for
deployment diagnosis, local ownership checks and Worker startup validation.

Application responses under `/api/` advertise the Server package version in
`Labtasker-Server-Version`, including successful, empty, and handled error
responses. When authentication is configured, the header is emitted only for
requests bearing the valid Server token. With authentication disabled, it is
public. `/health` and `/openapi.json` do not carry this header. The header does
not change response bodies, authentication, or the API version.

The Client observes this header on ordinary business responses, with no extra
request or preflight. Read-only `Client.server_version: str | None` returns the
normalized PEP 440 version from the latest observed business response. It starts
as `None`; a missing, invalid, or longer-than-128-character header resets it to
`None`. Reading the property never performs I/O. A network failure provides no
new observation. Older Servers and proxies may omit the header; absence does
not establish incompatibility.

If the observed Server version precedes the Client package version under PEP 440
ordering (including patch and prerelease differences), the Client writes one
`[labtasker] warning:` line to stderr recommending a Server upgrade and noting
that newer features may be unavailable. Each Client instance warns at most once
per distinct normalized older Server version. Equal, newer, and unknown versions
do not warn. This applies to Python, CLI, and Worker calls without changing
stdout, return values, exception types/codes/details, exit status, retries, or
Task execution. The warning is advisory, not a claim that version mismatch caused
an operation failure. It is not a Python warnings-filter-dependent exception.
There is no generic feature-version gate or automatic protocol fallback.

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
`creation_hash` (not a public Task field) to recognize the original creation
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

The next endpoint decisions cover claim, heartbeat, progress and the three server-facing
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
makes at most three transport attempts, always replaying the exact same request.
If none obtains a usable response, the transport error propagates and the Worker
exits under section 3.0; any unacknowledged claim relies on lease recovery.
An explicit empty `204` ends that logical claim and normal idle polling uses a
new `run_id`.

A successful claim returns the complete public Task plus execution ownership:

```json
{
  "task": {"id": "t_..."},
  "run_id": "r_...",
  "lease_expires_at": "2026-08-20T12:00:00Z"
}
```

Claim replay recognition is bounded. A retry whose `run_id` is still active
returns the same claim. A retry whose `run_id` remains in a Task's single
`last_terminal_run_id` slot returns `409 stale_run` rather than assigning new
work. After a later terminal transition overwrites that slot, the Server no
longer retains evidence that the older token was used and may treat it as a new
claim token. Reusing such an arbitrarily old token is unsupported: every new
logical claim must use a fresh private `run_id`. V2 adds no global Run history,
permanent used-token set or expiring tombstone table merely to recognize retries
outside this bounded window.

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
Heartbeat carries no progress, ETA or Worker status; progress has its own action.

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
POST /api/v2/queues/{queue}/tasks/{task_id}/progress
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

The non-terminal progress body is:

```text
progress: {"run_id":"r_...","progress":{}}
```

Only a running Task with the matching active `run_id` and an unexpired lease may
accept it. It returns `204`, replaces the prior snapshot and records the current
Server time and attempt. It does not renew the lease. A report at or beyond the
lease deadline applies normal heartbeat expiry before returning
`409 run_finalized`; a finalized matching run returns its recorded action and an
unrelated run returns `409 stale_run`. A report rejected by size validation leaves
the run active. The complete stored Task data, including progress, remains
limited to 1 MiB.

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
scanner. Heartbeat, progress, complete, fail and unclaim require
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
The slot remains available through the next claim and is overwritten only by the next terminal
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
defines one Worker loop lifecycle. The Server stores an expiring observation
for that invocation (section 8.6), without controlling its process. A Worker
executes at most one Task at a time, while its code,
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
    max_consecutive_failures: int = 5,
    metadata: dict[str, JSONValue] | None = None,
)
```

V2 supports only the explicit `@loop(...)` spelling, not a second bare `@loop`
form. Queue uses the ordinary Client resolution chain. `metadata` is one strict
JSON object fixed for the Worker invocation and defaults to `{}` when omitted.
The decorator has no Client, filter, heartbeat, required-fields, full-args-dict
or execution-timeout parameter.

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
labtasker.report_progress(progress, *, skip_if_no_labtasker=False) -> bool
labtasker.report_worker_telemetry(telemetry, *, skip_if_no_labtasker=False) -> bool
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

`report_progress()` accepts one strict JSON object and works in Python Workers
and Python programs launched by Command Workers. It returns true when the Server
accepts the replacement snapshot and false for an isolated transport/rejection
failure or confirmed revocation. Invalid data and missing execution context are
programming errors and raise. With `skip_if_no_labtasker=True`, missing context
returns false. The helper performs one request per call; callers should report at
meaningful evaluation/checkpoint boundaries rather than every inner-loop step.

`report_worker_telemetry()` accepts one strict JSON object and works in Python
Workers and Python programs launched by Command Workers. It synchronously
replaces the current Worker invocation's latest snapshot, performs one request,
and returns true only when the Server accepts it. Invalid data and missing
execution context are programming errors and raise; with
`skip_if_no_labtasker=True`, missing context returns false. Transport or Server
failures are isolated, logged and return false. Unlike Task progress, Worker
telemetry is not run-fenced and remains reportable during cleanup after a
successful `finish()` while the Worker observation is still present. It does not
renew observation expiry or affect Task execution. Labtasker adds no automatic
sampling, retry, throttling, history or platform-specific fields.

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
trace hooks, leftover live threads or one subprocess per Python Task. Those
approaches either corrupt ordinary Python expectations or defeat process-local
model reuse.

`task_info()`, `report_progress()`, `report_worker_telemetry()`,
`cancellation_requested()` and `set_force_stop_timeout()` require an active
Python Task execution context. Calling them during Worker startup, idle polling,
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
Client construction or network access. Failure at this stage raises the
corresponding Python exception or writes a CLI log diagnostic and exits nonzero,
including transport failure after the applicable request retry budget. It cannot
create a Task execution failure because local execution has not started.
Exhausting the three transport attempts for a logical claim also exits the
Worker. These startup/claim exits are explicitly permitted by section 3.0.

The word “retry” refers to three deliberately separate mechanisms:

| Mechanism | Owner | Effect when exhausted |
|---|---|---|
| Task `attempt / max_attempts` | Server Task state | The Task becomes `failed`; the Worker continues claiming other Tasks. |
| Bounded HTTP transport attempts | Client request logic | The request fails; startup/claim transport exhaustion exits the Worker. Task heartbeat and terminal reporting have separate recovery policies. |
| Worker process restart | External supervisor or Agent | Labtasker itself has no restart counter or policy. |

Reaching a Task's `max_attempts` does not itself terminate its Worker.
The independent local consecutive-failure limit can terminate that Worker. The
Server maintains Task and current-run correctness only: Task lifecycle/retry
fields, `active_run_id`, heartbeat expiry, terminal-deduplication slots and the
latest-run summary. Supplementary Worker rows store approximate activity only;
they add no process retry counter, resource inventory or remote lifecycle command.
Claim `route` is used for matching and copied to `last_route`; claim does not
register a Worker. Run heartbeat describes one claimed execution, independently
of Worker observation renewal.


An explicit empty claim starts the `idle_timeout`; a successful claim resets it.
When the timeout expires without work, a decorated Python Worker returns `None`
and a command Worker exits zero. Task success, ordinary charged failure and
transient unclaim resolve the current run before the local failure guard decides
whether to return to claim.

Each Worker loop has a local `max_consecutive_failures` limit, default `5`.
Python `loop()` and the Command Worker accept this keyword; `labtasker loop`
exposes `--max-consecutive-failures INTEGER`. Only positive non-Boolean integers
are accepted, validated before Client construction or network access. There is
no disable value, environment variable, Server configuration or persisted count.

An accepted failure report for an ordinary exception (including `TaskError` and
binding errors), Command nonzero exit or startup failure increments the count.
An accepted `TransientError` unclaim also increments it, without changing its
uncharged Task semantics. Successful completion resets the count, including
successful `finish()` followed by ordinary cleanup exceptions or nonzero child
exit. Empty polls, confirmed cancellation and lease loss leave it unchanged;
a report rejected as stale/finalized does not count as an execution failure.
Terminal-report network retries never count as additional executions.

After reporting and local execution cleanup, reaching the limit logs the count,
limit, last Task ID and error type, then raises `FatalWorkerError` before another
claim. The CLI exits `1`; an uncaught Python exception exits nonzero. Explicit
`FatalWorkerError` keeps its immediate-exit semantics, including after `finish()`.
The Server's retry budget, Task state and `run_id` fencing remain unchanged.
This protection is independent of supplementary Worker observability.

The count starts at zero for each loop invocation. External supervisors must
configure restart backoff and restart frequency limits: restarting clears the
count and can otherwise repeatedly damage the Queue. The guard cannot recover
retry attempts already consumed before exit.

Worker process statuses stay conventional and small:

```text
0    normal idle-timeout completion
1    Worker configuration, definitive protocol, FatalWorkerError or force-stop failure
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
the Task remains succeeded. Configuration and definitive protocol failures raise
their corresponding `LabtaskerError`. Worker-managed transport failures stay in
the recovery paths defined by section 3.0. Only idle timeout returns normally.

V2 adds no `max_tasks`, `once`, `stop_after_current`, `daemon` or automatic
restart option. Observations provide no remote control channel; a remote
`stop_after_current` would require a separate process-control protocol;
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
LABTASKER_SOCKET          # Unix-socket mode only
LABTASKER_QUEUE
LABTASKER_TASK_ID
LABTASKER_RUN_ID
LABTASKER_ROUTE
LABTASKER_RUN_DIR
```

Exactly one endpoint form is present. HTTP mode overwrites `LABTASKER_URL` and
removes `LABTASKER_SOCKET` and `LABTASKER_ROOT`. Unix-socket mode overwrites
`LABTASKER_SOCKET` and removes `LABTASKER_URL`, `LABTASKER_TOKEN` and
`LABTASKER_ROOT`.
If HTTP authentication is disabled, `LABTASKER_TOKEN` is absent even when the
parent environment happened to contain that name. These variables are
Worker-provided execution context, not a second user-facing connection or
environment templating system.

In authenticated HTTP mode the Server token is necessarily available because
child code that calls `finish()` performs the same authenticated, run-fenced
completion as the parent. It remains a server-wide trust-domain credential, not a
per-run authorization mechanism. Socket mode instead uses the already selected
Unix-socket endpoint; it never re-resolves a root or config from the child CWD. The opaque
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
browse without first querying the Server. Its root is the Client's snapshotted
Labtasker root, including for HTTP and external-socket Workers, and its stable
layout is:

```text
<labtasker_root>/
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
`<labtasker_root>/.gitignore` with `*` and `!.gitignore` rules. This keeps the entire
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
- `run.json` is the local execution journal. Schema version 2 contains a
  credential-free Server endpoint object, Queue, Task ID, run ID,
  route, attempt, start and finish timestamps, local phase, terminal action and
  Server acknowledgement time. The endpoint object always has `connection`,
  `managed_local`, `url`, `socket`, `labtasker_root` and `database`: HTTP fills
  only `url`, an external socket fills only `socket`, and a managed-local endpoint
  fills the last three paths. This snapshot prevents recovery or
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

### 8.6 Supplementary Worker observability

Status: **Decided** (2026-09-09).

The motivating workflow is discovering which routes have listening Workers and
inspecting pending work without inferring all execution capacity from running
Tasks. Running Tasks cannot reveal idle Workers or reliably describe a Worker
that is still cleaning up after `finish()`.

The following constraints are agreed for this revision:

- Accept a moderate implementation scope: Worker presence storage and migration,
  shared Worker reporting behavior, an HTTP/Python/CLI slice, and focused failure
  tests. Include online counts and meaningfully defined busy/idle observations;
  exclude Worker history, remote process control and scheduling dependencies.
- Task state and the existing run-fenced protocol remain authoritative for
  execution correctness and recovery. Worker observations are supplementary
  information. Do not spend substantial complexity maintaining strong
  consistency between Worker observations and Task state.
- Allow reporting jitter and delayed observations. Prefer prompt notification on
  a state change with periodic reporting to repair missed notifications. The
  Worker reporting interval is 60 seconds. Each accepted observation renews its
  expiry to 300 seconds after the Server's receipt time; Client wall-clock time
  does not determine freshness. These observation timings are independent of
  Task-run heartbeat and lease ownership. Delivery delays remain permitted.
  These values are fixed in the first version; add no Worker/Queue timing
  options, CLI flags or environment-variable overrides.
- Use an independent Worker-observation reporting loop for periodic renewal
  and prompt activity-change notifications. Do not piggyback this information
  on claim requests or Task-run heartbeats. One reporter serializes observation
  requests and covers waiting, execution, reporting and post-finish cleanup.
  Keep only the latest not-yet-sent observation, coalescing intermediate activity
  changes rather than queueing every transition. After failure, retry the latest
  observation on the next periodic or activity-change notification; do not add
  an independent exponential-backoff retry loop or replay obsolete snapshots.
  Rate-limit repeated failure diagnostics and log recovery. Reuse the existing
  transport timeout mechanism for observation requests; do not add a new strict
  end-to-end request deadline or ordinary immediate transport-retry loop here.
  Repeated warnings are limited to one per 60 seconds. Reporting failures retain the
  non-blocking execution boundary below.
- Failure to register or report Worker observations must not block startup,
  claim or execution when the ordinary Task protocol remains usable. Missing or
  stale observations are an acceptable degradation; provide diagnostics without
  changing Task outcomes. Task communication follows the phase-specific
  network-resilience boundary in section 3.0, including permitted startup/claim
  failure exits and the existing effects of confirmed protocol decisions.
- An observation network error, timeout, failed registration/renewal/withdrawal,
  or expired observation must never cause an otherwise-running loop to exit,
  pause claiming, cancel execution, change a Task outcome or increment the local
  consecutive-failure guard. Contain reporter exceptions in the observation
  path. Observation timeout handling is not a Worker-stop mechanism.
- Worker expiry or a busy/idle observation must not authorize, revoke, recover
  or otherwise mutate a Task run. Task ownership remains guarded by `run_id` and
  its existing lease. In particular, zero observed online Workers is not proof
  that no execution process exists.
- A Worker reports only two activity states: waiting for work, or occupied with
  a claimed execution including reporting and cleanup. Do not expose separate
  executing/reporting/cleaning phases. A Worker remains occupied after `finish()`
  until its local execution flow ends and it can return to claiming. Exact public
  states are `idle` and `busy`. Enter `busy` after a claim is confirmed successful;
  retain `idle` while awaiting or retrying an unconfirmed claim response. Return
  to `idle` after execution/reporting/cleanup when ready to resume claiming.
- Worker observations include the instance identifier, Queue, route, activity,
  last-contact time, an advisory associated Task ID, user-defined metadata, and
  an optional latest telemetry snapshot. The Task reference can be stale,
  terminal or deleted; it imposes no cross-record consistency or Task-mutation
  requirement. Labtasker does not automatically collect hostname, PID,
  scheduler, GPU or other platform-specific fields.
- The local consecutive-failure count and limit in section 8.2 are not included
  in the first-version Worker observation schema. Keep enforcement and its
  diagnostic logging local; do not add exit history for this feature.

A Worker observation identity belongs to one invocation of the Worker loop.
This loop-scoped choice is confirmed after comparison with process identity.
Generate a fresh Client-side instance ID for each invocation and retain it
across that invocation's Tasks, idle polling, observation retries and temporary
Server disconnections. A new invocation gets a new ID, even if it runs in the
same OS process, on the same route, or under the same launcher command. Do not
derive identity from PID, hostname or route, or require a user-supplied stable
name. IDs match `w_[A-Za-z0-9_-]{12}`, using nine random bytes encoded as
unpadded URL-safe base64.

This ID identifies an observed execution loop, not a Task or an ownership token.
Each claim continues to use a fresh private `run_id`. Multiple Workers on the
same route have distinct instance IDs. The outer Command Worker owns the
observation; its command child and distributed ranks do not independently
register as Workers. A reconnect within the same invocation retains its ID;
a process restart starts a new invocation. Old and new observations can briefly
coexist until the old one expires, so counts are not exact live-process counts.

Expired Worker observations are excluded from online list/count results as soon
as their expiry is reached, independently of physical cleanup. Clean up expired
rows in the background; do not expose retained offline observations or Worker
history. Only after an independent existing lifecycle reason has already
determined that the loop should exit, attempt to withdraw its observation.
Wait at most one second in total for observation-reporter shutdown and withdrawal,
then stop waiting and continue the already-decided exit. This budget must not
start during ordinary execution, initiate an exit, change its exit result or
limit Task execution/cleanup. Successful withdrawal is not a prerequisite for
exit. Stop further reporting as part of shutdown; crashes, failed withdrawal
and unfinished requests fall back to expiry. Do not forcibly terminate workload
threads or processes to enforce this observation-only wait budget. Delete expired
rows at Server startup and on the existing lease-scan cadence; physical cleanup
does not control online query eligibility.

Registration and renewal use one complete-observation reporting operation:
create the row when absent, otherwise update the observation and renew its
expiry. A still-running loop can recreate a cleaned-up observation using its
unchanged instance ID after connectivity returns. Do not require a separate
register-then-heartbeat handshake. Use
`PUT /api/v2/queues/{queue}/workers/{id}` with complete `route`, `status`,
nullable advisory `task_id` and strict JSON-object `metadata` fields, returning
`204` without a body on success. `metadata` defaults to `{}` when omitted for
compatibility with older reporters.
Use `DELETE` on the same path to withdraw, also returning `204`; withdrawing an
absent Worker in an existing Queue is successful. Both operations require an
existing Queue and never create one implicitly. A stored instance cannot change
its route: a conflicting report returns `409 worker_route_conflict`. The three
original report fields are required; metadata is optional with default `{}`.
`task_id` accepts null or a syntactically valid Task ID. Bundled Workers report
null when idle and the claimed ID when busy; the
Server imposes no Task lookup, foreign key or cross-field consistency check.

An active execution may synchronously replace its Worker's latest telemetry via
`POST /api/v2/queues/{queue}/workers/{id}/telemetry` with
`{"telemetry": {...}}`, returning `204`. Telemetry is a strict user-defined JSON
object and `{}` is a valid replacement. The Server records
`telemetry_updated_at` from its own clock. This action does not update
`last_seen_at`, renew expiry, change route/status/task association, create an
absent or expired observation, or affect Task execution; the latter returns
`404 worker_not_found`. There is no telemetry merge, history, automatic sampler,
retry loop, throttling, aggregation or platform-specific schema.
The outer Command Worker injects its one loop-scoped Worker ID into the child
environment. Descendants and distributed ranks therefore report to the same
snapshot. Concurrent reports remain independent complete replacements; the last
report committed by the Server is visible. There is no rank selection, per-rank
Worker observation, field merge or conflict resolution.

Online Worker observations do not prevent Queue deletion. Preserve the existing
Task-based Queue deletion rules and remove its Worker observations when the
Queue is deleted. Subsequent observations for that absent Queue fail through
the ordinary Queue-not-found contract; they do not restore the Queue.

Accept last-arriving observations without a strict closed-instance registry.
Although the Client serializes reporting and stops sending on exit, an earlier
timed-out request may be processed after withdrawal and temporarily recreate
the row. This is permitted: absent further reports it expires 300 seconds after
its last accepted observation. Do not introduce closed-instance tombstones or
generation tracking merely to eliminate this supplementary-observation race.
None of these observation updates changes Task ownership or recovery.

Route-level presence means at least one unexpired Worker observation in the same
Queue for that route, whether the Worker is waiting or busy. Route presence is
separate from a Worker's two activity states and does not imply spare capacity.

The primary route-inspection use case is examining all routes referenced by
pending Tasks to diagnose waiting work. Query Task counts with `status=pending`
and `group_by=routes`, then independently query Worker counts by `route`.
Clients can align these small results for a combined display. Worker-only routes
may be included by the consumer; the Server does not impose a joined view.
A multi-route Task contributes to multiple groups, so route counts are not
disjoint partitions of Tasks. There is no Route registry or lifecycle.

This feature's delivery scope is HTTP API, Python API and CLI. Web UI design
and implementation are separate follow-up work. Presentation order does not by
itself require separate endpoints; the independent queries can support later
Task-demand, Worker-capacity and combined views without a Route resource.

Task and Worker grouping are computed by the Server and exposed through count
operations. Worker read operations are `GET /api/v2/queues/{queue}/workers` and
`GET /api/v2/queues/{queue}/workers/count`, Python `list_workers()` and
`count_workers()`, and CLI `labtasker worker list|count`. Do not add a separate
Worker get operation, history query or user-facing remote-control command.
Worker list and count accept the same `filter` expression form, reusing the
existing filter language syntax with a Worker-specific field/type mapping.
Do not create a second expression language. Fixed public Worker fields and
nested `metadata.*` and `telemetry.*` paths are filterable using the existing
operators and dynamic JSON typing rules. Task-only paths do not become Worker
fields merely because the parser is shared. A Worker query remains
scoped to its URL Queue and excludes expired observations before user filtering.

Public Worker observations expose `id`, `queue`, `route`, `status`, nullable
`task_id`, `metadata`, nullable `telemetry` and `telemetry_updated_at`,
`last_seen_at`, and `expires_at`. All timestamps are Server-generated UTC values.
Expose the Server's expiry directly rather than requiring consumers
to reconstruct it from a hard-coded timeout. Worker lists use fixed `id`
lexicographic ascending order, `limit`/`cursor` pagination with default 100 and
maximum 1000 records, and live per-page reads without a cross-page snapshot.
Do not add an `order_by` option. Worker grouped counts follow the same page-size,
dimension-order and live-read rules as Task grouped counts.

Worker counting uses the same count-only grouping model as Task counting:
allow `route`, `status`, and their combination, with statuses `idle` and `busy`.
Unlike Task `routes`, Worker `route` is single-valued. Count only unexpired
observations. Ungrouped HTTP counting returns `{count: int}`; grouped responses
use `group_by`, `count`, `items` containing `key`/`count`, and `next_cursor`.
Do not introduce a separate fixed online/idle/busy metric structure. Python
`count_workers()` follows the same ungrouped-integer/grouped-page convention,
and CLI uses `--group-by route,status` with comma-separated, space-free fields
and JSON output. Worker observations and Task facts remain independent sources.

The existing `GET /api/v2/queues/{queue}/tasks/count` accepts restricted grouping.
Supported dimensions are `routes`, `status`, and their combination in either
order. `last_route`, metadata and other fields are outside this version. Metrics
remain counts; no arbitrary expressions, joined summaries or separate `/stats`
endpoint are introduced.

Grouped count responses have exactly these top-level fields: `group_by`, an
ordered array of the requested dimension names; `count`, the deduplicated
matching Task total; `items`, the current page of groups; and `next_cursor`,
the next-page token or null. Each group has `key`, an object mapping each
requested dimension name to its string value, and `count`, its Task count.
Do not encode group keys as positional arrays or add fixed `by_status` metrics.
For a `routes` dimension, the key value is one expanded route string, despite
the plural field name. JSON object member order is not the grouping-order
contract; the top-level `group_by` array defines dimension order.

Selection applies before aggregation. For `routes`, expand membership: a
multi-route Task appears in each compatible group, including when running.
This is not an actual-run route distribution. Top-level Task totals must not be
calculated by summing overlapping route groups. Return only groups that contain
at least one selected Task; do not generate zero-count combinations. After
completely reading the relevant groups, consumers may interpret an absent
combination as zero. An unvisited result page must not be interpreted as zero.

Grouped HTTP counting uses `limit` and `cursor`: the default limit is 100 groups,
the maximum is 1000 groups, and the minimum is one. Pagination applies after
selection and aggregation over the complete matching Task set. Any top-level
Task count describes that complete set at the request's read, not only the
returned groups. Group cursors are distinct from Task-list cursors. Follow the
existing Task-list cursor principle: bind a cursor to its operation/resource,
Queue, complete selection (including status/name/name_fuzzy where applicable
and the exact filter expression), and ordered grouping dimensions. Worker-list
cursors similarly bind their fixed ordering and selection. Reject malformed
or mismatched cursors with the existing `invalid_cursor` error. Page size is
not bound and can change between requests. Do not require equivalent-but-
differently-written filter expressions to share a cursor. Exact encoding
remains an implementation detail, not a public decoding contract.

Sort groups lexicographically ascending by their key values in the order of the
requested grouping fields, using deterministic case-sensitive string ordering.
Thus `routes,status` orders by route and then status, while `status,routes`
orders by status and then route. Status ordering is lexical, not lifecycle
ordering; do not add a special status-order policy or count-based ordering.

Each page reads current data independently. Do not preserve a cross-request
snapshot or introduce snapshot resources. Concurrent Task changes may alter
counts, introduce or remove groups, and change the top-level count between
pages. Combining pages is not guaranteed to represent any single instant;
the exact continuation behavior must follow the defined group-key ordering.

The following CLI syntax and compatibility requirements are agreed:

- Add `--group-by` to `labtasker task count`; use a single comma-separated
  argument with no spaces, for example `--group-by routes,status`.
- The option help must explicitly say `Comma-separated grouping fields, with
  no spaces (for example: routes,status). Supported fields: routes, status.`
  Do not document space-separated or repeated-option
  syntax as alternative forms.
- Explicit grouped queries produce deterministic structured JSON. Do not add
  a default table, TTY-dependent formatting or a separate stats command.
- Grouped CLI counting exposes `--limit` and `--cursor`, returns one page of
  JSON with `next_cursor`, and does not automatically fetch subsequent pages.
  Its page-size default and maximum match HTTP grouped counting.
- Without grouping, preserve existing HTTP `{count: int}`, Python integer
  return and CLI output behavior. New structured results are opt-in through
  grouping.

Extend both Client and module-level `count_tasks()` with an optional `group_by`
argument instead of adding a separate grouped-count method. Calls without
grouping retain the integer result. Grouped calls return a typed page matching
the HTTP grouped response; use typing overloads to describe these cases. The
Python `group_by` accepts an ordered sequence of field names, including lists
and tuples, such as `["routes", "status"]`. Do not also accept a comma-separated
string in Python; the Client serializes the sequence to the HTTP parameter.
Grouped calls return `GroupCountPage`, containing `CountGroup` items; Worker
listing returns `WorkerPage` containing `WorkerObservation` items.

Grouping validation is strict: reject empty grouping values, whitespace,
duplicate fields and unsupported fields/combinations instead of trimming or
deduplicating. Repeating CLI `--group-by` is an error. Ungrouped counting rejects
explicit `limit` or `cursor` parameters; do not silently ignore them. Client and
CLI defaults must distinguish omission from an explicitly supplied page size,
so existing plain-count calls remain unchanged. HTTP grouping and pagination validation uses `422 invalid_request`; malformed
or mismatched cursors use `422 invalid_cursor`. Repeated HTTP `group_by`
parameters are rejected. Python and CLI reject invalid grouping before network access.

Compatibility is additive: existing ungrouped count requests and Task protocol
messages remain unchanged. An old Client does not report observations. A new
Worker may execute Tasks against an old Server even when all observation calls
fail. A new Client rejects a scalar count response to a grouped request with
`TransportError`, since old Servers may ignore unknown query parameters. Do not
silently aggregate a Task-list page or invent zero Worker counts on HTTP errors.

Persist one mutable row per Queue/Worker ID, with Queue deletion cascading to
observations and indexes for expiry cleanup and Queue/route/status queries.
Migration `0002_worker_observations` adds this table without changing Task data.
Migration `0003_task_progress` adds the nullable progress snapshot columns while
preserving existing Tasks and routes.
Migration `0004_worker_observability` adds Worker metadata and nullable telemetry
snapshot columns while preserving existing observations with metadata `{}`.
Count and grouped items share a read transaction within a response. Aggregate
in SQL over the complete selection, then paginate groups; do not load Task JSON
or all Task rows into the Client. Observation mutations remain separate from
Task transactions and preserve the single-Server SQLite ownership model.

## 9. Client and CLI API

Status: **Decided**

### 9.1 CLI surface and configuration

The v2 client executable has this complete command tree. The root options
`--labtasker-root PATH` and `--auto-start-local-server` apply to every Client
command, including nested Task/Queue/Worker commands:

```text
labtasker task submit|get|list|count|update|cancel|requeue|delete
labtasker queue create|list|delete
labtasker worker list|count
labtasker loop
labtasker config show
```

The execution-context helpers `finish()`, `report_progress()` and
`report_worker_telemetry()` are Python APIs, not CLI commands. Command Workers
use their process exit status for ordinary completion; Labtasker does not add a
parallel CLI command for every Python runtime helper.

The exact Client CLI option inventory is:

| Scope | Public arguments and options |
| --- | --- |
| root | `--version`; `--labtasker-root PATH`; `--auto-start-local-server` (false) |
| `task submit` | `--args {}`, nullable `--name`, `--metadata {}`, `--priority 0`, `--max-attempts 3`, repeatable `--route`, nullable `--id`, nullable `--queue` |
| `task get` | required Task ID; nullable `--queue` |
| `task list` | nullable `--status`, `--name`, `--name-fuzzy`, `--filter`, `--order-by created_at`, `--descending` / `--ascending` (descending), `--limit 100`, nullable `--cursor`, nullable `--queue` |
| `task count` | the four list selectors, nullable comma-separated `--group-by`, `--limit`, `--cursor`, and `--queue`; limit/cursor require grouping |
| `task update` | exactly one of a positional Task ID or `--filter`; required `--changes`; nullable `--queue` |
| `task cancel`, `task requeue`, `task delete` | required Task ID; nullable `--queue` |
| `queue create`, `queue list`, `queue delete` | required name for create/delete; delete has `--cascade` (false) |
| `worker list` | nullable `--filter`, `--limit 100`, `--cursor`, and `--queue` |
| `worker count` | nullable `--filter`, comma-separated `--group-by`, `--limit`, `--cursor`, and `--queue`; limit/cursor require grouping |
| `loop` | `--route default`, nullable `--queue`, `--max-consecutive-failures 5`, `--idle-timeout 300`, nullable `--force-stop-timeout`, `--metadata {}`, then required direct argv after `--` |
| `config show` | no leaf options |

Page limits accept 1 through 1000. `--max-attempts` and
`--max-consecutive-failures` are positive integers. `--force-stop-timeout` is a
finite non-negative number or null. Strict JSON-object options reject arrays,
scalars, non-finite values, out-of-range integers, excessive nesting, and
trailing JSON data before any request.

The Server remains a separate runtime package and executable with the
`serve|status|stop|logs` commands from section 5.5; there is no `labtasker
server` command and no separate `start` spelling. V2 provides no `event`,
`admin`, pager or TUI commands
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

Connection selection and any explicitly authorized local process management are
visible. On a Client instance's first successful connection, before returning the
requested value, the Client writes one concise `[labtasker] connected`
diagnostic to the then-current stderr. A managed-local endpoint identifies
`server=local`, `transport=unix`, canonical `labtasker_root`, database and
socket, plus verified daemon PID and Server package version when available. An
explicit socket identifies `server=external`, `transport=unix` and the socket
path. An HTTP URL identifies `server=remote`, derives
`transport=http|https` and writes the complete credential-free base URL. No
diagnostic prints a token.

When `auto_start_local_server` is true, startup additionally writes
component-prefixed diagnostics when it requests or starts a daemon, waits for
another startup or observes readiness. A default managed-local request with no
running daemon reports the resolved root/socket and remedies but does not create
or start anything.
`labtasker` Client messages use `[labtasker]`; messages from the Server
executable use `[labtasker-server]`. These finite-operation diagnostics have
no timestamp and are required for direct Python API use as well as CLI use. The
successful connection line occurs at most once per Client instance, plus a new
line after an actual reconnection. Requested output remains alone on stdout.
Local Worker exception logging follows the Client outcome abstraction without
changing it: `TransientError` logs at WARNING with type/message but no default
traceback; `TaskError` logs at ERROR with traceback; `FatalWorkerError` logs at
CRITICAL with traceback before the Python Worker exits. A command child failing
by exit code or signal logs one ERROR containing that outcome, but does not copy
its already-relayed output into a second diagnostic message.

Authorization headers and token values must never appear in logs or errors.
Other diagnostic data, including Queue, Task ID, route, run ID, status, action,
attempt, timing, args, metadata, progress, result and traceback, may be logged when useful;
v2 imposes no field-by-field redaction system. Ordinary success logs should still
avoid dumping large payloads without diagnostic value.

Every Task leaf command and `loop` accepts `--queue` at that leaf position:

```text
labtasker task list --queue experiments
labtasker loop --queue experiments --route sdxl -- python train.py
```

There is no alternate global `--queue`. The Client CLI also has no `--url`,
`--socket` or `--token` options. One-off external endpoints and credentials use
environment variables; durable values may use config. The two global local
controls appear before the command:

```text
labtasker --labtasker-root /work/run/.labtasker task list
labtasker --auto-start-local-server task submit --args '{"seed":1}'
labtasker --labtasker-root /work/run/.labtasker \
  --auto-start-local-server task list
```

`--labtasker-root` selects the exact config, journal and managed-local-default
root; it does not itself override a configured URL or socket.
`--auto-start-local-server` grants process-start/recovery authority only for that
invocation. It does not persist permission and remains invalid when the resolved
endpoint is HTTP or an explicit socket.

#### Configuration location and precedence

Configuration follows one general rule: an explicit value overrides an implicit
one. The Client first resolves the config root:

```text
explicit labtasker_root / --labtasker-root
> LABTASKER_ROOT
> <canonical exact CWD>/.labtasker
```

Every Client retains this root for config lookup and Worker journals, including
when its network endpoint is HTTP or an external socket. The root is independent
of endpoint selection: it locates config and journals, and supplies the managed
local default only when no URL or socket wins. The Client reads at most
`<labtasker_root>/config.toml`. It never searches a parent
directory, infers a VCS/project root, reads a user-global file or merges profiles.
A later `chdir()` does not retarget an already constructed Client.

Endpoint selectors are atomic, not independent fields. Their source order is:

| Layer | Available endpoint selectors |
| --- | --- |
| explicit Python | `Client(url=...)` or `Client(socket=...)` |
| environment | `LABTASKER_URL` or `LABTASKER_SOCKET` |
| config | `url` or `socket` |
| built-in | managed local using the resolved Labtasker root |

The first layer containing an endpoint selector wins. Both selectors in that
winning layer are `invalid_config`; endpoint conflicts and semantic endpoint
errors in lower shadowed layers are ignored. The selected root config file must
still be valid TOML with known keys and string values, even when its endpoint is
shadowed. Queue and token use their own fallback chains:

```text
Queue:
  per-call/CLI value
  > explicit Client value
  > LABTASKER_QUEUE
  > <labtasker_root>/config.toml
  > default

token:
  explicit Client value
  > LABTASKER_TOKEN
  > <labtasker_root>/config.toml
  > absent
```

The config file is strict flat TOML with exactly these optional string keys:

```toml
url = "http://127.0.0.1:8000"
# socket = "/absolute/path/to/server.sock"  # mutually exclusive with url
queue = "default"
token = "secret"                           # sent only for an HTTP URL
```

A persistent external socket therefore needs no CLI flag or repeated environment
variable. `labtasker_root` is deliberately not a config key because the root must
be known before locating the file. Automatic-start permission is also not a
config/environment key.

The corresponding environment variables are `LABTASKER_URL`,
`LABTASKER_SOCKET`, `LABTASKER_ROOT`, `LABTASKER_QUEUE` and
`LABTASKER_TOKEN`. A present empty root, Queue or token is invalid rather than
absent. Endpoint values are validated only in the winning endpoint layer. An
effective token is sent only for an HTTP URL. A socket or managed-local endpoint
ignores it without treating unrelated HTTP credentials as a configuration
conflict.

`url` must be an absolute `http` or `https` base URL without userinfo, query or
fragment. A trailing slash is removed before appending `/api/v2`; an optional
path prefix is preserved. `socket` must resolve to an absolute filesystem path.
`queue` follows the Queue identifier grammar. `token` is a non-empty visible
ASCII string. Unknown/duplicate keys, unreadable or malformed TOML, wrong types
and empty values are `invalid_config`; values are never coerced.

Configuration is snapshotted when a Client is constructed. Importing the package
does not read it. Top-level functions construct one lazy default Client on first
use. Changing CWD, environment or files later does not mutate an existing
Client; construct another Client/process to re-resolve.

V2 implements no `config init`, `config set` or `config write` and never
automatically creates `config.toml`. The read-only diagnostic is:

```text
labtasker [--labtasker-root PATH] config show
```

It performs no network request, creates no file and starts no Server. It writes
one formatted JSON object. Examples of its discriminated shape are:

```json
{
  "connection": "socket",
  "managed_local": true,
  "labtasker_root": "/work/run/.labtasker",
  "database": "/work/run/.labtasker/server.db",
  "socket": "/tmp/labtasker-1000/root-012345.sock",
  "url": null,
  "queue": "default",
  "token_configured": false,
  "auto_start_local_server": false
}
```

For an external socket, `connection` remains `"socket"`,
`managed_local` is false, `socket` and `labtasker_root` are populated, and
database/url are null. For HTTP, `connection` is `"http"`, `url` and
`labtasker_root` are populated, and database/socket are null. Here the root is
the config/journal location, not a claim that the endpoint is locally managed.
`token_configured` is true only when the resolved endpoint is HTTP and a token
will be sent; the token value is never printed. Supplying the global auto-start
flag with a managed-local endpoint reports true while remaining side-effect free.
Combining it with an effective HTTP or external-socket endpoint is
`invalid_config`, just as for an operational command.

`ConfigError` retains `legacy_config_found` for the presence guard and
`invalid_config` for every other configuration failure. Details identify the
source and responsible field without exposing credentials. If
`<labtasker_root>/config.toml` is absent but
`<labtasker_root>/client.toml` exists, resolution stops with
`legacy_config_found` before endpoint use. V2 does not parse or migrate that v1
file.

Client config permissions are not enforced because portable permission checks do
not prevent accidental version-control disclosure. Remote deployments should
prefer `LABTASKER_TOKEN` or another secret injection mechanism. Tokens and
Authorization headers never appear in logs, errors, status output or runtime
metadata.
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
every process using that Labtasker root. Any later operation on that explicit instance fails
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

The public constructor is:

```python
Client(
    url=None,
    socket=None,
    labtasker_root=None,
    auto_start_local_server=False,
    token=None,
    queue=None,
)
```

`url` and `socket` are mutually exclusive explicit endpoint selectors.
`labtasker_root` independently selects config and journal location and may be
combined with either; when neither endpoint wins, it supplies the managed-local
default. V2 adds no `base_url` or `project` aliases. `None` means “not specified
at this source; continue through ordinary resolution.”
`auto_start_local_server` is a real boolean authority rather than a nullable
fallback field and is valid only when resolution selects managed local.

Task operations expose `queue: str | None = None`. `None` means "use the next
configured value", never a Queue literally named `None`. Queue resolution is:

```text
per-call argument
> explicit Client constructor value
> LABTASKER_QUEUE
> <labtasker_root>/config.toml
> built-in defaults
```

Endpoint and credential precedence is defined in section 9.1. The built-ins are
the exact-CWD Labtasker root, no token, no auto-start authority and Queue
`default`. V2 adds no profiles, user-level config merging, parent search,
VCS-root inference or automatic multi-file discovery. CLI and Python use the
same resolver. An unavailable explicit URL or socket never falls back to or
creates a managed local Server.

Resolution happens once when a `Client` instance is constructed. An explicit
`Client(...)` snapshots its effective endpoint, token, default Queue, config
root and auto-start authority in `__init__`, but performs no connection or
startup there.
The resolved snapshot is private implementation state, not a supported Client
property. `server_version` is the only public non-resource Client property.
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
list_workers / count_workers
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
list_workers  count_workers

loop  TaskArg  TaskInfo  task_info  finish  report_progress  report_worker_telemetry
cancellation_requested  set_force_stop_timeout

Task  TaskPage  Queue  BulkUpdateResult  LastError
WorkerObservation  WorkerPage  CountGroup  GroupCountPage
JSONValue  TaskStatus  TaskOrderField  TaskUpdate

LabtaskerError  ConfigError  TransportError  APIError
TransientError  TaskError  FatalWorkerError
```

There are no undocumented compatibility aliases in `__all__`. The Worker wire operations
`claim`, `heartbeat`, `progress`, `complete`, `fail` and `unclaim` are implementation details
of `loop` rather than public Python convenience functions. Their HTTP contract
remains documented for independent executor implementations; importing a private
client module is not a supported compatibility surface.

`Task` and `TaskPage` are frozen Pydantic models owned by the client package.
Task identity is consistently `task.id`, never `_id` or `task_id`. Top-level
attribute assignment is rejected so local mutation is not mistaken for a server
update; JSON objects in `args`, `metadata`, `result` and populated `progress` remain ordinary mutable
dicts rather than introducing deep immutable wrappers. `model_dump(mode="json")`
provides a JSON-ready representation. These response models use `extra="ignore"`
for additive Server compatibility while continuing to require and strictly parse
every known field; Client request and configuration models do not inherit this
leniency.

`list_tasks(limit=100, cursor=None)` fetches exactly one page. V2 does not add an
auto-fetching iterator, streaming list API or implicit "all" mode. Callers follow
`next_cursor` explicitly; server-side batch actions select and process their full
match set independently of Client pagination.

Ordinary Client requests default to a 15-second per-request timeout. This leaves
response margin beyond the shared strategy's independent five-second pool wait
and five-second SQLite busy limits. The local
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
response. It covers connection failures, explicitly authorized local daemon
startup/unavailability,
timeouts, invalid HTTP/JSON, a non-error success response that fails the documented
response schema, and an error response that lacks the required API error envelope.
Its stable CLI error code is `transport_error`; structured details may include a
non-sensitive operation, HTTP URL/status or local `state`, `labtasker_root`,
`database`, `socket` and `log` path, but never credentials or an unbounded
response body. V2 does not add a separate `ProtocolError` or daemon
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
  `args.*`, `metadata.*`, `result.*`, `progress.*` and `last_error.*`;
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
must be scalar JSON literals. All other operand shapes, including path-to-path,
list-on-the-left and constant-only membership, are `invalid_filter` errors. The
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

The documented additive progress fields are:

```text
progress
progress_updated_at
progress_attempt
```

They are all null before the active attempt reports progress. When populated,
`progress` is a strict JSON object, `progress_updated_at` is Server UTC time and
`progress_attempt` identifies the attempt that produced the retained snapshot.

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
Pydantic model. `routes` remains `list[str]`; `args`, `metadata`, `result` and populated `progress` remain ordinary
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
    name_fuzzy: str | None = None,
    filter: str | None = None,
    order_by: TaskOrderField = "created_at",
    descending: bool = True,
    limit: int = 100,
    cursor: str | None = None,
    queue: str | None = None,
) -> TaskPage
```

`status`, `name`, `name_fuzzy` and `filter` are optional and are ANDed when combined. `name`
means exact string equality. `name_fuzzy` is an optional, case-insensitive
name search: apply Unicode case folding to the name and query, split the query
on Unicode whitespace, and require each word to occur as a subsequence of the
name. Characters within a word must appear in order, but words are matched
independently and may overlap or occur in any order. Both `tr ev` and `EV TR`
match `train_model_eval`. Empty or whitespace-only search imposes no name
restriction; a non-empty search excludes null and empty names. Punctuation is
literal, with no regex, wildcard, fzf extended operators, smart-case rule, accent
normalization, or relevance ranking. Existing ordering remains unchanged.

The Server evaluates the predicate before pagination over the selected Queue;
list and count use the same predicate. Exact `name`, `name_fuzzy`, `status`, and
`filter` combine with AND. `filter='name == "..."'` remains strict equality;
this change adds no fuzzy expression function. CLI list and count expose
`--name-fuzzy`, and Python exposes `name_fuzzy` on both Client and module functions.
The raw `name_fuzzy` input participates in cursor selection identity, so changing
its case, whitespace, or word order requires starting a new pagination query.

Listing has no `task_id` shortcut because
`get_task()` is the canonical ID lookup. `TaskPage` is a frozen client-owned
Pydantic model containing `items: list[Task]` and `next_cursor: str | None`.

HTTP uses:

```http
GET /api/v2/queues/{queue}/tasks?status=...&name=...&name_fuzzy=...&filter=...&order_by=created_at&descending=true&limit=100&cursor=...
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
    name_fuzzy: str | None = None,
    filter: str | None = None,
    queue: str | None = None,
    group_by: Sequence[str] | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> int | GroupCountPage
```

It uses exactly the same `status`, exact `name`, `name_fuzzy`, and `filter` selection semantics
as `list_tasks`, with supplied predicates ANDed. It has no `order_by` or direction.
Optional grouping and group pagination follow section 8.6. Ungrouped HTTP uses:

```http
GET /api/v2/queues/{queue}/tasks/count?status=...&name=...&name_fuzzy=...&filter=...
```

and returns one strict object:

```json
{"count": 123}
```

The Python method unwraps that object to an ordinary non-negative `int`. The CLI
mirrors the four selectors and Queue:

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
and change inspection noisy. Progress reports likewise update only
`progress_updated_at`, not the lifecycle-oriented `updated_at`.

## Decision log

| Date | Decision |
|---|---|
| 2026-09-18 | Require POSIX advisory file locking for every Server transport and lifecycle mode, including foreground HTTP. Reject all operational `labtasker-server` commands on Windows before root, database, listener or process side effects while keeping help and version inspection available. Keep the ordinary HTTP Client and Python Worker best effort on Windows; they connect to a Server running on a POSIX host. This supersedes the earlier Windows best-effort Server classification. |
| 2026-09-18 | Keep ordinary Client request timeout at 15 seconds, including response margin beyond the shared strategy's separate five-second pool and busy waits. Keep resolved Client configuration private, with `server_version` as the only public non-resource property. For false-default authority, destructive and lifecycle booleans, expose only positive `--auto-start-local-server`, `--cascade`, `--daemon` and `--force` flags; retain the meaningful `--descending` / `--ascending` ordering pair. |
| 2026-09-18 | Keep `finish()`, `report_progress()` and `report_worker_telemetry()` as Python execution-context helpers without parallel CLI commands. Remove `labtasker progress` and `labtasker worker telemetry`; Command Workers continue to use process exit status for ordinary completion, while Python launched by a Command Worker may import the helpers when runtime reporting is needed. |
| 2026-09-17 | Add `--database-filesystem auto|local|shared`. Resolve known local storage to WAL/FULL, known shared storage to DELETE/EXTRA plus one `QueuePool` connection whose checkout serializes all transactions, and unknown storage to the shared strategy with a warning. Treat detection as a guard rather than a correctness proof; shared deployments must still guarantee one external Server owner. |
| 2026-09-17 | Replace database-inode ownership with permanent per-user host-local `/tmp` advisory sidecars keyed separately by canonical Labtasker root, socket path and database path. Hold applicable locks for process lifetime without TTL or stealing; provide no cross-user/cross-node exclusion and treat hard-link/inconsistent-path aliases as unsupported misuse. |
| 2026-09-17 | Unify public Server launch as `serve`/`serve --daemon` with independent `--connection http|socket`, `--labtasker-root` and `--database`; remove public `start`. Require every public `serve` invocation to select `http` or `socket` explicitly, with no transport default; host/port and socket defaults apply only after that selection, while managed auto-start privately selects socket. Make detached launch idempotent only for matching non-secret effective configuration and require explicit stop before a conflicting relaunch or token rotation. The launcher inherits only the root lock; the child acquires its socket/database locks. |
| 2026-09-17 | Make Client local Server creation opt-in through invocation-scoped `--auto-start-local-server` or `Client(auto_start_local_server=True)`. Resolve the independent config/journal root from explicit input, `LABTASKER_ROOT` or exact CWD without parent/VCS search; resolve URL/socket from the first explicit, environment or root-config endpoint layer and otherwise use managed local. Default Clients only connect, and shadowed endpoint layers do not conflict. |
| 2026-09-17 | Keep daemon state to `running`, `starting`, `unhealthy` and `stopped`. Add no persistent automatic-start throttle, retry timestamp, backoff/stale/unmanaged state or authenticated management probe; stale artifacts are internal cleanup and foreground Servers are outside daemon management. |
| 2026-09-17 | Keep auto-started daemons alive until explicit stop, create operational state but no config, add no config-writing command or managed-instance marker, and require documentation plus the public Agent Skill to carry the same precedence and behavior matrices. |
| 2026-09-17 | Bound the v2.5 ownership migration: the first sidecar-owning release also retains the legacy database-inode lock for effective local storage and emits a deterministic deprecation diagnostic when a legacy owner is detected; shared and undiscoverable custom legacy Servers require stop-before-upgrade. Bind daemon readiness to a private child/generation confirmation emitted only after Uvicorn establishes the listener, then verify public health, so another Server on the requested address cannot satisfy readiness. |
| 2026-09-17 | Make claim replay recognition explicitly bounded to an active run or the one retained latest-terminal slot. Require a fresh private `run_id` for every new logical claim, permit an overwritten arbitrarily old token to be treated as new, and add no permanent Run history or used-token tombstone table. |
| 2026-09-17 | Keep platform-specific filesystem classification in the short-lived hidden Server coordinator rather than duplicating it into the Client distribution. Permit that coordinator process after an explicitly authorized managed-local connection failure, but reject shared or unknown storage before creating the root, database, runtime metadata or daemon child. |
| 2026-09-16 | Add strict invocation-scoped Worker metadata and a synchronous replace-only latest telemetry snapshot for observing resource placement and load distribution. Support Worker filtering over fixed fields plus `metadata.*` and `telemetry.*`, while keeping grouping fixed to `route`/`status` and adding no automatic collection, merge, history, retry, throttling or scheduling effect. Command descendants and distributed ranks share one Worker ID and use last-committed replacement semantics. This supersedes the historical exclusion of Worker metadata and resource observations. |
| 2026-09-13 | Add one run-fenced latest `progress` object for dashboard visibility and external early-stop decisions. Reports replace rather than merge, do not renew leases or change Task lifecycle/`updated_at`, retain the last accepted snapshot after run finalization, clear it on the next claim, and carry Server-owned report time and attempt. Expose best-effort Python/Command helpers and dynamic `progress.*` filtering without adding history, automatic throttling or a Server-side early-stop policy. |
| 2026-09-12 | Support all three distributions on Python 3.10+; define runtime lower bounds as release-tested compatibility floors, keep automated Python updates lockfile-only, derive and verify exact direct minima without a second lock across Python 3.10 through 3.14, test the Python 3.10 Client against a fresh latest-allowed resolution, and smoke-test independent and full wheel installations across the same Python matrix. |
| 2026-08-28 | Expose eager root `--version` options on both runtime executables, reporting the owning runtime distribution and package version on stdout without configuration, network or local-daemon side effects; list the option in root help without embedding the current version there. |
| 2026-08-28 | Make stdout the single machine-readable response channel for finite Client commands: successful data or a handled `LabtaskerError` envelope is written there, diagnostics remain on stderr, and exit status distinguishes success from failure. Keep usage errors and continuing `loop` failures as natural-language stderr, with no output-mode flag or response wrapper. |
| 2026-09-09 | Add supplementary loop-scoped Worker observations with independent best-effort reporting, 60-second renewal and 300-second expiry; preserve Task authority and the phase-specific network-resilience boundary in section 3.0. Extend existing Task counts and new Worker counts with restricted ordered grouping through HTTP, Python and CLI (section 8.6). This supersedes historical decisions excluding Worker observations and grouping; routes remain labels and no remote process control is added. |
| 2026-08-24 | Standardize finite diagnostics as `[labtasker]` or `[labtasker-server]`, emit one explicit successful Client connection line with local/remote Server kind and Unix/HTTP(S) transport, and give default long-running Worker and Server logs millisecond UTC timestamps, levels and component prefixes. |
| 2026-08-21 | Make CWD-bound local mode the default endpoint when no URL is configured: store the durable SQLite database under that exact canonical CWD, derive an owner-only tmux-style `/tmp/labtasker-UID` Unix socket without parent/VCS discovery, and let every explicit HTTP URL disable all local process management. Superseded on 2026-09-17 by independent Labtasker-root resolution and opt-in startup. |
| 2026-08-21 | Make local endpoint selection and daemon transitions unconditionally visible on stderr for CLI and direct Python use, while preserving requested data on stdout and never printing credentials. |
| 2026-08-21 | Use the actual database inode's inherited ownership FD as both local startup election and lifetime ownership, with no separate startup lock or readiness pipe; poll socket health for at most 30 seconds and never break or automatically kill a live owner. Superseded on 2026-09-17 by separate host-local root, socket-path and canonical database-path sidecars. |
| 2026-08-21 | Reuse ephemeral per-CWD runtime metadata for a fixed one-automatic-launch-per-10-seconds throttle; add no durable startup-state file, failure counter, exponential backoff, probation/stability phases or delayed reset task. Superseded on 2026-09-17 by explicit auto-start authority with one attempt per invocation and root-lock concurrency, without a persistent throttle. |
| 2026-08-21 | Detach the local daemon from its launching terminal and SSH connection, give it no idle shutdown, and stop it only explicitly or through ordinary process/machine failure; expose CWD-addressed `start`, `status`, `stop [--force]` and `logs` commands, make stop one-shot, and keep explicit HTTP `serve` foreground and user-managed. Superseded on 2026-09-17 by unified `serve [--daemon]` and root-addressed management. |
| 2026-08-21 | Permit automatic recovery only for the default Unix-socket transport and preserve every operation's existing uncertain-outcome/retry rules; an explicit HTTP URL never causes Client-owned Server startup, restart or shutdown. Superseded on 2026-09-17 by invocation-scoped opt-in local auto-start; the retry boundary remains unchanged. |
| 2026-08-21 | Publish `labtasker` as the full-install metapackage over independent `labtasker-client` and `labtasker-server` runtime distributions; use direct `labtasker-client` installation for the slim/remote case because extras cannot subtract default dependencies. |
| 2026-08-21 | Reject the Command Worker with built-in `NotImplementedError` on Windows before Client construction because the current executor cannot uphold whole-process-group cancellation; keep the CLI diagnostic readable without adding a public platform-error type, retain Client, Server and Python Worker as Windows best effort, and retain Command Worker as macOS best effort. The Server portion is superseded by the 2026-09-18 POSIX-only Server decision. |
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
| 2026-08-20 | Name the explicit Client constructor `Client(url=None, token=None, queue=None)` so connection vocabulary matches config/env; add no `base_url` alias. Superseded on 2026-09-17 by adding `socket`, `labtasker_root` and `auto_start_local_server`; `base_url` remains absent. |
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
| 2026-08-20 | Bound list pages to 1 to 1000 Tasks with default 100; use a stateless opaque cursor tied to the Queue, selection and ordering inputs while allowing the next page size to change. |
| 2026-08-20 | Make CLI data output two-space-indented UTF-8 JSON with no ANSI styling; `task list` always returns the `TaskPage` schema and has no table, pager or IDs-only output mode. |
| 2026-08-20 | Make `last_route`, `started_at` and `finished_at` filterable; fixed nullable built-ins always exist, so test population with `field != None` rather than `exists(field)`. |
| 2026-08-20 | Support one explicitly allowlisted built-in scalar `order_by` field plus `descending`, sort nulls last, default to `created_at` descending, and add `id` as the stable cursor tie-breaker; omit JSON and multi-field sorting. |
| 2026-08-20 | Add no stored or virtual duration field, filter or ordering; callers derive the coarse latest-run duration from a non-null timestamp pair. |
| 2026-08-20 | Use the same resource-qualified Python names on top-level functions and Client methods; keep `submit_task`/`list_tasks` etc. and add no short aliases. |
| 2026-08-20 | Return client-owned frozen Pydantic `Task`/`TaskPage` models with `task.id`; keep nested JSON dicts ordinary and provide `model_dump(mode="json")`. |
| 2026-08-20 | Fetch exactly one explicit cursor page from `list_tasks`; add no auto iterator, stream or implicit-all mode, and keep server-side batch selection independent of pagination. |
| 2026-08-20 | Resolve `queue=None` through per-call, Client, environment, current-project config and finally `default`; treat Queue as a configurable default rather than auth identity. |
| 2026-08-20 | Use only `LABTASKER_URL`, `LABTASKER_TOKEN` and `LABTASKER_QUEUE` as user-facing Client configuration variables; read only CWD `.labtasker/config.toml`, with no profiles, parent search, user config or multi-file merge. Superseded on 2026-09-17 by `LABTASKER_SOCKET`, `LABTASKER_ROOT` and root-selected config while retaining single-file/no-parent discovery. |
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
| 2026-08-20 | Define `.labtasker/config.toml` as a flat strict three-string TOML file (`url`, `queue`, `token`) read by stdlib `tomllib`; reject unknown/duplicate/empty/ill-typed values and add no YAML/config framework. Superseded on 2026-09-17 only to add mutually exclusive `socket`; strict flat TOML remains. |
| 2026-08-20 | Make every client config key optional, including `token`; an omitted token sends no Authorization header, while a present empty token remains invalid. |
| 2026-08-20 | If the new CWD config is absent but v1 `.labtasker/client.toml` exists, fail with `legacy_config_found` before all other resolution; do not parse or migrate the legacy file. |
| 2026-08-20 | Give Queue and route one case-preserving, case-sensitive 1 to 128 character ASCII identifier grammar, `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`, with no normalization. |
| 2026-08-20 | Limit `labtasker-server serve` to host, port and SQLite path flags with defaults `127.0.0.1:8000` and `.labtasker/server.db`; read the token only from `LABTASKER_SERVER_TOKEN` and leave process supervision external. Fully superseded on 2026-09-17 by unified `serve [--daemon]`, independent connection selection and root-addressed management. |
| 2026-08-20 | Automatically initialize or forward-migrate known v2 Alembic revisions before listening; reject newer/unknown/failed schemas, add no migration CLI or automatic backup, and do not treat v1 MongoDB as an implicit startup migration. |
| 2026-08-20 | Fix SQLite to WAL, foreign keys, 5000 ms busy timeout and FULL synchronous durability; apply per-connection settings and fail startup if required values cannot be verified. Superseded on 2026-09-17 for shared storage by DELETE/EXTRA and one pooled connection whose checkout serializes all transactions; the local settings remain. |
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
| 2026-08-19 | Require heartbeat for every claimed run and use heartbeat loss as the only recovery mechanism when a Worker stops responding. |
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
