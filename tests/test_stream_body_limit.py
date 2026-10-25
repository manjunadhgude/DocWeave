"""Regression test for API bodies without a declared Content-Length."""

import asyncio
from unittest.mock import patch

from docweave.api import APIRequestSecurityMiddleware


def test_streamed_body_without_content_length_is_limited():
    messages = [
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678", "more_body": False},
    ]
    sent = []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") == "http.request" and not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/reconcile/two-way/json",
        "raw_path": b"/api/v1/reconcile/two-way/json",
        "query_string": b"",
        "headers": [],  # Intentionally no Content-Length header.
        "client": ("stream-limit-test-client", 12345),
        "server": ("testserver", 80),
    }

    middleware = APIRequestSecurityMiddleware(downstream)
    with patch("docweave.api.MAX_JSON_REQUEST_BYTES", 6):
        asyncio.run(middleware(scope, receive, send))

    starts = [item for item in sent if item.get("type") == "http.response.start"]
    bodies = [item.get("body", b"") for item in sent if item.get("type") == "http.response.body"]
    assert starts and starts[0]["status"] == 413
    assert b"Request body exceeds" in b"".join(bodies)
