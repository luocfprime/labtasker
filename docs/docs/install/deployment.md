# Deploy Server

!!! info "TLDR"

    The Labtasker server can be deployed in two ways, depending on the database backend and the chosen deployment method.

      | Deployment Method                | Server                 | Database                      |
      |----------------------------------|------------------------|-------------------------------|
      | Python Native `labtasker-server` | Local Environment      | A Python Emulated Embedded DB |
      | docker compose                   | Run inside a container | MongoDB Service               |

## Method 1. Python Native (Easy)

This is the simplest way to get started with Labtasker using only Python dependencies. The embedded database makes setup
fast and straightforward.

```bash
pip install labtasker
```

Then, to start a Labtasker server (with embedded database) in the background, run the following command:

```bash
labtasker-server serve --host 0.0.0.0 --port 9321 &
```

## Method 2. Docker Compose (Advanced)

This method is recommended for scenarios where you need more robust database capabilities and containerized deployment.

### Prerequisites

- Docker Compose

### Step 1: Configuration

1. Clone the repository:
   ```bash
   git clone https://github.com/fkcptlst/labtasker.git
   cd labtasker
   ```

2. Create your environment file:
   ```bash
   cp server.example.env server.env
   ```

3. Configure your settings in `server.env`:
    - Configure MongoDB.
    - Configure server ports.
    - Configure how often you want to check for task timeouts.

### Step 2: Start services

1. Start services (first time or update existing services):
   ```bash
   docker compose --env-file server.env up -d --pull always
   ```

2. Check status:
   ```bash
   docker compose --env-file server.env ps
   ```

3. View logs:
   ```bash
   docker compose --env-file server.env logs -f
   ```

### Database Management

To expose MongoDB for external tools (this is potentially risky):

1. Set `EXPOSE_DB=true` in `server.env`
2. Optionally set `DB_PORT` to change the exposed port (default: 27017)
3. Use tools like MongoDB Compass to connect to the database.
