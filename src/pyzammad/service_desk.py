"""Small Zammad REST/webhook wrapper with no Django dependencies.

The wrapper owns Zammad URLs, authentication, JSON parsing, bounded network
waits, response limits, and webhook signature verification. This compatibility
surface preserves the existing service-desk contract.
The top-level public read client remains independent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

import requests

_MAX_RESPONSE_BYTES = 1 << 20
_MAX_WEBHOOK_BYTES = 1 << 19
_RETRYABLE_STATUS_CODES = frozenset((408, 425, 429))
_SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))
_HTTP_CLIENT_ERROR = 400
_HTTP_SERVER_ERROR = 500
_CONFIGURATION_INVALID = "zammad_configuration_invalid"
_CONNECT_TIMEOUT = "zammad_connect_timeout"
_CONNECTION_FAILED = "zammad_connection_failed"
_OUTCOME_UNKNOWN = "zammad_outcome_unknown"
_RATE_LIMITED = "zammad_rate_limited"
_REJECTED = "zammad_rejected"
_RESPONSE_INVALID = "zammad_response_invalid"
_RESPONSE_TOO_LARGE = "zammad_response_too_large"
_TRANSPORT_FAILED = "zammad_transport_failed"
_WEBHOOK_INVALID = "zammad_webhook_invalid"
_WEBHOOK_JSON_INVALID = "zammad_webhook_json_invalid"
_WEBHOOK_SIGNATURE_INVALID = "zammad_webhook_signature_invalid"
_PRIORITY_NAMES = {1: "low", 2: "normal", 3: "high"}
_CORRELATION_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}\Z")


class ZammadTransportError(RuntimeError):
    """Sanitized provider failure with explicit retry semantics."""

    def __init__(self, code: str, *, retryable: bool, ambiguous: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous


def _error(
    code: str,
    *,
    retryable: bool,
    ambiguous: bool,
) -> ZammadTransportError:
    return ZammadTransportError(code, retryable=retryable, ambiguous=ambiguous)


@dataclass(frozen=True, slots=True)
class ZammadWebhook:
    """Authenticated webhook payload plus a replay-stable delivery fingerprint."""

    event_id: str
    ticket_id: str
    ticket_updated_at: str
    article_id: str = ""


@dataclass(frozen=True, slots=True)
class ZammadTicketCreate:
    title: str
    body: str
    customer_id: str
    group: str
    priority: str
    custom_fields: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ZammadTicketUpdate:
    status: str | None = None
    priority: str | None = None


@dataclass(frozen=True, slots=True)
class ZammadArticleCreate:
    body: str
    internal: bool


@dataclass(frozen=True, slots=True)
class ZammadTicketWriteback:
    body: str
    internal: bool
    status: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ZammadTicket:
    external_id: str
    number: str
    title: str
    status: str
    priority: str
    customer_id: str
    organization_id: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ZammadWritebackReceipt:
    ticket: ZammadTicket
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ZammadWritebackReconciliation:
    ticket: ZammadTicket
    note_found: bool
    transition_applied: bool
    correlation_id: str


def _parse_ticket(payload: dict[str, Any]) -> ZammadTicket:
    external_id = payload.get("id")
    if external_id is None:
        raise _error(_RESPONSE_INVALID, retryable=False, ambiguous=True)
    priority = payload.get("priority", "")
    if not priority:
        priority_id = payload.get("priority_id")
        priority = _PRIORITY_NAMES.get(priority_id, "") if isinstance(priority_id, int) else ""
    return ZammadTicket(
        external_id=str(external_id),
        number=str(payload.get("number", "")),
        title=str(payload.get("title", "")),
        status=str(payload.get("state", payload.get("state_id", ""))),
        priority=str(priority),
        customer_id=str(payload.get("customer_id", "")),
        organization_id=str(payload.get("organization_id", "") or ""),
        updated_at=str(payload.get("updated_at", "")),
    )


def verify_webhook(
    payload: bytes,
    headers: dict[str, str],
    *,
    secret: str,
) -> ZammadWebhook:
    """Verify Zammad's ``x-hub-signature`` HMAC-SHA1 and parse bounded JSON."""

    if not secret or not payload or len(payload) > _MAX_WEBHOOK_BYTES:
        raise _error(_WEBHOOK_INVALID, retryable=False, ambiguous=False)
    normalized_headers = {key.casefold(): value for key, value in headers.items()}
    supplied = normalized_headers.get("x-hub-signature", "")
    expected = (
        "sha1="
        + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha1,
        ).hexdigest()
    )
    if not hmac.compare_digest(supplied, expected):
        raise _error(_WEBHOOK_SIGNATURE_INVALID, retryable=False, ambiguous=False)
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError):
        raise _error(
            _WEBHOOK_JSON_INVALID,
            retryable=False,
            ambiguous=False,
        ) from None
    if not isinstance(parsed, dict):
        raise _error(_WEBHOOK_JSON_INVALID, retryable=False, ambiguous=False)
    ticket = parsed.get("ticket")
    if not isinstance(ticket, dict) or ticket.get("id") is None:
        raise _error(_WEBHOOK_JSON_INVALID, retryable=False, ambiguous=False)
    article = parsed.get("article")
    return ZammadWebhook(
        event_id=hashlib.sha256(payload).hexdigest(),
        ticket_id=str(ticket["id"]),
        ticket_updated_at=str(ticket.get("updated_at", "")),
        article_id=(str(article.get("id", "")) if isinstance(article, dict) else ""),
    )


