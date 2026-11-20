"""Tool logic for the Outlook drafts connector, independent of the MCP transport.

Every call runs with the caller's own Microsoft Graph token, so a person can only
read their own mailbox and calendar. Saving a reply draft is the only write, and
each attempt (successful or not) is written to the audit log.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .audit import AuditLog
from .graph import AccessRevoked, BlockedRequest, GraphClient, GraphError, message_path

FOLDERS = ("inbox", "sentitems", "drafts", "archive")
MAX_MESSAGES = 25
MAX_BODY_CHARS = 20_000
MAX_REPLY_CHARS = 10_000
MAX_CALENDAR_DAYS = 31
TEXT_BODY = {"Prefer": 'outlook.body-content-type="text"'}


class ConnectorDisabled(Exception):
    """IT has switched this connector off (connector revocation)."""


@dataclass(frozen=True)
class CallContext:
    token: str
    conversation_id: str | None = None


def token_user(token: str) -> str:
    """Best-effort user name from the token, used only to label audit records.

    Microsoft Graph validates the token on every call; this decoding never
    decides access.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims.get("upn") or claims.get("preferred_username") or claims.get("oid") or "unknown"
    except Exception:  # noqa: BLE001 - an unreadable token is still labelled
        return "unknown"


def _sender(message: dict[str, Any]) -> str:
    address = (message.get("from") or {}).get("emailAddress") or {}
    name, email = address.get("name"), address.get("address")
    return f"{name} <{email}>" if name and email else (email or name or "")


class OutlookTools:
    def __init__(
        self,
        *,
        audit: AuditLog,
        enabled: bool = True,
        graph_factory: Callable[[str], GraphClient] = GraphClient,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.audit = audit
        self.enabled = enabled
        self._graph_factory = graph_factory
        self._now = now

    def _graph(self, ctx: CallContext) -> GraphClient:
        if not self.enabled:
            raise ConnectorDisabled("The Outlook connector has been switched off by IT.")
        return self._graph_factory(ctx.token)

    # Read-only tools ---------------------------------------------------------

    def list_recent_messages(
        self, ctx: CallContext, folder: str = "inbox", top: int = 10, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        folder = folder.lower().strip()
        if folder not in FOLDERS:
            raise ValueError(f"folder must be one of: {', '.join(FOLDERS)}")
        params: dict[str, Any] = {
            "$top": max(1, min(int(top), MAX_MESSAGES)),
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
        }
        if unread_only:
            # Graph requires the $orderby property to appear first in $filter.
            params["$filter"] = "receivedDateTime ge 1900-01-01T00:00:00Z and isRead eq false"
        data = self._graph(ctx).request("GET", f"/me/mailFolders/{folder}/messages", params=params)
        return [
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": _sender(m),
                "received": m.get("receivedDateTime"),
                "is_read": m.get("isRead"),
                "preview": m.get("bodyPreview"),
            }
            for m in data.get("value", [])
        ]

    def get_message(self, ctx: CallContext, message_id: str) -> dict[str, Any]:
        params = {"$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,webLink"}
        m = self._graph(ctx).request("GET", message_path(message_id), params=params, headers=TEXT_BODY)
        body = (m.get("body") or {}).get("content") or ""
        return {
            "id": m.get("id"),
            "subject": m.get("subject"),
            "from": _sender(m),
            "to": [r["emailAddress"].get("address") for r in m.get("toRecipients", [])],
            "cc": [r["emailAddress"].get("address") for r in m.get("ccRecipients", [])],
            "received": m.get("receivedDateTime"),
            "body": body[:MAX_BODY_CHARS],
            "body_truncated": len(body) > MAX_BODY_CHARS,
            "web_link": m.get("webLink"),
        }

    def get_calendar(self, ctx: CallContext, days_ahead: int = 7) -> list[dict[str, Any]]:
        days = max(1, min(int(days_ahead), MAX_CALENDAR_DAYS))
        start = self._now().replace(microsecond=0)
        params = {
            "startDateTime": start.isoformat(),
            "endDateTime": (start + timedelta(days=days)).isoformat(),
            "$orderby": "start/dateTime",
            "$select": "subject,start,end,location,organizer,isOnlineMeeting",
            "$top": 50,
        }
        data = self._graph(ctx).request(
            "GET", "/me/calendarView", params=params, headers={"Prefer": 'outlook.timezone="UTC"'}
        )
        return [
            {
                "subject": e.get("subject"),
                "start_utc": (e.get("start") or {}).get("dateTime"),
                "end_utc": (e.get("end") or {}).get("dateTime"),
                "location": (e.get("location") or {}).get("displayName"),
                "organizer": ((e.get("organizer") or {}).get("emailAddress") or {}).get("address"),
                "online": e.get("isOnlineMeeting"),
            }
            for e in data.get("value", [])
        ]

    # The only write: a draft that the person reviews and sends in Outlook ----

    def create_reply_draft(
        self, ctx: CallContext, message_id: str, reply_text: str, reply_all: bool = False
    ) -> dict[str, Any]:
        action = "create_reply_all_draft" if reply_all else "create_reply_draft"
        base = {
            "action": action,
            "user": token_user(ctx.token),
            "conversation_id": ctx.conversation_id,
            "source_message_id": message_id,
        }
        try:
            text = (reply_text or "").strip()
            if not text:
                raise ValueError("reply_text is empty.")
            if len(text) > MAX_REPLY_CHARS:
                raise ValueError(f"reply_text is longer than {MAX_REPLY_CHARS} characters.")
            suffix = "/createReplyAll" if reply_all else "/createReply"
            draft = self._graph(ctx).request("POST", message_path(message_id, suffix), json={"comment": text})
        except (ConnectorDisabled, AccessRevoked, BlockedRequest, GraphError, ValueError) as exc:
            self.audit.append(**base, outcome="failed", error=type(exc).__name__)
            raise
        self.audit.append(**base, outcome="draft_saved", draft_id=draft.get("id"))
        return {
            "draft_id": draft.get("id"),
            "subject": draft.get("subject"),
            "web_link": draft.get("webLink"),
            "next_step": "The draft is in your Outlook Drafts folder. Review it and send it yourself.",
        }
