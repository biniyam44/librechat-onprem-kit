"""End-to-end over HTTP: an MCP client calls the connector the way LibreChat does,
with the person's token in the Authorization header. Microsoft Graph is mocked."""

import socket
import threading
import time

import anyio
import httpx
import httpx2
import pytest
import uvicorn
from conftest import FakeGraph, fake_jwt
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from outlook_drafts.audit import AuditLog
from outlook_drafts.server import build_server
from outlook_drafts.tools import OutlookTools

TOKEN = fake_jwt(upn="ana@example-company.com")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    graph = FakeGraph()
    audit = AuditLog(tmp_path / "actions.jsonl")
    port = _free_port()
    app = build_server(OutlookTools(audit=audit, graph_factory=graph.factory)).streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=[f"127.0.0.1:{port}"], allowed_origins=[]
        ),
        host="127.0.0.1",
    )
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started:
        assert time.monotonic() < deadline, "the MCP server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", graph, audit
    uv.should_exit = True
    thread.join(timeout=10)


def _session(url: str, token: str, action):
    async def main():
        headers = {"X-Conversation-Id": "conv-7"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx2.AsyncClient(headers=headers, timeout=10) as http:
            async with Client(streamable_http_client(f"{url}/mcp", http_client=http)) as client:
                return await action(client)

    return anyio.run(main)


def test_tools_offered_to_librechat_cannot_send_forward_or_delete(server):
    url, _, _ = server
    listed = _session(url, TOKEN, lambda client: client.list_tools())
    names = {tool.name for tool in listed.tools}
    assert names == {"list_recent_messages", "get_message", "get_calendar", "create_reply_draft"}
    assert not any(word in name for name in names for word in ("send", "forward", "delete", "move"))


def test_draft_over_http_runs_as_the_signed_in_person(server):
    url, graph, audit = server
    result = _session(
        url,
        TOKEN,
        lambda client: client.call_tool("create_reply_draft", {"message_id": "m1", "reply_text": "See you then."}),
    )
    assert result.is_error is False
    assert graph.requests[-1].headers["Authorization"] == f"Bearer {TOKEN}"
    assert graph.requests[-1].url.path.endswith("/me/messages/m1/createReply")
    [record] = audit.records()
    assert record["user"] == "ana@example-company.com"
    assert record["conversation_id"] == "conv-7"


def test_call_without_a_token_returns_a_clear_error(server):
    url, graph, _ = server
    result = _session(url, "", lambda client: client.call_tool("list_recent_messages", {}))
    assert result.is_error is True
    assert "sign in" in result.content[0].text
    assert graph.requests == []


def test_requests_for_a_foreign_host_name_are_rejected(server):
    url, _, _ = server
    response = httpx.post(
        f"{url}/mcp",
        headers={
            "Host": "attacker.example",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 421


def test_health_endpoint(server):
    url, _, _ = server
    assert httpx.get(f"{url}/healthz").text == "ok"
