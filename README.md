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


## Service-desk compatibility surface

`pyzammad.service_desk` preserves the existing UniqueOS ticket/write and raw-webhook
contract independently of the top-level read client. Import its `ZammadClient`,
`ZammadTicketCreate`, `ZammadTicketUpdate`, `ZammadArticleCreate`,
`ZammadTransportError`, and `verify_webhook` from that module. The top-level
`pyzammad.ZammadClient`, models, and error types are unchanged.

The compatibility client accepts a `(connect, read)` timeout tuple and an optional
`requests.Session`; it retains requests transport behavior, including its redirect
policy. The read client's httpx behavior described above is unchanged. Keeping the
existing transport avoids changing mutation ambiguity and injected-session contracts
during migration. Neither timeout contract is a total wall-clock deadline.

Compatibility responses are streamed with a 1 MiB cap and always closed after parsing;
webhooks are capped at 512 KiB, authenticated over raw bytes using HMAC-SHA1, and
identified with SHA256. Sanitized errors expose `code`, `retryable`, and `ambiguous`.
The client never automatically retries mutations; callers retain their existing
admission and ambiguity handling. This port does not grant new write permissions.
UniqueOS must separately consume an owner-merged SDK pin before removing its legacy
copy. All tests use synthetic data and mocked transports.

Ticket responses expose the complete bounded provider JSON object through
`ZammadTicket.fields` and `ZammadTicket.field(name, default)`. Zammad custom object
attributes are returned at the top level, so consumers can read any fields they own
without adding application-specific names to this SDK. Field contents are untrusted
provider data: consumers remain responsible for type, length, URL-host, identifier,
and authorization validation before using them.
