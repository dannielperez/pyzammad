"""Synchronous, read-first Zammad REST API client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .exceptions import (
    APIError,
    AuthenticationError,
    ConnectionError,
    NotFound,
    PermissionDenied,
    RateLimitError,
    ResponseFormatError,
)
from .models import Article, Group, Ticket, User

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_PAGE_SIZE = 100


class ZammadClient:
    """Read-first client authenticated with a scoped Zammad access token."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not api_token.strip():
            raise ValueError("api_token is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={
                "Accept": "application/json",
                "Authorization": f"Token token={api_token}",
                "User-Agent": "pyzammad/0.1.0",
            },
            timeout=timeout,
            verify=verify_ssl,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> ZammadClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(path.lstrip("/"), params=params)
        except httpx.TimeoutException as exc:
            raise ConnectionError("Zammad request timed out") from exc
        except httpx.RequestError as exc:
            raise ConnectionError("Zammad endpoint is unreachable") from exc

        if response.status_code == 401:
            raise AuthenticationError("Zammad rejected the API token")
        if response.status_code == 403:
            raise PermissionDenied("Zammad token lacks permission for this resource")
        if response.status_code == 404:
            raise NotFound("Zammad resource was not found")
        if response.status_code == 429:
            raise RateLimitError("Zammad rate limit exceeded")
        if response.is_error:
            raise APIError(f"Zammad returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ResponseFormatError("Zammad returned invalid JSON") from exc

    @staticmethod
    def _list(payload: Any, resource: str) -> list[dict[str, Any]]:
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ResponseFormatError(f"Zammad {resource} response must be a list of objects")
        return payload

    @staticmethod
    def _page_params(page: int, per_page: int) -> dict[str, int]:
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= per_page <= MAX_PAGE_SIZE:
            raise ValueError(f"per_page must be between 1 and {MAX_PAGE_SIZE}")
        return {"page": page, "per_page": per_page}

    def me(self) -> User:
        payload = self._get("api/v1/users/me")
        if not isinstance(payload, dict):
            raise ResponseFormatError("Zammad current-user response must be an object")
        return User.from_payload(payload)

    def tickets(self, *, page: int = 1, per_page: int = 50) -> list[Ticket]:
        payload = self._get("api/v1/tickets", params=self._page_params(page, per_page))
        return [Ticket.from_payload(row) for row in self._list(payload, "tickets")]

    def ticket(self, ticket_id: int) -> Ticket:
        if ticket_id < 1:
            raise ValueError("ticket_id must be positive")
        payload = self._get(f"api/v1/tickets/{ticket_id}")
        if not isinstance(payload, dict):
            raise ResponseFormatError("Zammad ticket response must be an object")
        return Ticket.from_payload(payload)

    def ticket_articles(self, ticket_id: int) -> list[Article]:
        if ticket_id < 1:
            raise ValueError("ticket_id must be positive")
        payload = self._get(f"api/v1/ticket_articles/by_ticket/{ticket_id}")
        return [Article.from_payload(row) for row in self._list(payload, "articles")]

    def groups(self, *, page: int = 1, per_page: int = 100) -> list[Group]:
        """List groups when the token has Zammad's ``admin.group`` permission."""
        payload = self._get("api/v1/groups", params=self._page_params(page, per_page))
        return [Group.from_payload(row) for row in self._list(payload, "groups")]

    def users(self, *, page: int = 1, per_page: int = 100) -> list[User]:
        """List users when the token has Zammad's ``admin.user`` permission."""
        payload = self._get("api/v1/users", params=self._page_params(page, per_page))
        return [User.from_payload(row) for row in self._list(payload, "users")]
