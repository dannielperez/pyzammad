"""Small typed projections of the Zammad API payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class User:
    id: int
    login: str
    email: str
    firstname: str
    lastname: str
    active: bool

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> User:
        return cls(
            id=int(value["id"]),
            login=str(value.get("login") or ""),
            email=str(value.get("email") or ""),
            firstname=str(value.get("firstname") or ""),
            lastname=str(value.get("lastname") or ""),
            active=bool(value.get("active", False)),
        )


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    number: str
    title: str
    group_id: int
    state_id: int
    priority_id: int
    owner_id: int | None
    customer_id: int | None
    article_count: int
    created_at: str
    updated_at: str

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> Ticket:
        def optional_int(key: str) -> int | None:
            raw = value.get(key)
            return int(raw) if raw is not None else None

        return cls(
            id=int(value["id"]),
            number=str(value.get("number") or ""),
            title=str(value.get("title") or ""),
            group_id=int(value["group_id"]),
            state_id=int(value["state_id"]),
            priority_id=int(value["priority_id"]),
            owner_id=optional_int("owner_id"),
            customer_id=optional_int("customer_id"),
            article_count=int(value.get("article_count") or 0),
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class Group:
    id: int
    name: str
    active: bool

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> Group:
        return cls(
            id=int(value["id"]),
            name=str(value.get("name") or ""),
            active=bool(value.get("active", False)),
        )


@dataclass(frozen=True, slots=True)
class Article:
    id: int
    ticket_id: int
    internal: bool
    body: str
    content_type: str
    created_at: str

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> Article:
        return cls(
            id=int(value["id"]),
            ticket_id=int(value["ticket_id"]),
            internal=bool(value.get("internal", False)),
            body=str(value.get("body") or ""),
            content_type=str(value.get("content_type") or ""),
            created_at=str(value.get("created_at") or ""),
        )
