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

// Create required collections
db.createCollection('queues')
db.createCollection('tasks')
db.createCollection('workers')
EOF
