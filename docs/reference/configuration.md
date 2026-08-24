# Configuration

On POSIX systems, most local users need no configuration: Labtasker selects the
current project, starts its local Server when first needed, and uses Queue
`default`. Configure a Client to select another Queue, connect to an explicitly
managed HTTP Server, or control multiple targets from one process. Windows does
not provide automatic local mode and therefore requires an explicit HTTP URL.

## Client resolution

Client settings use this precedence, independently for each field:

1. explicit `Client(...)` or function argument;
2. environment variable;
3. `.labtasker/config.toml` in the current working directory;
4. built-in default.

```toml
url = "https://labtasker.example.com"
queue = "experiments"
token = "secret"
```

| Setting | Environment | Default |
| --- | --- | --- |
| `url` | `LABTASKER_URL` | local mode in the canonical current directory |
| `queue` | `LABTASKER_QUEUE` | `default` |
| `token` | `LABTASKER_TOKEN` | unset |

The file is strict: unknown keys, empty values, malformed TOML, and v1
`.labtasker/client.toml` are errors. A token without an explicit URL is invalid;
local mode has no authentication. `labtasker config show` prints the
discriminated local/HTTP endpoint and only reports whether a token is configured.
It performs no network request and creates no files.

With no effective URL, Client construction snapshots the exact canonical CWD.
The first real request starts or connects to that directory's detached Server
through `/tmp/labtasker-UID/{sha256-of-directory}.sock`. Durable state remains in
`CWD/.labtasker/server.db`. The `[labtasker] connected` diagnostic on stderr
explicitly states `server=local`, `transport=unix`, the selected directory,
database and socket; daemon transitions are also visible. Labtasker never
searches a parent directory or VCS root, and a later `chdir()` does not retarget
an existing Client.

An explicit constructor, environment, or config-file URL selects ordinary HTTP
mode and disables all daemon startup, recovery, and stop behavior. Operating
that Server is then the user's or process supervisor's responsibility.

Configuration is loaded when a `Client` is first instantiated. Top-level helper
functions lazily share one default Client; use an explicit Client when different
targets are needed in one process:

```python
from labtasker import Client

with Client(url="https://example.com", queue="paper") as client:
    client.submit_task({"prompt": "a ceramic fox"}, routes=["sdxl"])
```

## Server configuration

The current directory's default local daemon can be inspected and managed with:

```bash
labtasker-server start
labtasker-server status
labtasker-server logs
labtasker-server stop [--force]
```

It has no idle shutdown. `status` is read-only JSON; `logs` prints the complete
current log without following it. A normal `stop` waits up to 30 seconds and
never sends SIGKILL. `--force` only signals the same reverified daemon after that
graceful deadline.

For an explicitly operated foreground HTTP Server:

```bash
labtasker-server serve \
  --host 127.0.0.1 \
  --port 8000 \
  --database .labtasker/server.db
```

The authentication token is read only from `LABTASKER_SERVER_TOKEN`; there is no
token CLI flag. Loopback and `localhost` binds may omit it. A non-loopback bind
requires it.

All application API calls then require the same bearer token. `/health` and
`/openapi.json` remain unauthenticated for discovery. Labtasker provides one
server-wide shared token, not users, roles, per-Queue ACLs, or Worker identity.

## SQLite ownership

Run one Server process per database file. Labtasker initializes a fresh database
and performs known v2 migrations at startup. Unknown or newer schema versions
fail clearly instead of being guessed. Large artifacts do not belong in this
database; store their paths or external URLs in Task data.
