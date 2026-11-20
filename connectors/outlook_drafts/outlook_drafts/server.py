"""MCP server: the signed-in person's Outlook mail and calendar, with reply drafts only.

LibreChat calls this server with `Authorization: Bearer {{LIBRECHAT_GRAPH_ACCESS_TOKEN}}`
(see librechat.yaml), so every tool runs as the person who is chatting.
Built on the MCP Python SDK 2.x (`MCPServer`).
"""

from __future__ import annotations

import os
from functools import partial
from typing import Any, Callable

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from .audit import AuditLog
from .graph import AccessRevoked, BlockedRequest, GraphError
from .tools import CallContext, ConnectorDisabled, OutlookTools

INSTRUCTIONS = (
    "Tools for the signed-in person's own Outlook mailbox and calendar. "
    "You can list and read messages, read the calendar and save a reply draft. "
    "You cannot send, forward or delete mail: after saving a draft, tell the person "
    "to review and send it in Outlook."
)


def call_context(ctx: Context) -> CallContext:
    headers = ctx.headers or {}
    auth = headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return CallContext(token=token, conversation_id=headers.get("x-conversation-id") or None)


async def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking Graph call in a worker thread and turn known failures into tool errors."""
    try:
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))
    except AccessRevoked as exc:
        raise ToolError(
            f"Outlook refused access ({exc.status}). Access may have been revoked or the "
            "session expired: sign in to LibreChat again, or contact IT."
        ) from exc
    except (ConnectorDisabled, BlockedRequest, GraphError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def build_server(tools: OutlookTools) -> MCPServer:
    server = MCPServer("outlook-drafts", instructions=INSTRUCTIONS, version="1.0.0")

    @server.tool()
    async def list_recent_messages(
        ctx: Context, folder: str = "inbox", top: int = 10, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        """List your most recent messages in one folder: inbox, sentitems, drafts or archive (max 25)."""
        return await _run(tools.list_recent_messages, call_context(ctx), folder, top, unread_only)

    @server.tool()
    async def get_message(ctx: Context, message_id: str) -> dict[str, Any]:
        """Read one of your messages as plain text, by the id from list_recent_messages."""
        return await _run(tools.get_message, call_context(ctx), message_id)

    @server.tool()
    async def get_calendar(ctx: Context, days_ahead: int = 7) -> list[dict[str, Any]]:
        """List your calendar events from now until a number of days ahead (max 31), in UTC."""
        return await _run(tools.get_calendar, call_context(ctx), days_ahead)

    @server.tool()
    async def create_reply_draft(
        ctx: Context, message_id: str, reply_text: str, reply_all: bool = False
    ) -> dict[str, Any]:
        """Save a reply to one of your messages as a draft in Outlook. It is NOT sent:
        you review and send it yourself in Outlook."""
        return await _run(tools.create_reply_draft, call_context(ctx), message_id, reply_text, reply_all)

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return server


def tools_from_env() -> OutlookTools:
    return OutlookTools(
        audit=AuditLog(os.environ.get("AUDIT_LOG_PATH", "/audit/outlook-actions.jsonl")),
        enabled=os.environ.get("CONNECTOR_ENABLED", "true").strip().lower() == "true",
    )


def security_from_env() -> TransportSecuritySettings:
    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "outlook-drafts:8000").split(",") if h.strip()]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[])


def main() -> None:
    build_server(tools_from_env()).run(
        "streamable-http",
        host="0.0.0.0",  # reachable only on the internal Docker network; no port is published
        port=int(os.environ.get("PORT", "8000")),
        stateless_http=True,
        json_response=True,
        transport_security=security_from_env(),
    )


if __name__ == "__main__":
    main()