def _read_bounded(response: requests.Response) -> bytearray:
    declared_length = response.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > _MAX_RESPONSE_BYTES:
                raise _error(_RESPONSE_TOO_LARGE, retryable=False, ambiguous=True)
        except ValueError:
            pass
    raw = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        raw.extend(chunk)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise _error(_RESPONSE_TOO_LARGE, retryable=False, ambiguous=True)
    return raw


def _parse_response_value(response: requests.Response) -> Any:
    if response.status_code in _RETRYABLE_STATUS_CODES:
        raise _error(_RATE_LIMITED, retryable=True, ambiguous=False)
    if response.status_code >= _HTTP_SERVER_ERROR:
        raise _error(_OUTCOME_UNKNOWN, retryable=False, ambiguous=True)
    if response.status_code >= _HTTP_CLIENT_ERROR:
        raise _error(_REJECTED, retryable=False, ambiguous=False)
    raw = _read_bounded(response)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        raise _error(
            _RESPONSE_INVALID,
            retryable=False,
            ambiguous=True,
        ) from None
    return parsed


def _parse_response(response: requests.Response) -> dict[str, Any]:
    parsed = _parse_response_value(response)
    if not isinstance(parsed, dict):
        raise _error(_RESPONSE_INVALID, retryable=False, ambiguous=True)
    return parsed


def _correlation_marker(correlation_id: str) -> str:
    if not _CORRELATION_ID.fullmatch(correlation_id):
        raise _error(_CONFIGURATION_INVALID, retryable=False, ambiguous=False)
    return f"[UniqueOS correlation: {correlation_id}]"


def _connection_failure(method: str) -> ZammadTransportError:
    if method.upper() in _SAFE_METHODS:
        return _error(_CONNECTION_FAILED, retryable=True, ambiguous=False)
    return _error(_OUTCOME_UNKNOWN, retryable=False, ambiguous=True)


