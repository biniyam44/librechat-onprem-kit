#!/usr/bin/env bash
# Offboard one person from LibreChat. Do the Entra ID steps FIRST:
#   1. Block sign-in for the account and revoke its sessions.
#   2. Remove the LibreChat.User app role assignment.
# With OPENID_REUSE_TOKENS=true, LibreChat sessions depend on Entra ID tokens, so an
# open session ends at the next token refresh, and Graph tokens for the Outlook
# connector can no longer be issued.
#
# This script then acts inside LibreChat:
#   ./scripts/offboard_user.sh person@example-company.com          # ban now, keep data
#   ./scripts/offboard_user.sh person@example-company.com --delete # remove account and data
# LibreChat's own admin scripts ask for anything they still need and for confirmation.

set -euo pipefail

EMAIL="${1:?usage: offboard_user.sh <email> [--delete]}"
MODE="${2:-}"
if [[ ! "$EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
  echo "not an email address: $EMAIL" >&2
  exit 2
fi
COMPOSE=(docker compose -f deploy-compose.yml -f compose.onprem.yml)

if [[ "$MODE" == "--delete" ]]; then
  echo "[offboard] deleting the LibreChat account and data of $EMAIL"
  "${COMPOSE[@]}" exec api npm run delete-user -- "$EMAIL"
else
  echo "[offboard] banning $EMAIL in LibreChat (data kept for the retention period)"
  "${COMPOSE[@]}" exec api npm run ban-user -- "$EMAIL"
fi

echo "[offboard] remaining accounts with this email:"
"${COMPOSE[@]}" exec -T mongodb mongosh --quiet LibreChat --eval "db.users.countDocuments({ email: '$EMAIL' })"
