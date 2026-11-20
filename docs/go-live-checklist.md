# Go-live checklist

Run every test on the production server before go-live, with two test accounts
(**Test A** and **Test B**) that are normal staff accounts in Entra ID. Keep the
evidence (screenshots, command output) in the go-live folder.

`pytest` covers the parts that can be checked from the files alone. Run it first:

```bash
python3 -m pytest
```

| # | Test | How to run it | Passes when | Automated part |
|---|------|---------------|-------------|----------------|
| 1 | **Restricted records** | As Test A, who has no access to a restricted Pace job, ask an agent with the Pace connector to read that job. In the SharePoint picker, look for a folder Test A cannot open in SharePoint. | Pace refuses the record. The picker does not show the folder. | `test_connectors_are_the_approved_ones_with_per_user_tokens` (Pace receives the person's own identity) |
| 2 | **Chat isolation** | Test A writes a chat containing a unique word. Test B searches for that word and opens Test A's chat URL directly. | Test B finds nothing and the URL does not open. Shared links cannot be created. | `test_people_cannot_add_connectors_or_share_chats` |
| 3 | **Offboarding** | In Entra ID, block sign-in for Test B, revoke sessions and remove the app role. Then run `./scripts/offboard_user.sh <test-b-email>`. | Test B's open session ends at the next token refresh (15 minutes or less), sign-in is refused, and the Outlook connector refuses calls. | `test_sign_in_is_entra_id_only` |
| 4 | **Connector revocation** | Set `OUTLOOK_CONNECTOR_ENABLED=false` in `.env`, run `docker compose -f deploy-compose.yml -f compose.onprem.yml up -d outlook-drafts`, then ask an agent to list mail. Repeat by removing admin consent for Mail.ReadWrite in Entra ID. | Both times the tool answers with a clear "switched off" or "access refused" message and nothing reaches the mailbox. | `test_switched_off_connector_refuses_every_tool`, `test_refused_draft_is_recorded_and_reported_as_revoked` |
| 5 | **Approved providers only** | Open the model menu. Try to select another endpoint or type an unapproved model name in an API request. | Only the approved Anthropic, OpenAI and xAI models appear. Other models are refused. | `test_only_approved_providers_and_models`, `test_provider_keys_stay_on_the_server` |
| 6 | **Per-person spend** | Give Test A a small balance (`docker compose ... exec api npm run set-balance`), chat until it runs out, then run `scripts/spend_report.py` for the month. | Test A is stopped at zero until the refill. The report shows Test A's usage per model. | `test_per_person_spend_limits_are_on`, `tests/test_spend_report.py` |
| 7 | **Deletion and retention** | Test A deletes a chat. Check the chat list, search, and MongoDB (`db.conversations.countDocuments({conversationId: "<id>"})`). Check that a new chat has an `expiredAt` date. | The chat is gone everywhere. New chats carry the agreed retention date. | `test_retention_applies_to_every_chat` |
| 8 | **Recovery from backup** | Run `./scripts/backup.sh` on production, then `./scripts/restore.sh` on the test server. Sign in there and open an old chat. | The record counts printed by `restore.sh` match production, and old chats, files and agents open normally. | none (needs two servers) |
| 9 | **Approved-action records** | Ask an agent to draft a reply to a test email. Approve the tool call when LibreChat asks. Then run `docker compose ... exec outlook-drafts python -m outlook_drafts.audit /audit/outlook-actions.jsonl`. | LibreChat asked before the draft was saved. The audit log has one line with the person, the conversation and the draft id, and reports "audit log intact". Nothing was sent. | `test_changes_need_human_approval_and_send_delete_are_denied`, `test_saved_draft_is_recorded_in_the_audit_log`, `test_audit_chain_detects_an_edited_line` |

## Also check

- **Internal only:** from outside the office and VPN, `https://<chat-host>` does not answer. From the office it does. The admin host answers only from the IT range.
- **Embedding:** the in-house web app shows LibreChat in its iframe, and any other site cannot (`curl -sI https://<chat-host> | grep -i frame-ancestors`).
- **Multi-factor sign-in:** a sign-in from a new browser asks for the second factor (Conditional Access).
- **No secrets in git:** `git status` shows no `.env`, certificates or audit files.
