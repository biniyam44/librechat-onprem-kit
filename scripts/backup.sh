#!/usr/bin/env bash
# Nightly LibreChat backup to an encrypted, off-server restic repository.
# Run from the LibreChat folder (where deploy-compose.yml and .env live), e.g. from
# a systemd timer or cron at 01:30:  ./scripts/backup.sh
#
# What is saved:
#   - MongoDB: users, chats, messages, agents, balances, transactions (mongodump)
#   - pgvector: embeddings for file search (pg_dump)
#   - uploads/ and images/: files people attached
#   - config: librechat.yaml, compose.onprem.yml, nginx/, .env (restic encrypts the repository)
#   - audit/: the connector action records
# Meilisearch is not saved: LibreChat rebuilds the search index from MongoDB.

set -euo pipefail

# Read single values from .env without executing it (LibreChat's .env contains
# arithmetic such as BAN_DURATION=1000 * 60 * 60 * 2, so it must never be sourced).
env_get() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
RESTIC_REPOSITORY="$(env_get RESTIC_REPOSITORY)"
RESTIC_PASSWORD_FILE="$(env_get RESTIC_PASSWORD_FILE)"
VECTORDB_USER="$(env_get VECTORDB_USER)"
VECTORDB_NAME="$(env_get VECTORDB_NAME)"
: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY in .env (an off-server target)}"
: "${RESTIC_PASSWORD_FILE:?set RESTIC_PASSWORD_FILE in .env}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

COMPOSE=(docker compose -f deploy-compose.yml -f compose.onprem.yml)
WORK="$(mktemp -d /var/tmp/librechat-backup.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
chmod 700 "$WORK"

echo "[backup] MongoDB"
"${COMPOSE[@]}" exec -T mongodb mongodump --archive --gzip --db LibreChat > "$WORK/mongo.archive.gz"

echo "[backup] pgvector"
"${COMPOSE[@]}" exec -T vectordb pg_dump -U "${VECTORDB_USER:-myuser}" -d "${VECTORDB_NAME:-mydatabase}" -Fc > "$WORK/vectordb.dump"

echo "[backup] files and config"
tar -czf "$WORK/files.tar.gz" uploads images audit
tar -czf "$WORK/config.tar.gz" librechat.yaml compose.onprem.yml nginx .env

echo "[backup] sending to $RESTIC_REPOSITORY"
restic backup "$WORK" --tag librechat --host "$(hostname)"
restic forget --tag librechat --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune
# Read back a sample of the stored data so silent corruption is noticed early.
restic check --read-data-subset=5%

echo "[backup] done"
