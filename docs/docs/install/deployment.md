# Deploy Server

!!! info "TLDR"

    The deployment of Labtasker is straightforward. Basically, you need to:

    1. Make sure repo is cloned and docker compose is installed.
    2. Modify the config file according to your needs.
    3. Start services via `docker compose --env-file=your_env_file.env up -d`

## Prerequisites

- Docker Compose

## Deployment

### Step 1: Configuration

1. Clone the repository:
   ```bash
   git clone https://github.com/fkcptlst/labtasker.git
   cd labtasker
   ```

2. Copy `server.example.env` to `server.env`:
   ```bash
   cp server.example.env server.env
   ```

3. Edit `server.env` with your settings:
    - Configure MongoDB.
    - Configure server ports.
    - Configure how often you want to check for task timeouts.

### Step 2: Start services

1. Start services:
   ```bash
   docker compose --env-file server.env up -d
   ```

2. Check status:
   ```bash
   docker compose --env-file server.env ps
   ```

3. View logs:
   ```bash
   docker compose --env-file server.env logs -f
   ```

## Database Management

To expose MongoDB for external tools (this is potentially risky):

1. Set `EXPOSE_DB=true` in `server.env`
2. Optionally set `DB_PORT` to change the exposed port (default: 27017)
3. Use tools like MongoDB Compass to connect to the database.

[//]: # (## Maintenance)

[//]: # ()

[//]: # (- Backup database:)

[//]: # (  ```bash)

[//]: # (  docker exec labtasker-mongodb mongodump --out /data/backup)

[//]: # (  ```)

[//]: # ()

[//]: # (- Restore database:)

[//]: # (  ```bash)

[//]: # (  docker exec labtasker-mongodb mongorestore /data/backup)

[//]: # (  ```)
