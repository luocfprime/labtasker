#!/bin/bash
set -e

# this script wraps the original docker-entrypoint.sh script of mongodb
# 1. mongodb entrypoint script is called, invoking init.d scripts before starting the server
# 2. the server is started and the entrypoint script waits for the server to be ready
# 3. once the server is ready, the post-init.d scripts are executed

# Call the original MongoDB entrypoint script
/usr/local/bin/docker-entrypoint.sh "$@" &

# # Wait for MongoDB to be fully initialized
# echo "Waiting for MongoDB to start..."
# until mongosh --quiet --eval "db.adminCommand('ping')" >/dev/null 2>&1; do
#   sleep 2
# done
# echo "MongoDB is ready."

# Execute post-init scripts
if [ -d "/docker-entrypoint-post-initdb.d/" ]; then
  echo "Running post-init.d scripts..."
  for script in /docker-entrypoint-post-initdb.d/*; do
    case "$script" in
      *.sh)
        echo "Executing $script"
        . "$script"
        ;;
      *.js)
        echo "Executing $script with mongosh"
        mongosh "$script"
        ;;
      *)
        echo "Ignoring $script (not .sh or .js)"
        ;;
    esac
  done
fi

# Wait for the MongoDB process to end
wait
