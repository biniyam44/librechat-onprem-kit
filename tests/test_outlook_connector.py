"""Unit tests for the Outlook drafts connector, with Microsoft Graph mocked."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from conftest import FakeGraph, fake_jwt

from outlook_drafts.audit import AuditLog
from outlook_drafts.graph import AccessRevoked, BlockedRequest
from outlook_drafts.tools import CallContext, ConnectorDisabled, OutlookTools

TOKEN = fake_jwt(upn="ana@example-company.com")


@pytest.fixture
def graph():
    return FakeGraph()


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "actions.jsonl")


@pytest.fixture
def tools(graph, audit):
    fixed_now = lambda: datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)  # noqa: E731
    return OutlookTools(audit=audit, graph_factory=graph.factory, now=fixed_now)


CTX = CallContext(token=TOKEN, conversation_id="conv-42")


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/me/sendMail"),
        ("POST", "/me/messages/m1/send"),
        ("POST", "/me/messages/m1/reply"),
        ("POST", "/me/messages/m1/forward"),
        ("POST", "/me/messages/m1/move"),
        ("DELETE", "/me/messages/m1"),
        ("PATCH", "/me/messages/m1"),
        ("GET", "/users/someone-else@example-company.com/messages"),
        ("GET", "/me/mailFolders/inbox/messages/../../../users/x"),
        ("GET", "/me/messages/.."),
        ("GET", "/me/messages/%2E%2E"),
    ],
)
def test_graph_client_refuses_anything_but_reads_and_drafts(graph, method, path):
    client = graph.factory(TOKEN)
    with pytest.raises(BlockedRequest):
        client.request(method, path)
    assert graph.requests == [], "a refused request must never reach Microsoft Graph"


@pytest.mark.parametrize("bad_id", ["m1/send", "m1?x=1", "m1 m2", "", "../users"])
def test_message_ids_cannot_change_the_path(tools, bad_id):
    with pytest.raises(BlockedRequest):
        tools.get_message(CTX, bad_id)


def test_reply_draft_uses_create_reply_with_the_callers_token(tools, graph):
    result = tools.create_reply_draft(CTX, "AAMkAD=", "Thank you, the quote is attached.")
    request = graph.requests[-1]
    assert request.method == "POST"
    assert request.url.raw_path == b"/v1.0/me/messages/AAMkAD%3D/createReply"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {"comment": "Thank you, the quote is attached."}
    assert result["draft_id"] == "draft-1"
    assert "send it yourself" in result["next_step"]


def test_reply_all_draft(tools, graph):
    tools.create_reply_draft(CTX, "m1", "Noted, thanks.", reply_all=True)
    assert graph.requests[-1].url.path.endswith("/createReplyAll")


def test_saved_draft_is_recorded_in_the_audit_log(tools, audit):
    tools.create_reply_draft(CTX, "m1", "Confirmed for Tuesday.")
    [record] = audit.records()
    assert record["action"] == "create_reply_draft"
    assert record["outcome"] == "draft_saved"
    assert record["user"] == "ana@example-company.com"
    assert record["conversation_id"] == "conv-42"
    assert record["source_message_id"] == "m1" and record["draft_id"] == "draft-1"
    assert "Confirmed for Tuesday" not in json.dumps(record), "mail text must not be copied into the log"


def test_refused_draft_is_recorded_and_reported_as_revoked(audit):
    revoked = FakeGraph(status=403)
    tools = OutlookTools(audit=audit, graph_factory=revoked.factory)
    with pytest.raises(AccessRevoked):
        tools.create_reply_draft(CTX, "m1", "Hello")
    [record] = audit.records()
    assert record["outcome"] == "failed" and record["error"] == "AccessRevoked"


def test_switched_off_connector_refuses_every_tool(audit, graph):
    tools = OutlookTools(audit=audit, enabled=False, graph_factory=graph.factory)
    for call in (
        lambda: tools.list_recent_messages(CTX),
        lambda: tools.get_message(CTX, "m1"),
        lambda: tools.get_calendar(CTX),
        lambda: tools.create_reply_draft(CTX, "m1", "Hi"),
    ):
        with pytest.raises(ConnectorDisabled):
            call()
    assert graph.requests == []
    assert audit.records()[-1]["error"] == "ConnectorDisabled"


def test_missing_token_is_refused(tools):
    with pytest.raises(AccessRevoked):
        tools.list_recent_messages(CallContext(token=""))


def test_empty_reply_is_refused_and_recorded(tools, audit, graph):
    with pytest.raises(ValueError):
        tools.create_reply_draft(CTX, "m1", "   ")
    assert graph.requests == []
    assert audit.records()[-1]["outcome"] == "failed"


def test_unread_filter_lists_the_sort_property_first(tools, graph):
    tools.list_recent_messages(CTX, folder="Inbox", top=500, unread_only=True)
    params = graph.requests[-1].url.params
    assert params["$filter"].startswith("receivedDateTime ge")
    assert params["$top"] == "25", "the page size is capped"


def test_unknown_folder_is_refused(tools):
    with pytest.raises(ValueError):
        tools.list_recent_messages(CTX, folder="deleteditems")


def test_calendar_window_is_capped_at_31_days(tools, graph):
    tools.get_calendar(CTX, days_ahead=365)
    params = graph.requests[-1].url.params
    assert params["startDateTime"] == "2026-11-20T09:00:00+00:00"
    assert params["endDateTime"] == "2026-12-21T09:00:00+00:00"


def test_audit_chain_detects_an_edited_line(tools, audit):
    for text in ("First reply", "Second reply", "Third reply"):
        tools.create_reply_draft(CTX, "m1", text)
    assert audit.verify() == (True, None)

    lines = audit.path.read_text().splitlines()
    edited = json.loads(lines[1])
    edited["user"] = "someone-else@example-company.com"
    lines[1] = json.dumps(edited, sort_keys=True)
    audit.path.write_text("\n".join(lines) + "\n")
    assert audit.verify() == (False, 2)


def test_audit_chain_detects_a_removed_line(tools, audit):
    for text in ("First reply", "Second reply", "Third reply"):
        tools.create_reply_draft(CTX, "m1", text)
    lines = audit.path.read_text().splitlines()
    audit.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert audit.verify() == (False, 2)
