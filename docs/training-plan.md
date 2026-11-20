# Training plan

Live, hands-on sessions over Teams or Zoom. The team does each step on their own
screen; the trainer guides and only takes over to unblock. Each session ends with a
short exercise that proves the skill, and a recording for later.

## Session 1 (IT, 90 min): how it runs

- The pieces: nginx, LibreChat, MongoDB, Meilisearch, RAG API, the Outlook connector.
- Where settings live: `.env`, `librechat.yaml`, `compose.onprem.yml`, and what each controls.
- Health and logs: `dc ps`, `dc logs`, the `/healthz` check, reading JSON logs.
- **Exercise:** change the welcome message, restart only the API, confirm the change, run `pytest`.

## Session 2 (IT, 90 min): update, back up, restore

- Pinned images and why, release notes, the update and rollback steps.
- Backups: what is saved, where, how long, and how to read a snapshot list.
- **Exercise:** run a backup, restore it on the test server, compare the counts, roll an
  update forward and back.

## Session 3 (IT, 90 min): models, limits and connectors

- Adding and removing approved models and model specs; testing the change.
- Allowances: start balance, refills, `set-balance`, the monthly spend report.
- Connectors: MCP servers in `librechat.yaml`, `allowedAddresses`, tool approval rules,
  switching a connector off, reading the audit log.
- Offboarding from start to finish.
- **Exercise:** add a model, give a test account a small allowance and run the report, switch
  the Outlook connector off and on again.

## Session 4 (power users, 90 min): features most people miss

- Switching models in the middle of a chat, and comparing answers side by side.
- Artifacts: documents and small apps that open beside the chat.
- Agents: instructions, files, tools, sharing with colleagues, and handing off between models.
- SharePoint picker and file search with citations.
- Outlook drafts with approval: what the approval prompt shows and why nothing is sent.
- Temporary chats, bookmarks, the prompt library.
- **Exercise:** build a small team agent that uses a SharePoint document and drafts a reply.

## Handover

The team can, without help: run, update, back up, restore, add models and tools,
change allowances, offboard a person and read the action records. The go-live
checklist is signed off and stored with the evidence.
