#!/bin/bash
set -e

# Create labtasker user and database if they don't exist
mongosh <<EOF
use $MONGO_INITDB_DATABASE

db.createUser({
  user: '$MONGO_INITDB_ROOT_USERNAME',
  pwd: '$MONGO_INITDB_ROOT_PASSWORD',
  roles: [{
    role: 'readWrite',
    db: '$MONGO_INITDB_DATABASE'
  }]
})

// Create required collections and indexes
db.createCollection('queues')
// Queue indexes
db.queues.createIndex({ "queue_name": 1 }, { unique: true })

db.createCollection('tasks')
// Task indexes
db.tasks.createIndex({ "queue_id": 1 })
db.tasks.createIndex({ "status": 1 })
db.tasks.createIndex({ "priority": 1 })

db.createCollection('workers')
// Worker indexes
db.workers.createIndex({ "queue_id": 1 })
db.workers.createIndex({ "worker_name": 1 })
EOF
