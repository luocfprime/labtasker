# Deployment and capability decisions

Choose the smallest supported path that fits the deployment. A mechanism being
possible with custom code does not make it a Labtasker interface.

## Choose the endpoint

| Situation | Canonical path |
| --- | --- |
| One POSIX project on one machine | Install `labtasker` and use automatic local mode from the project directory. |
| Several machines or users share work | Run one explicit HTTP Server and point every Client and Worker at it. |
| Windows Client or Python Worker | Use an explicit HTTP Server; automatic local mode is unsupported. |
| Client-only environment | Install `labtasker-client`. |
| Dedicated Server environment | Install `labtasker-server`. |
| User wants to operate a Unix socket directly | Do not. The local socket is private automatic-local transport, not a configurable public Server interface; use HTTP for a self-managed Server. |

The `labtasker` convenience package installs matching Client and Server
distributions and is the default for local use. All packages require Python 3.11
or newer.

Automatic local mode is selected only when no URL is configured. It is bound to
the exact canonical current working directory when the Client is constructed;
it does not search parent directories or a repository root. Importing
`labtasker`, constructing a Client, displaying help, and running
`labtasker config show` do not start or contact a Server. The first real Task or
Queue request does.

Local management commands address the current directory's automatic daemon:

```bash
labtasker-server status
labtasker-server logs
labtasker-server start
labtasker-server stop
```

Ordinary local use should rely on automatic startup. `start` is for explicit
diagnosis or management, not required setup. A later local operation may restart
an intentionally stopped daemon.

## Run a shared HTTP Server

Run the Server in the foreground under a process supervisor owned by the user:

```bash
# Configure LABTASKER_SERVER_TOKEN through the supervisor's secret mechanism.
labtasker-server serve \
  --host 0.0.0.0 \
  --port 8000 \
  --database /data/labtasker.db
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
does not provide users, roles, separate user tokens, per-Queue ACLs, or Worker
identity. A Queue is a scheduling namespace, not a security boundary. Use
separate Server trust domains or external network/authentication controls when
different groups require isolation.

Explicit constructor arguments override environment variables, which override
the config file, which overrides defaults. A token without an explicit URL is
invalid because local mode has no authentication. Do not commit tokens or put
them in commands, Task data, or logs.

Top-level Python functions share one lazily created default Client. When one
process must operate against several endpoints or Queues, construct explicit
`Client(url=..., queue=..., token=...)` instances instead of changing global
environment variables between calls.

An explicit HTTP Client never starts, stops, restarts, or otherwise supervises
the Server. Run exactly one Server process for each SQLite database file; do not
use multiple Uvicorn workers or multiple hosts against the same file. Store the
database on storage whose local file locking has the required semantics.

## Respect platform boundaries

- Linux is the fully supported and release-gated platform.
- Ordinary HTTP Client, foreground Server, and Python Worker behavior is best
  effort on macOS and Windows.
- Automatic local mode requires POSIX and is unsupported on Windows.
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
| Register Workers or report which routes are online | No. The Server stores Tasks and active runs, not a Worker or capacity registry. |
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
