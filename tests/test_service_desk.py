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
    ZammadTicketWriteback,
    ZammadTransportError,
    verify_webhook,
)

_CREDENTIAL = "opaque-fixture-credential"
_SIGNING_MATERIAL = "opaque-fixture-signing-material"


def _response(payload: dict | list, *, status_code: int = 200) -> Mock:
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


def test_ticket_and_user_identity_fields_are_typed():
    session = Mock()
    session.request.side_effect = [
        _response(
            {
                "id": 42,
                "number": "74002",
                "title": "Camera offline",
                "state": "open",
                "priority": "2 normal",
                "customer_id": 7,
                "owner_id": 3,
                "organization_id": 9,
                "uniqueos_site_id": "ed93dc7f-d127-46e9-bb1e-1b18c11c965a",
                "updated_at": "2026-09-18T12:00:00Z",
            },
        ),
        _response(
            {
                "id": 3,
                "login": "agent@example.test",
                "email": "agent@example.test",
                "firstname": "Ada",
                "lastname": "Lovelace",
                "active": True,
            },
        ),
    ]
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=session,
    )

    ticket = client.get_ticket("42")
    user = client.get_user(ticket.owner_id)

    assert ticket.owner_id == "3"
    assert ticket.site_reference == "ed93dc7f-d127-46e9-bb1e-1b18c11c965a"
    assert user.external_id == "3"
    assert user.email == "agent@example.test"
    assert user.display_name == "Ada Lovelace"
    assert client.ticket_url(ticket.number) == "https://desk.example.test/ticket/74002"


def test_ticket_number_lookup_requires_one_exact_match():
    session = Mock()
    session.request.return_value = _response(
        [
            {"id": 41, "number": "74001", "title": "Other"},
            {"id": 42, "number": "74002", "title": "Camera offline"},
        ],
    )
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=session,
    )

    ticket = client.find_ticket_by_number("74002")

    assert ticket.external_id == "42"
    assert session.request.call_args.args[1].endswith(
        "/api/v1/tickets/search?query=number%3A74002",
    )


def test_ticket_number_lookup_rejects_missing_or_duplicate_exact_matches():
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=Mock(),
    )
    client._session.request.return_value = _response([])  # noqa: SLF001
    with pytest.raises(ZammadTransportError, match="ticket_not_found"):
        client.find_ticket_by_number("74002")

    client._session.request.return_value = _response(  # noqa: SLF001
        [
            {"id": 42, "number": "74002"},
            {"id": 43, "number": "74002"},
        ],
    )
    with pytest.raises(ZammadTransportError, match="ticket_ambiguous"):
        client.find_ticket_by_number("74002")


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


def test_correlated_writeback_uses_one_ticket_mutation():
    session = Mock()
    session.request.return_value = _response(
        {
            "id": 42,
            "number": "74002",
            "title": "Camera offline",
            "state": "closed",
            "priority": "high",
            "customer_id": 7,
        },
    )
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=session,
    )

    receipt = client.writeback_ticket(
        "42",
        ZammadTicketWriteback(
            body="Verification complete.",
            internal=True,
            status="closed",
            correlation_id="corr-123",
        ),
    )

    assert receipt.ticket.status == "closed"
    assert receipt.correlation_id == "corr-123"
    assert session.request.call_args.kwargs["json"] == {
        "state": "closed",
        "article": {
            "subject": "UniqueOS work update",
            "body": "Verification complete.\n\n[UniqueOS correlation: corr-123]",
            "type": "note",
            "internal": True,
        },
    }


def test_writeback_reconciliation_requires_note_and_transition():
    session = Mock()
    articles = _response(
        {
            "ignored": "the list response is supplied below",
        },
    )
    session.request.side_effect = [
        _response({"id": 42, "state": "closed"}),
        articles,
    ]
    articles.iter_content.return_value = [
        json.dumps([{"id": 8, "body": "[UniqueOS correlation: corr-123]"}]).encode(),
    ]
    client = ZammadClient(
        base_url="https://desk.example.test",
        api_token=_CREDENTIAL,
        timeout=(2, 8),
        session=session,
    )
    command = ZammadTicketWriteback("unused", False, "closed", "corr-123")

    result = client.reconcile_writeback("42", command)

    assert result.note_found is True
    assert result.transition_applied is True
    assert session.request.call_count == 2


@pytest.mark.parametrize("payload", [b"", b"x" * ((1 << 19) + 1)])
def test_webhook_bounds_reject_before_signature_or_json(payload):
    with pytest.raises(ZammadTransportError, match="zammad_webhook_invalid"):
        verify_webhook(payload, {}, secret=_SIGNING_MATERIAL)
