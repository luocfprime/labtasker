#!/bin/bash

echo "Running init-keyfile.sh..."

KEYFILE_PATH="/data/configdb/mongo-keyfile"

# Check if the keyfile already exists
if [ ! -f "$KEYFILE_PATH" ]; then
  echo "Keyfile not found. Generating a new one..."

  # Generate a random key for authentication
  openssl rand -base64 756 > "$KEYFILE_PATH"

  # Set the required permissions
  chmod 400 "$KEYFILE_PATH"

  echo "Keyfile created and permissions set."
else
  echo "Keyfile already exists. Verifying permissions..."

  # Ensure proper permissions are set
  chmod 400 "$KEYFILE_PATH"

  echo "Permissions verified."
fi

echo "Keyfile setup completed."
