from __future__ import annotations

import json

import httpx
import pytest

from pyzammad import AuthenticationError, PermissionDenied, ResponseFormatError, ZammadClient

TOKEN = "synthetic-token"  # noqa: S105
BASE_URL = "https://support.example.invalid"


def _client(handler) -> ZammadClient:
    return ZammadClient(
        base_url=BASE_URL,
        api_token=TOKEN,
        transport=httpx.MockTransport(handler),
    )


def _json(status: int, payload) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


def test_me_uses_token_header_and_typed_projection():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/users/me"
        assert request.headers["Authorization"] == f"Token token={TOKEN}"
        return _json(
            200,
            {
                "id": 7,
                "login": "svc",
                "email": "svc@example.invalid",
                "active": True,
            },
        )

    with _client(handler) as client:
        user = client.me()

    assert user.id == 7
    assert user.login == "svc"
    assert user.active is True


def test_tickets_are_bounded_and_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"page": "2", "per_page": "25"}
        return _json(
            200,
            [
                {
                    "id": 3,
                    "number": "26003",
                    "title": "Test",
                    "group_id": 1,
                    "state_id": 2,
                    "priority_id": 2,
                    "owner_id": None,
                    "customer_id": 9,
                    "article_count": 1,
                    "created_at": "2026-09-07T00:00:00Z",
                    "updated_at": "2026-09-07T00:01:00Z",
                }
            ],
        )

    with _client(handler) as client:
        tickets = client.tickets(page=2, per_page=25)

    assert tickets[0].number == "26003"
    assert tickets[0].customer_id == 9


@pytest.mark.parametrize("status,error", [(401, AuthenticationError), (403, PermissionDenied)])
def test_auth_errors_never_echo_response_body(status, error):
    with (
        _client(lambda _request: _json(status, {"error": "synthetic-token"})) as client,
        pytest.raises(error) as caught,
    ):
        client.me()
    assert TOKEN not in str(caught.value)


def test_invalid_shape_is_rejected():
    with (
        _client(lambda _request: _json(200, {"tickets": []})) as client,
        pytest.raises(ResponseFormatError),
    ):
        client.tickets()


def test_page_size_is_capped_before_network_call():
    with (
        _client(lambda _request: pytest.fail("network should not run")) as client,
        pytest.raises(ValueError, match="between 1 and 100"),
    ):
        client.tickets(per_page=101)
