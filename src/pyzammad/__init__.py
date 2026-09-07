"""Typed Python client for Zammad."""

from .client import DEFAULT_TIMEOUT_SECONDS, MAX_PAGE_SIZE, ZammadClient
from .exceptions import (
    APIError,
    AuthenticationError,
    ConnectionError,
    NotFound,
    PermissionDenied,
    RateLimitError,
    ResponseFormatError,
    ZammadError,
)
from .models import Article, Group, Ticket, User

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_PAGE_SIZE",
    "APIError",
    "Article",
    "AuthenticationError",
    "ConnectionError",
    "Group",
    "NotFound",
    "PermissionDenied",
    "RateLimitError",
    "ResponseFormatError",
    "Ticket",
    "User",
    "ZammadClient",
    "ZammadError",
]
