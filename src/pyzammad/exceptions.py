"""Exception hierarchy for pyzammad."""


class ZammadError(Exception):
    """Base error for all client failures."""


class ConnectionError(ZammadError):
    """The Zammad endpoint could not be reached."""


class AuthenticationError(ZammadError):
    """The supplied API token was rejected."""


class PermissionDenied(ZammadError):
    """The token lacks permission for the requested resource."""


class NotFound(ZammadError):
    """The requested Zammad resource does not exist."""


class RateLimitError(ZammadError):
    """Zammad rate-limited the request."""


class APIError(ZammadError):
    """Zammad returned an unexpected response."""


class ResponseFormatError(ZammadError):
    """Zammad returned JSON with an unexpected shape."""
