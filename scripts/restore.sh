#!/usr/bin/env bash
# Restore LibreChat from the restic repository, on a fresh or a test server.
# Run from a LibreChat folder that has deploy-compose.yml, this kit's files and a .env
# with RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE.
#   ./scripts/restore.sh            # latest snapshot
#   ./scripts/restore.sh 4f2a9c1e   # a specific snapshot id (see: restic snapshots)
# The go-live "recovery from backup" test runs this on a test server and compares
# the counts it prints with production.

set -euo pipefail

SNAPSHOT="${1:-latest}"
# Read single values from .env without executing it (LibreChat's .env contains
# arithmetic such as BAN_DURATION=1000 * 60 * 60 * 2, so it must never be sourced).
env_get() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
RESTIC_REPOSITORY="$(env_get RESTIC_REPOSITORY)"
RESTIC_PASSWORD_FILE="$(env_get RESTIC_PASSWORD_FILE)"
VECTORDB_USER="$(env_get VECTORDB_USER)"
VECTORDB_NAME="$(env_get VECTORDB_NAME)"
: "${RESTIC_REPOSITORY:?}"; : "${RESTIC_PASSWORD_FILE:?}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

COMPOSE=(docker compose -f deploy-compose.yml -f compose.onprem.yml)
WORK="$(mktemp -d /var/tmp/librechat-restore.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

echo "[restore] fetching snapshot $SNAPSHOT"
restic restore "$SNAPSHOT" --tag librechat --target "$WORK"
SRC="$(dirname "$(find "$WORK" -name mongo.archive.gz -print -quit)")"

echo "[restore] stopping the app and starting only the databases"
"${COMPOSE[@]}" stop api client outlook-drafts || true
"${COMPOSE[@]}" up -d mongodb vectordb
sleep 10

echo "[restore] MongoDB"
"${COMPOSE[@]}" exec -T mongodb mongorestore --archive --gzip --drop < "$SRC/mongo.archive.gz"

echo "[restore] pgvector"
"${COMPOSE[@]}" exec -T vectordb pg_restore -U "${VECTORDB_USER:-myuser}" -d "${VECTORDB_NAME:-mydatabase}" --clean --if-exists < "$SRC/vectordb.dump"

echo "[restore] files (config is restored by hand from config.tar.gz if needed)"
tar -xzf "$SRC/files.tar.gz"
cp "$SRC/config.tar.gz" ./config-from-backup.tar.gz

echo "[restore] starting LibreChat (the search index is rebuilt from MongoDB)"
"${COMPOSE[@]}" up -d

echo "[restore] record counts, compare with production:"
"${COMPOSE[@]}" exec -T mongodb mongosh --quiet LibreChat --eval '
  ["users", "conversations", "messages", "agents", "transactions", "balances"].forEach(
    (c) => print(c.padEnd(14), db.getCollection(c).countDocuments())
  )'
