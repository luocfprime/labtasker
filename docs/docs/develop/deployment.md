# Deployment Guide

## Prerequisites
- Docker
- Docker Compose

## Configuration
1. Copy `server.example.env` to `server.env`:
   ```bash
   cp server.example.env server.env
   ```

2. Edit `server.env` with your settings:
   - Set secure passwords
   - Configure ports
   - Set security pepper

## Database Management
To expose MongoDB for external tools:
1. Set `EXPOSE_DB=true` in `server.env`
2. Optionally set `DB_PORT` to change the exposed port (default: 27017)
2. Use tools like MongoDB Compass with:
   ```
   mongodb://username:password@localhost:27017
   ```

## Deployment
1. Start services:
   ```bash
   docker-compose --env-file server.env up -d
   ```

2. Check status:
   ```bash
   docker-compose ps
   ```

3. View logs:
   ```bash
   docker-compose logs -f
   ```

## Maintenance
- Backup database:
  ```bash
  docker exec labtasker-mongodb mongodump --out /data/backup
  ```

- Restore database:
  ```bash
  docker exec labtasker-mongodb mongorestore /data/backup
  ```
