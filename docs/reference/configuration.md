# Configuration

Labtasker separates Client endpoint selection from Server operation. A default
Client selects one exact managed-local root and tries its Unix socket, but it
does not create files or start a process unless that invocation explicitly has
auto-start authority.

## Client resolution

The Labtasker root is resolved first:

1. `Client(labtasker_root=...)` or global CLI `--labtasker-root`;
2. `LABTASKER_ROOT`;
3. the exact canonical `<current-directory>/.labtasker`.

Labtasker never searches a parent directory, repository root, or another config
location. The root selects the one optional `config.toml` and the Worker journal
directory. It is still resolved when the selected endpoint is HTTP or an
external socket.

The endpoint is then selected as one atomic URL-or-socket layer:

1. explicit `Client(url=...)` or `Client(socket=...)`;
2. `LABTASKER_URL` or `LABTASKER_SOCKET`;
3. `url` or `socket` in `<labtasker-root>/config.toml`;
4. the managed-local socket derived from the root.

Supplying both alternatives in the same layer is an error. A winning higher
layer shadows both alternatives below it, so a one-off explicit URL does not
conflict with a stored socket. An unavailable explicit endpoint never falls
back to managed local.

Queue and token values use explicit, environment, config, then default
precedence independently:

| Setting | Environment | Config key | Default |
| --- | --- | --- | --- |
| endpoint | `LABTASKER_URL` / `LABTASKER_SOCKET` | `url` / `socket` | managed local |
| root | `LABTASKER_ROOT` | — | exact `<CWD>/.labtasker` |
| Queue | `LABTASKER_QUEUE` | `queue` | `default` |
| HTTP token | `LABTASKER_TOKEN` | `token` | unset |

A config file is flat and strict:

```toml
url = "https://labtasker.example.com"
queue = "experiments"
token = "secret"
```

Use `socket = "/absolute/path/to/server.sock"` instead of `url` for an
external Unix socket. Unknown keys, duplicate endpoint selectors, empty values,
malformed TOML, and v1 `.labtasker/client.toml` are errors. Tokens contain only
visible ASCII and are sent only to HTTP endpoints; socket connections have no
application-level token.

`labtasker config show` resolves these sources without contacting a Server,
creating the root, or starting a process. It prints whether a token would be
used, never the token value.

## Managed local startup

With no configured URL or socket, the Client uses the root-derived owner-only
Unix socket. A request normally only tries that socket. Authorize startup for a
single CLI invocation or Python Client when needed:

```bash
labtasker --auto-start-local-server task list
```

```python
from labtasker import Client

with Client(auto_start_local_server=True) as client:
    queues = client.list_queues()
```

Repeated and concurrent authorized calls are idempotent: one matching daemon is
started or reused. Auto-start creates operational state under the root but no
`config.toml`. It is valid only for the managed-local endpoint and only when the
Server classifies the database filesystem as known local storage. Shared or
unknown storage requires an explicitly operated Server.

Without startup authority, a missing daemon produces a `TransportError` that
names the resolved root and socket and suggests the startup flag, an explicit
`serve`, or a configured endpoint. Importing `labtasker`, constructing a Client,
displaying help, and running `config show` remain side-effect free.

Configuration is fixed when a Client is constructed. A later `chdir()`, config
edit, or environment change does not retarget it. Top-level functions lazily
share one default Client; use explicit Clients for several targets:

```python
from labtasker import Client

with Client(url="https://example.com", queue="paper", token=token) as client:
    client.submit_task({"prompt": "a ceramic fox"}, routes=["sdxl"])
```

## Server operation

The Server requires a POSIX platform with advisory file locking. All Server
transports and lifecycle modes, including foreground HTTP, are unsupported on
Windows. `labtasker-server --help`, command help, and `--version` remain
available there, but operational commands fail before creating a root, opening
SQLite, binding a listener, or starting a process. Windows Clients and Python
Workers connect to an HTTP Server running on a POSIX host.

Every public Server launch explicitly selects its transport:

```bash
labtasker-server serve --connection socket [OPTIONS]
labtasker-server serve --connection http [OPTIONS]
```

`--connection` has no default. Common defaults are exact
`CWD/.labtasker` for `--labtasker-root`, `<root>/server.db` for `--database`,
`auto` for `--database-filesystem`, and foreground operation. `--daemon` changes
only foreground versus detached lifecycle; it does not change the transport.

Socket mode derives an owner-only runtime socket from the canonical root unless
`--socket` is supplied. HTTP mode defaults to `127.0.0.1:8000`. `--host` and
`--port` are HTTP-only; `--socket` is socket-only.

Start or reuse a detached local daemon explicitly:

```bash
labtasker-server serve \
  --connection socket \
  --daemon \
  --labtasker-root .labtasker
```

Manage only that exact root:

```bash
labtasker-server status --labtasker-root .labtasker
labtasker-server logs --labtasker-root .labtasker
labtasker-server stop --labtasker-root .labtasker [--force]
```

