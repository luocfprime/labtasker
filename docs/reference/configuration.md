# Configuration

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
| `url` | `LABTASKER_URL` | `http://127.0.0.1:8000` |
| `queue` | `LABTASKER_QUEUE` | `default` |
| `token` | `LABTASKER_TOKEN` | unset |

The file is strict: unknown keys, empty values, malformed TOML, and v1
`.labtasker/client.toml` are errors. `labtasker config show` prints effective
non-secret settings and only reports whether a token is configured.

Configuration is loaded when a `Client` is first instantiated. Top-level helper
functions lazily share one default Client; use an explicit Client when different
targets are needed in one process:

```python
from labtasker import Client

with Client(url="https://example.com", queue="paper") as client:
    client.submit_task({"prompt": "a ceramic fox"}, routes=["sdxl"])
```

## Server configuration

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