class ZammadClient:
    """Timeout-bounded client for the narrow ticket surface used by the POC."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout: tuple[float, float],
        session: requests.Session | None = None,
    ) -> None:
        clean_url = base_url.strip().rstrip("/")
        if (
            not clean_url.startswith(("http://", "https://"))
            or not api_token
            or any(value <= 0 for value in timeout)
        ):
            raise _error(_CONFIGURATION_INVALID, retryable=False, ambiguous=False)
        self.base_url = clean_url
        self.timeout = timeout
        self._session = session or requests.Session()
        self._headers = {
            "Authorization": f"Token token={api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers,
                json=body,
                timeout=self.timeout,
                stream=True,
            )
        except requests.ConnectTimeout:
            raise _error(_CONNECT_TIMEOUT, retryable=True, ambiguous=False) from None
        except requests.ReadTimeout:
            raise _connection_failure(method) from None
        except requests.ConnectionError:
            raise _connection_failure(method) from None
        except requests.RequestException:
            raise _error(_TRANSPORT_FAILED, retryable=False, ambiguous=True) from None

        try:
            try:
                return _parse_response(response)
            except requests.RequestException:
                raise _connection_failure(method) from None
        finally:
            response.close()

    def _request_value(self, method: str, path: str) -> Any:
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers,
                json=None,
                timeout=self.timeout,
                stream=True,
            )
        except requests.ConnectTimeout:
            raise _error(_CONNECT_TIMEOUT, retryable=True, ambiguous=False) from None
        except (requests.ReadTimeout, requests.ConnectionError):
            raise _connection_failure(method) from None
        except requests.RequestException:
            raise _error(_TRANSPORT_FAILED, retryable=False, ambiguous=True) from None
        try:
            try:
                return _parse_response_value(response)
            except requests.RequestException:
                raise _connection_failure(method) from None
        finally:
            response.close()

    def create_ticket(self, command: ZammadTicketCreate) -> ZammadTicket:
        payload = {
            "title": command.title,
            "customer_id": command.customer_id,
            "group": command.group,
            "priority": command.priority,
            "article": {
                "subject": command.title,
                "body": command.body,
                "type": "note",
                "internal": False,
            },
            **command.custom_fields,
        }
        return _parse_ticket(self._request("POST", "/api/v1/tickets", body=payload))

    def get_ticket(self, external_id: str) -> ZammadTicket:
        return _parse_ticket(self._request("GET", f"/api/v1/tickets/{external_id}"))

    def update_ticket(
        self,
        external_id: str,
        command: ZammadTicketUpdate,
    ) -> ZammadTicket:
        payload = {}
        if command.status is not None:
            payload["state"] = command.status
        if command.priority is not None:
            payload["priority"] = command.priority
        return _parse_ticket(
            self._request("PUT", f"/api/v1/tickets/{external_id}", body=payload),
        )

    def create_article(
        self,
        external_id: str,
        command: ZammadArticleCreate,
    ) -> str:
        payload = {
            "ticket_id": external_id,
            "body": command.body,
            "type": "note",
            "internal": command.internal,
        }
        result = self._request("POST", "/api/v1/ticket_articles", body=payload)
        article_id = result.get("id")
        if article_id is None:
            raise _error(_RESPONSE_INVALID, retryable=False, ambiguous=True)
        return str(article_id)

    def writeback_ticket(
        self,
        external_id: str,
        command: ZammadTicketWriteback,
    ) -> ZammadWritebackReceipt:
        """Append one correlated note and state change in one provider request."""
        marker = _correlation_marker(command.correlation_id)
        payload = {
            "state": command.status,
            "article": {
                "subject": "UniqueOS work update",
                "body": f"{command.body}\n\n{marker}",
                "type": "note",
                "internal": command.internal,
            },
        }
        ticket = _parse_ticket(
            self._request("PUT", f"/api/v1/tickets/{external_id}", body=payload),
        )
        return ZammadWritebackReceipt(ticket, command.correlation_id)

    def reconcile_writeback(
        self,
        external_id: str,
        command: ZammadTicketWriteback,
    ) -> ZammadWritebackReconciliation:
        """Read back both effects of an ambiguously acknowledged write."""
        marker = _correlation_marker(command.correlation_id)
        ticket = self.get_ticket(external_id)
        articles = self._request_value(
            "GET",
            f"/api/v1/ticket_articles/by_ticket/{external_id}",
        )
        if not isinstance(articles, list) or any(
            not isinstance(article, dict) for article in articles
        ):
            raise _error(_RESPONSE_INVALID, retryable=False, ambiguous=True)
        note_found = any(marker in str(article.get("body", "")) for article in articles)
        return ZammadWritebackReconciliation(
            ticket=ticket,
            note_found=note_found,
            transition_applied=ticket.status == command.status,
            correlation_id=command.correlation_id,
        )
