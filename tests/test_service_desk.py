"""Wire-contract tests for the Django-free Zammad SDK wrapper."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import Mock

import pytest
import requests
from pyzammad.service_desk import (
    ZammadClient,
    ZammadTicketCreate,
    ZammadTicketUpdate,
    ZammadTransportError,
    verify_webhook,
)

_CREDENTIAL = "opaque-fixture-credential"
_SIGNING_MATERIAL = "opaque-fixture-signing-material"


def _response(payload: dict, *, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.content = json.dumps(payload).encode()
    response.headers = {}
    response.iter_content.return_value = [response.content]
    return response


def test_client_owns_zammad_wire_auth_payload_and_timeouts():
    session = Mock()
    session.request.return_value = _response(
        {
            "id": 42,
            "number": "74002",
            "title": "Camera offline",
            "state_id": 1,
            "priority_id": 3,
            "customer_id": 7,
        },
        status_code=201,
    )
    client = ZammadClient(
        base_url="https://desk.example.test/",
        api_token=_CREDENTIAL,
        timeout=(2.0, 8.0),
        session=session,
    )

    result = client.create_ticket(
        ZammadTicketCreate(
            title="Camera offline",
            body="Device offline.",
            customer_id="7",
            group="Users",
            priority="high",
            custom_fields={},
        ),
    )

    assert result.external_id == "42"
    session.request.assert_called_once_with(
        "POST",
        "https://desk.example.test/api/v1/tickets",
        headers={
            "Authorization": f"Token token={_CREDENTIAL}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "title": "Camera offline",
            "customer_id": "7",
            "group": "Users",
            "priority": "high",
            "article": {
                "subject": "Camera offline",
                "body": "Device offline.",
                "type": "note",
                "internal": False,
            },
        },
        timeout=(2.0, 8.0),
        stream=True,
    )
    session.request.return_value.close.assert_called_once_with()


def test_mutation_read_timeout_is_ambiguous_and_not_blindly_retryable():
    session = Mock()
    session.request.side_effect = requests.ReadTimeout("provider detail")
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2.0, 8.0),
        session=session,
    )

    with pytest.raises(ZammadTransportError) as raised:
        client.update_ticket("42", ZammadTicketUpdate(status="closed"))

    assert str(raised.value) == "zammad_outcome_unknown"
    assert raised.value.ambiguous is True
    assert raised.value.retryable is False


def test_connection_failure_is_retryable_for_get_but_ambiguous_for_write():
    session = Mock()
    session.request.side_effect = requests.ConnectionError("provider detail")
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2.0, 8.0),
        session=session,
    )

    with pytest.raises(ZammadTransportError) as read_error:
        client.get_ticket("42")
    with pytest.raises(ZammadTransportError) as write_error:
        client.update_ticket("42", ZammadTicketUpdate(status="closed"))

    assert read_error.value.retryable is True
    assert read_error.value.ambiguous is False
    assert write_error.value.retryable is False
    assert write_error.value.ambiguous is True


def test_declared_oversized_response_is_rejected_before_streaming():
    session = Mock()
    response = _response({"id": 42})
    response.headers = {"content-length": str((1 << 20) + 1)}
    session.request.return_value = response
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2.0, 8.0),
        session=session,
    )

    with pytest.raises(ZammadTransportError, match="response_too_large"):
        client.get_ticket("42")

    response.iter_content.assert_not_called()
    response.close.assert_called_once_with()


def test_webhook_verification_is_authenticated_and_replay_stable():
    raw = json.dumps(
        {"ticket": {"id": 42, "updated_at": "2026-08-28"}},
        separators=(",", ":"),
    ).encode()
    signature = (
        "sha1="
        + hmac.new(
            _SIGNING_MATERIAL.encode(),
            raw,
            hashlib.sha1,
        ).hexdigest()
    )

    first = verify_webhook(
        raw,
        {"X-Hub-Signature": signature},
        secret=_SIGNING_MATERIAL,
    )
    second = verify_webhook(
        raw,
        {"x-hub-signature": signature},
        secret=_SIGNING_MATERIAL,
    )

    assert first.event_id == second.event_id == hashlib.sha256(raw).hexdigest()
    assert first.ticket_id == "42"
    with pytest.raises(ZammadTransportError, match="signature_invalid"):
        verify_webhook(
            raw + b" ",
            {"x-hub-signature": signature},
            secret=_SIGNING_MATERIAL,
        )


def test_read_and_service_desk_clients_remain_distinct():
    from pyzammad import ZammadClient as ReadClient

    assert ReadClient is not ZammadClient
    assert callable(ReadClient.me)


@pytest.mark.parametrize("internal", [True, False])
def test_article_visibility_and_identifier(internal):
    from pyzammad.service_desk import ZammadArticleCreate

    session = Mock()
    session.request.return_value = _response({"id": 84})
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=session,
    )
    assert client.create_article("42", ZammadArticleCreate("note", internal)) == "84"
    assert session.request.call_args.kwargs["json"] == {
        "ticket_id": "42",
        "body": "note",
        "type": "note",
        "internal": internal,
    }
    session.request.return_value.close.assert_called_once_with()


def test_actual_stream_limit_closes_response_without_declared_size():
    session = Mock()
    response = _response({"id": 42})
    response.iter_content.return_value = [b"x" * (1 << 20), b"x"]
    session.request.return_value = response
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=session,
    )
    with pytest.raises(ZammadTransportError, match="response_too_large"):
        client.get_ticket("42")
    response.close.assert_called_once_with()


@pytest.mark.parametrize("payload", [b"", b"x" * ((1 << 19) + 1)])
def test_webhook_bounds_reject_before_signature_or_json(payload):
    with pytest.raises(ZammadTransportError, match="zammad_webhook_invalid"):
        verify_webhook(payload, {}, secret=_SIGNING_MATERIAL)
