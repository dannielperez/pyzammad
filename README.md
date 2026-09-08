# pyzammad

Typed, timeout-bounded Python client for Zammad's REST API. The initial surface
is deliberately read-first for operations and compliance dashboards.

```python
from pyzammad import ZammadClient

with ZammadClient(
    base_url="https://support.example.invalid",
    api_token="a-scoped-access-token",
) as client:
    identity = client.me()
    tickets = client.tickets(per_page=25)
```

Use a dedicated Zammad service user and a narrowly scoped access token. Basic
authentication is intentionally unsupported. Ticket visibility follows the
service user's Zammad group access. Methods for users and groups require their
corresponding Zammad administrative permissions; do not grant them merely for a
connection test.

The library never logs tokens or response bodies in raised HTTP errors. Every
request is timeout-bounded, TLS verification is enabled by default, redirects
are not followed, and list page sizes are capped at 100.
