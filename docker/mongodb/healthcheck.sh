#!/bin/bash

if [ ! -f /setup_completed ]; then
    echo "File /setup_completed not found"
    exit 1
fi

if ! mongosh --eval "db.adminCommand('ping')" >/dev/null 2>&1; then
    echo "MongoDB ping failed"
    exit 1
fi

echo "Health check passed"
exit 0