There is no public `start` command. Detached `serve` is idempotent only when the
effective non-secret configuration matches the running daemon. A conflict asks
the operator to stop the existing daemon before relaunching it. `status` is
read-only JSON; `logs` prints the complete current log without following it. A
normal `stop` waits up to 30 seconds and never sends SIGKILL; `--force` may do so
only after rechecking process identity.

For an HTTP Server:

```bash
LABTASKER_SERVER_TOKEN=secret \
labtasker-server serve \
  --connection http \
  --host 0.0.0.0 \
  --port 8000 \
  --database /data/labtasker.db \
  --database-filesystem auto
```

The authentication token is read only from `LABTASKER_SERVER_TOKEN`; there is no
token CLI flag. Loopback and `localhost` binds may omit it. A non-loopback bind
requires it. `/health` and `/openapi.json` stay unauthenticated; application API
calls use the one Server-wide bearer token. Labtasker does not provide users,
roles, per-Queue ACLs, or authenticated Worker identities.

## SQLite filesystem strategies

Run exactly one Server process per database file. The filesystem strategy
controls SQLite safety settings, not the Client transport:

| Strategy | Journal | Sync | Connections and transactions |
| --- | --- | --- | --- |
| `local` | WAL | FULL | ordinary local pool; SQLite serializes writes |
| `shared` | DELETE | EXTRA | one connection; every read and write transaction serialized |
| `auto` | detected | detected | known local uses `local`; known shared and unknown use `shared` |

For `auto`, the Server inspects the database path or its nearest existing parent.
Linux reads the longest matching mount from `/proc/self/mountinfo`; macOS reads
the longest matching entry from `mount` output. The current conservative type
sets are:

| Classification | Recognized filesystem types |
| --- | --- |
| known local | `apfs`, `btrfs`, `ext2`, `ext3`, `ext4`, `f2fs`, `hfs`, `hfsplus`, `jfs`, `overlay`, `tmpfs`, `ufs`, `xfs`, `zfs` |
| known shared | `beegfs`, `ceph`, `cifs`, `fuse.sshfs`, `gpfs`, `lustre`, `nfs`, `nfs4`, `smbfs`, `wekafs` |

An unavailable or unlisted type is unknown. Unknown auto-detection emits a
warning and selects `shared`; it never guesses local. Explicit `local` or
`shared` bypasses detection and is the operator override. Detection is only a
guard: mount aliases, vendor-specific clients, containers, and filesystem
configuration can hide the real durability or locking behavior.

`local` uses WAL for ordinary local concurrency and `synchronous=FULL`.
`shared` uses the rollback journal in `DELETE` mode, avoiding WAL's long-lived
shared-memory coordination files, and `synchronous=EXTRA`, which adds the
directory durability step associated with deleting the rollback journal. These
settings reduce assumptions about shared storage; they cannot repair broken
remote locking, `fsync`, network partitions, or split brain.

The shared SQLAlchemy pool is exactly `pool_size=1`, `max_overflow=0`, and
`pool_timeout=5`. Checkout of that single connection serializes read, write,
health, startup-recovery, and expiry transactions. A request that cannot check
out the connection within five seconds receives retryable `503 database_busy`;
after checkout, SQLite has a separate 5000 ms lock wait. This protects
correctness but does not increase SQLite write throughput. FastAPI endpoints and
SQLAlchemy remain synchronous; async HTTP is a later profiling decision, not a
shared-storage safety requirement.

Every connection enables foreign keys and a 5000 ms SQLite busy timeout. One
host-local sidecar lock owns the canonical database path for the Server process;
detached daemons additionally own their exact root, and Unix Servers own their
socket path. These locks prevent ordinary same-user duplicates on one host, not
cross-host split brain.

Sidecar locks live in the owner-only per-user runtime directory under `/tmp`, are
keyed by hashes of canonical paths, have no TTL, and are never stolen or deleted
as part of normal cleanup. The kernel releases the advisory lock when the owning
process exits. During the bounded v2.5 transition, effective `local` mode also
retains the legacy database-inode lock; shared mode deliberately does not depend
on that remote-file lock. Stop an old Server cleanly before upgrading a shared
database.

Root and database symlink aliases resolve to their canonical targets before
locking. For a Unix socket, only the parent is canonicalized; the final entry is
kept for validation and a symlink there is rejected. The per-user runtime
directory itself must also be an owner-only real directory, not a symlink.

For one cluster node using a shared database and same-host Clients, the root and
database remain independent and a detached socket Server is valid:

```bash
labtasker-server serve \
  --connection socket \
  --daemon \
  --labtasker-root /var/tmp/my-run/labtasker \
  --database /shared/project/server.db \
  --database-filesystem shared
```

For Clients on other nodes, run the same single owner with `--connection http`
instead. In both cases an external supervisor or operational policy must ensure
that no other node starts a Server for the same database. Labtasker provides no
distributed owner lease or split-brain recovery.

Labtasker initializes a fresh database and applies known v2 migrations before
listening. Unknown or newer schemas fail clearly. Store large artifacts outside
SQLite and record paths or URLs in Task data.
