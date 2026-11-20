# LibreChat On-Prem Kit

A deployment kit for running [LibreChat](https://github.com/danny-avila/LibreChat) as a
company's internal AI workspace on its own server: Microsoft Entra ID sign-in with
multi-factor, approved models from Anthropic, OpenAI and xAI, per-person spend limits,
connectors that need a person's approval before they change anything, encrypted
off-server backups, and a go-live test list.

Written for **LibreChat v0.8.9** (`librechat.yaml` config version 1.3.19) and the
**MCP Python SDK 2.3**. Company-specific values are placeholders marked `CHANGE`.

## What it covers

| Requirement | How the kit handles it |
|---|---|
| On-premises, internal only, HTTPS | nginx publishes 443 on the server's internal IP only, with office/VPN allow lists, TLS from the internal CA. The API, databases and connectors publish no ports. ([compose.onprem.yml](compose.onprem.yml), [nginx/](nginx/)) |
| Entra ID single sign-on with MFA | OpenID Connect is the only sign-in. App roles decide who may sign in; MFA comes from a Conditional Access policy. ([docs/entra-id-setup.md](docs/entra-id-setup.md)) |
| Embedded in an in-house web app | `frame-ancestors` allows only the in-house app's origin. |
| Anthropic, OpenAI and xAI models, keys on the server | Server-side keys, an approved model list per provider, Grok through xAI's OpenAI-compatible API. ([librechat.yaml](librechat.yaml)) |
| Per-person limits and spend reports | LibreChat balances with monthly reset, and [scripts/spend_report.py](scripts/spend_report.py) for a CSV per person, month and model. |
| Agents handing off between models | Every approved model is a handoff target (`modelSpecs` with `handoff: true`). |
| SharePoint files people can already open | LibreChat's SharePoint picker on the person's own Entra ID token. |
| Outlook: read own mail, draft replies | [connectors/outlook_drafts](connectors/outlook_drafts): an MCP server that runs on the person's own Graph token and can only read and save drafts. |
| ERP connector with permissions | The existing EFI Pace MCP server is connected with the person's identity, so Pace applies its own record permissions. |
| Actions a person confirms, each recorded | LibreChat tool approval asks before any connector write; send and delete are always denied. The connector writes a hash-chained audit log. |
| Retention, deletion, logging | `retentionMode: all` with agreed retention periods, JSON logs, audit log checks. |
| Backups off the server, tested restore | [scripts/backup.sh](scripts/backup.sh) and [scripts/restore.sh](scripts/restore.sh) with restic (encrypted). |
| Go-live tests and handover | [docs/go-live-checklist.md](docs/go-live-checklist.md), [docs/runbook.md](docs/runbook.md), [docs/training-plan.md](docs/training-plan.md) |

## How it fits together

```mermaid
flowchart LR
  user["Staff browser<br/>office or VPN"] -->|HTTPS| nginx["nginx<br/>internal IP only"]
  app["In-house web app"] -. iframe .-> nginx
  nginx --> api["LibreChat"]
  api --> mongo[("MongoDB")]
  api --> meili[("Meilisearch")]
  api --> rag["RAG API + pgvector"]
  api -->|sign-in + MFA| entra["Microsoft Entra ID"]
  api -->|server-side keys| llm["Anthropic / OpenAI / xAI APIs"]
  api -->|MCP + person's Graph token| outlook["outlook-drafts connector"]
  outlook -->|read mail, save drafts| graph["Microsoft Graph"]
  api -->|MCP + person's identity| pace["EFI Pace MCP"]
  backup["backup.sh (nightly)"] -->|restic, encrypted| offsite[("Off-server backup")]
```

## The Outlook connector

The connector gives agents four tools: `list_recent_messages`, `get_message`,
`get_calendar` and `create_reply_draft`. Its safety does not depend on the prompt:

- **Own mailbox only.** Every call uses the token LibreChat obtained for the person who is
  chatting (`{{LIBRECHAT_GRAPH_ACCESS_TOKEN}}`).
- **Cannot send.** The Graph client has an allow list of five request types. Sending,
  forwarding, moving and deleting are refused before any request leaves the container, and
  the app registration is not granted `Mail.Send`.
- **A person approves each draft** (LibreChat tool approval), then reviews and sends it in Outlook.
- **Every draft is recorded** in a hash-chained JSON Lines log (person, conversation, message,
  draft id, result, never the mail text). Editing or removing a past line is detected.
- **Can be switched off** for everyone with one setting, and stops working at once if Entra ID
  access is revoked.
- Runs as a non-root, read-only container, reachable only on the internal Docker network,
  with Host header checks.

## Quick start

```bash
git clone --branch v0.8.9 https://github.com/danny-avila/LibreChat.git && cd LibreChat
# copy this kit's files into the LibreChat folder, then build .env (see docs/runbook.md)
docker compose -f deploy-compose.yml -f compose.onprem.yml up -d
```

The full steps, including Entra ID, certificates and pinning the image, are in
[docs/runbook.md](docs/runbook.md).

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

53 tests in three groups:

- **Configuration rules** ([tests/test_config.py](tests/test_config.py)): Entra ID only, approved
  providers and models, keys on the server, spend limits on, retention for every chat, no public
  sharing, approval for every connector write, no published ports except nginx on the internal
  IP, blank secrets in the example, real secrets ignored by git.
- **Outlook connector** ([tests/test_outlook_connector.py](tests/test_outlook_connector.py)): refused
  requests never reach Graph, drafts use the caller's token, audit records and tamper detection,
  switch-off and revoked access.
- **End to end over HTTP** ([tests/test_outlook_mcp_http.py](tests/test_outlook_mcp_http.py)): an MCP
  client calls the running server the way LibreChat does.

The compose overrides were also checked with `docker compose config` against LibreChat's
`deploy-compose.yml`, and the nginx template with `nginx -t`.

## Agreed during setup, not included

- The EFI Pace MCP server itself (the company's own connector; the kit connects to it).
- Relevance AI and ElevenLabs connections: the right route (MCP server, agent action or API)
  depends on what each account exposes, and is decided after a short review of both.
- The final model list, allowances and retention periods.

## License

MIT
