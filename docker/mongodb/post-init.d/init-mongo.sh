#!/bin/bash
set -e

# MongoDB credentials and database from environment variables
MONGO_USER="$MONGO_INITDB_ROOT_USERNAME"
MONGO_PASSWORD="$MONGO_INITDB_ROOT_PASSWORD"
MONGO_DB="$MONGO_INITDB_DATABASE"

# Wait for MongoDB to start
echo "Waiting for MongoDB to start..."
until mongosh --quiet --eval "db.adminCommand('ping')" &>/dev/null; do
  sleep 2
done
echo "MongoDB started."

# Check if the replica set is already initialized
echo "Checking if the replica set is initialized..."
RS_STATUS=$(mongosh $MONGO_DB --quiet --username "$MONGO_USER" --password "$MONGO_PASSWORD" --authenticationDatabase admin --eval "rs.status().ok" || echo "0")

if [ "$RS_STATUS" -ne "1" ]; then
  echo "Replica set not initialized. Initializing..."
  mongosh $MONGO_DB --quiet --username "$MONGO_USER" --password "$MONGO_PASSWORD" --authenticationDatabase admin <<EOF
  rs.initiate({
    _id: "rs0",
    members: [
      { _id: 0, host: "localhost:27017" }
    ]
  })
EOF
  echo "Replica set initialized."
else
  echo "Replica set already initialized. Skipping initialization."
fi

# Wait for the replica set to become PRIMARY
echo "Waiting for MongoDB replica set to initialize..."
until mongosh --quiet --username "$MONGO_USER" --password "$MONGO_PASSWORD" --authenticationDatabase admin --eval "rs.isMaster().ismaster" | grep "true"; do
  sleep 2
done
echo "Replica set is now PRIMARY."

# Create collections if they do not exist
echo "Creating collections in database '$MONGO_DB'..."
mongosh --quiet --username "$MONGO_USER" --password "$MONGO_PASSWORD" --authenticationDatabase admin <<EOF
use $MONGO_DB
db.createCollection('queues', { capped: false })
db.createCollection('tasks', { capped: false })
db.createCollection('workers', { capped: false })
EOF
echo "Collections created successfully."

echo "Marking setup as completed..."
touch /setup_completed

echo "MongoDB setup completed."
