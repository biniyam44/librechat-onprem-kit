"""Minimal Microsoft Graph client for the signed-in person's own mailbox.

The safety rule is enforced here, in code, not only in prompts: this client can
read mail and calendar data and create reply drafts, and it refuses every other
request. Sending, forwarding, moving and deleting mail are impossible through it,
whatever the model or the caller asks for.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# The only (method, path) pairs this connector may call. Everything else is refused.
_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GET", re.compile(r"^/me/mailFolders/(inbox|sentitems|drafts|archive)/messages$")),
    ("GET", re.compile(r"^/me/messages/[^/]+$")),
    ("GET", re.compile(r"^/me/calendarView$")),
    ("POST", re.compile(r"^/me/messages/[^/]+/createReply$")),
    ("POST", re.compile(r"^/me/messages/[^/]+/createReplyAll$")),
)

# Graph ids use the URL-safe base64 alphabet. Anything else (a slash, "?", "..") is refused.
_MESSAGE_ID = re.compile(r"^[A-Za-z0-9=_\-]{1,512}$")


class GraphError(Exception):
    """Microsoft Graph answered with an error."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Microsoft Graph error {status}: {message}")
        self.status = status


class AccessRevoked(GraphError):
    """The token is missing, expired or no longer has access (401/403)."""


class BlockedRequest(Exception):
    """The request is outside what this connector is allowed to do."""


def message_path(message_id: str, suffix: str = "") -> str:
    """Build /me/messages/{id}[/suffix] with the id validated and URL-encoded."""
    if not _MESSAGE_ID.match(message_id or ""):
        raise BlockedRequest("That does not look like an Outlook message id.")
    return f"/me/messages/{quote(message_id, safe='')}{suffix}"


def _error_message(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except Exception:  # noqa: BLE001 - any unexpected body still gives a useful error
        return resp.text[:200] or resp.reason_phrase


class GraphClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not token:
            raise AccessRevoked(401, "No Microsoft Graph token was provided. Sign in to LibreChat again.")
        self._client = httpx.Client(
            base_url=GRAPH_BASE,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=timeout,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        segments = path.split("/")
        if any(s in (".", "..") for s in segments) or "%2e" in path.lower():
            raise BlockedRequest(f"{path} contains a relative path segment.")
        if not any(method == allowed and rx.match(path) for allowed, rx in _ALLOWED):
            raise BlockedRequest(f"{method} {path} is not allowed by this connector.")
        resp = self._client.request(method, path, params=params, json=json, headers=headers)
        if resp.status_code in (401, 403):
            raise AccessRevoked(resp.status_code, _error_message(resp))
        if resp.status_code >= 400:
            raise GraphError(resp.status_code, _error_message(resp))
        return resp.json() if resp.content else {}

    def close(self) -> None:
        self._client.close()
