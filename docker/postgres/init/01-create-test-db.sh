#!/bin/sh
set -eu

echo "Creating DocuLens test database..."
createdb \
  --username "$POSTGRES_USER" \
  --owner "$POSTGRES_USER" \
  doculens_test

echo "DocuLens test database created."
