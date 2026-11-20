import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "connectors" / "outlook_drafts"))
sys.path.insert(0, str(ROOT / "scripts"))

from outlook_drafts.graph import GraphClient  # noqa: E402


def fake_jwt(**claims: str) -> str:
    """An unsigned token with the given claims (Graph is mocked in tests, so nothing verifies it)."""

    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}.signature"


@pytest.fixture
def root() -> Path:
    return ROOT


class FakeGraph:
    """Records every request and answers like Microsoft Graph would."""

    def __init__(self, status: int = 200):
        self.requests: list[httpx.Request] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json={"error": {"message": "Access is denied."}})
        path = request.url.path
        if path.endswith(("/createReply", "/createReplyAll")):
            return httpx.Response(201, json={"id": "draft-1", "subject": "RE: Quote", "webLink": "https://outlook/d1"})
        if path.endswith("/messages") or path.endswith("/calendarView"):
            return httpx.Response(200, json={"value": []})
        return httpx.Response(200, json={"id": "m1", "subject": "Quote", "body": {"content": "Hello"}})

    def factory(self, token: str) -> GraphClient:
        return GraphClient(token, transport=httpx.MockTransport(self.handler))
