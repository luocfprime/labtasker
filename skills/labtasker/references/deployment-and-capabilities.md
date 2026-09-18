# Deployment and capability decisions

Choose the smallest supported path that fits the deployment. A mechanism being
possible with custom code does not make it a Labtasker interface.

## Choose the endpoint

| Situation | Canonical path |
| --- | --- |
| One POSIX project on one machine | Install `labtasker`; explicitly authorize the managed-local daemon once, then use its root-derived socket. |
| Several machines or users share work | Run one explicit HTTP Server and point every Client and Worker at it. |
| SQLite database on NFS, WekaFS, Lustre, or uncertain storage | Run one explicit Server with `--database-filesystem shared`; externally guarantee one owner across nodes. |
| Windows Client or Python Worker | Use an explicit HTTP Server; managed local mode is unsupported. |
| Client-only environment | Install `labtasker-client`. |
| Dedicated Server environment | Install `labtasker-server`. |
| One same-user host needs an explicitly operated Unix endpoint | Run `serve --connection socket`; use its root-derived default or an explicit `--socket`. |

The `labtasker` convenience package installs matching Client and Server
distributions and is the default for local use. All packages require Python 3.10
or newer.

Managed local mode is selected only when no URL or socket is configured. It is
bound to the exact canonical Labtasker root when the Client is constructed. The
root resolves from explicit input, `LABTASKER_ROOT`, then exact
`CWD/.labtasker`; it does not search parent directories or a repository root.
Importing
`labtasker`, constructing a Client, displaying help, and running
`labtasker config show` do not create state, start a process, or contact a
Server. Ordinary operations only connect. `--auto-start-local-server` or
`Client(auto_start_local_server=True)` explicitly authorizes one managed-local
Client invocation to start or recover the standard daemon.

Local management commands address one exact root:

```bash
labtasker-server status --labtasker-root .labtasker
labtasker-server logs --labtasker-root .labtasker
labtasker-server stop --labtasker-root .labtasker
```

There is no public `start`. To launch directly, use
`labtasker-server serve --connection socket --daemon --labtasker-root
.labtasker`. Repeating an identical detached launch is idempotent. A conflicting
launch fails and requires an explicit stop first.

## Run a shared HTTP Server

Run the Server in the foreground under a process supervisor owned by the user:

```bash
# Configure LABTASKER_SERVER_TOKEN through the supervisor's secret mechanism.
labtasker-server serve \
  --connection http \
  --host 0.0.0.0 \
  --port 8000 \
  --database /data/labtasker.db \
  --database-filesystem shared
```

A non-loopback bind requires `LABTASKER_SERVER_TOKEN`; there is no token CLI
flag. Configure every Client and Worker with the matching endpoint and token:

```bash
export LABTASKER_URL=http://server.example:8000
export LABTASKER_QUEUE=default
# Supply LABTASKER_TOKEN through the environment's secret mechanism.
```

The same fields may be placed in the current directory's strict
`.labtasker/config.toml`:

```toml
url = "http://server.example:8000"
queue = "default"
```

The config file also accepts `token`, but prefer a protected environment or
secret manager so a credential is not committed with the project.

Authentication is one Server-wide bearer token for every application API call;
`/health` and `/openapi.json` remain unauthenticated for discovery. Labtasker
does not provide users, roles, separate user tokens, per-Queue ACLs, or
authenticated Worker identities. Observation IDs identify loop invocations,
not security principals.
A Queue is a scheduling namespace, not a security boundary. Use
separate Server trust domains or external network/authentication controls when
different groups require isolation.

Endpoint selection is atomic: explicit URL/socket overrides the environment
URL/socket layer, which overrides the root config URL/socket layer, then managed
local. Queue and token follow ordinary explicit, environment, config, default
precedence. Tokens are sent only for HTTP. Do not commit tokens or put them in
commands, Task data, or logs.

Top-level Python functions share one lazily created default Client. When one
process must operate against several endpoints or Queues, construct explicit
`Client(url=..., queue=..., token=...)` instances instead of changing global
environment variables between calls.

An explicit HTTP or socket Client never starts, stops, restarts, or otherwise
supervises the Server. Every public `serve` requires `--connection http|socket`;
`--daemon` changes only lifecycle. Run exactly one Server process for each
SQLite database file and do not use multiple Uvicorn workers.

`--database-filesystem auto|local|shared` selects the SQLite strategy. Local
uses WAL/FULL. Shared uses DELETE/EXTRA, one pooled connection, and serializes
all read and write transactions. Auto maps recognized local filesystems to
local, recognized NFS/WekaFS/Lustre-style storage to shared, and unknown storage
to shared with a warning. Detection is not a correctness proof: the operator
must still prevent cross-node duplicate Servers and validate storage locking and
durability behavior.

## Diagnose version differences

`Client.server_version` reports the normalized Server package version from the
latest ordinary API response, or `None` if its version header is absent or
invalid. Reading it makes no request; `/health` is not a feature handshake.
When the Server is older than the Client, each Client emits an advisory warning
to stderr once per distinct older version. The warning does not change success,
exit status, retries, or Worker execution, and does not prove why a request failed.
There is no automatic feature fallback or generic version gate. Inspect the
actual API error when an operation fails; upgrade a user-owned deployment when
needed, respecting shared Server ownership. A missing version is unknown,
not evidence of incompatibility.

## Respect platform boundaries

- Linux is the fully supported and release-gated platform.
- Ordinary HTTP Client, foreground Server, and Python Worker behavior is best
  effort on macOS and Windows.
- Managed local mode and Unix-socket Servers require POSIX and are unsupported
  on Windows.
- Command Workers are unsupported on Windows because Labtasker cannot guarantee
  whole-process-tree cancellation there. They fail before Server access, Task
  claim, journal creation, or child startup.
- Single-node `torchrun` and Accelerate use the Command Worker boundary and are
  therefore also unsupported on Windows.

Do not recommend trying an explicitly unsupported path and waiting for a system
call to fail. Choose the HTTP/Python alternative or move command execution to a
supported POSIX host.

## Answer capability questions directly

| Request | Labtasker answer |
| --- | --- |
| Allocate, reserve, or discover a free GPU | No. The user, shell, or cluster scheduler starts Workers on allocated resources. |
| See online Workers, route presence, or user-reported latest resource details | Yes. Bundled Workers automatically report expiring observations and may include static metadata plus latest telemetry; use `list_workers` / `count_workers` or `worker list` / `worker count`. Read [observations-and-counts.md](observations-and-counts.md). This is approximate observation, not discovered capacity, allocation, or process control. |
| Schedule machines, pods, or multi-node rendezvous | No. Use SLURM, Kubernetes, Koala, or another external scheduler. |
| Express Task dependencies or a workflow DAG | No. Use a workflow engine and submit independent leaves to Labtasker. |
| Store checkpoints, images, videos, or datasets | No. Use project or artifact storage and record references in Task data. |
| Run one Task with single-node `torchrun` or Accelerate | Yes, through one outer Command Worker on supported POSIX platforms. |
| Provide an asynchronous Python Client | No. The public Python API is synchronous. |
| Run several Tasks concurrently in one Worker process | No. Start more Worker processes; each executes at most one Task at a time. |
| Keep an AI agent in the runtime loop | No. Agents may configure and operate Labtasker, but Worker execution is autonomous. |

Labtasker coordinates independent work after processes exist. If the main
problem is resource allocation, dependent pipelines, or artifact management,
select another primary tool rather than building those concepts around
Labtasker.
