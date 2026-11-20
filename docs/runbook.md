# Runbook: install, update, back up, recover

All commands run in the LibreChat folder on the server. To keep them short:

```bash
alias dc='docker compose -f deploy-compose.yml -f compose.onprem.yml'
```

## Install

1. **Server:** Ubuntu 24.04 LTS, Docker Engine with the Compose plugin (2.24 or newer).
   Suggested size for about 100 staff: 8 vCPU, 16 GB RAM, 200 GB SSD.
2. **Firewall:** allow 443 (and 80, which only redirects) from the office and VPN ranges.
   Nothing else is published.
3. **LibreChat:** `git clone --branch v0.8.9 https://github.com/danny-avila/LibreChat.git`
   and copy this kit's files into that folder.
4. **.env:** start from LibreChat's `.env.example`, then merge `.env.onprem.example`.
   Generate every secret (`openssl rand -hex 32`; `CREDS_IV` needs 16 bytes: `openssl rand -hex 16`).
5. **Pin the API image:** `docker pull <image>:<tag>`, then
   `docker image inspect --format '{{index .RepoDigests 0}}' <image>:<tag>` and put the
   digest in `LIBRECHAT_API_IMAGE`.
6. **Certificate:** issue one certificate for the chat and admin host names from the
   internal CA and save it as `certs/chat.crt` and `certs/chat.key`.
7. **Audit folder:** `mkdir -p audit && sudo chown 10001 audit` (the connector runs as uid 10001).
8. **Entra ID:** follow [entra-id-setup.md](entra-id-setup.md).
9. **Start:** `dc up -d`, then `dc ps` until every service is healthy.
10. **Check:** run `python3 -m pytest`, then the [go-live checklist](go-live-checklist.md).

## Update LibreChat

1. Read the release notes for config or database changes.
2. Run `./scripts/backup.sh`.
3. Put the new digest in `LIBRECHAT_API_IMAGE` (keep the old one in a comment).
4. `dc pull api && dc up -d api`
5. Smoke test: sign in, one chat with each approved model, one Outlook draft with approval,
   `dc logs --since 10m api | grep -i error`.
6. **Rollback:** put the old digest back and `dc up -d api`. If the release changed the
   database, restore last night's backup as well (`./scripts/restore.sh`).

## Backups

`scripts/backup.sh` saves MongoDB, pgvector, uploaded files, config and the audit log to an
encrypted restic repository off the server, keeps 14 daily, 8 weekly and 12 monthly copies,
and reads back a sample to catch corruption. Run it nightly with a systemd timer:

```ini
# /etc/systemd/system/librechat-backup.service
[Service]
Type=oneshot
WorkingDirectory=/opt/LibreChat
ExecStart=/opt/LibreChat/scripts/backup.sh

# /etc/systemd/system/librechat-backup.timer
[Timer]
OnCalendar=*-*-* 01:30
Persistent=true
[Install]
WantedBy=timers.target
```

Keep the restic password file in the password manager as well: without it, backups cannot
be read.

## Recover

On a fresh server with the same install steps: `./scripts/restore.sh` (latest) or
`./scripts/restore.sh <snapshot-id>`. Compare the printed counts with production. Practise
this every quarter on the test server.

## Everyday tasks

| Task | How |
|---|---|
| Add or remove an approved model | Edit `ANTHROPIC_MODELS` / `OPENAI_MODELS` in `.env` or the xAI list in `librechat.yaml`, update `modelSpecs`, run `pytest`, then `dc up -d api`. Check the model has a price in LibreChat so spend is counted correctly. |
| Change one person's allowance | `dc exec api npm run set-balance` or `add-balance`; list with `list-balances`. |
| Monthly spend report | See the top of `scripts/spend_report.py`. |
| Rotate a provider key | Replace it in `.env`, `dc up -d api`, revoke the old key at the provider. |
| Switch the Outlook connector off | `OUTLOOK_CONNECTOR_ENABLED=false`, `dc up -d outlook-drafts`. |
| Offboard a person | Entra ID steps, then `./scripts/offboard_user.sh <email>`. |
| Check the action records | `dc exec outlook-drafts python -m outlook_drafts.audit /audit/outlook-actions.jsonl` |
| Logs | `dc logs -f api` (JSON lines with `CONSOLE_JSON=true`), files in `./logs`. |
