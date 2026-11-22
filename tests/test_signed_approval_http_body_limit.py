"""HTTP-boundary regression tests for signed-approval request size limits."""

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.main import app


MAX_SIGNED_APPROVAL_REQUEST_BYTES = 66_128
SIGNED_APPROVAL_PATH = (
    f"/checkout-orders/{uuid.UUID(int=1)}/signed-approval"
)


def test_oversized_malformed_signed_approval_is_rejected_before_json_parsing():
    body = b"{" + (b" " * MAX_SIGNED_APPROVAL_REQUEST_BYTES)

    response = TestClient(app).post(
        SIGNED_APPROVAL_PATH,
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413


def test_streaming_signed_approval_limit_applies_without_content_length():
    body = b"{" + (b" " * MAX_SIGNED_APPROVAL_REQUEST_BYTES)
    chunks = [body[:32_768], body[32_768:]]
    sent = []

    async def receive():
        chunk = chunks.pop(0)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": bool(chunks),
        }

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": SIGNED_APPROVAL_PATH,
        "raw_path": SIGNED_APPROVAL_PATH.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    asyncio.run(app(scope, receive, send))

    response_start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    assert response_start["status"] == 413
