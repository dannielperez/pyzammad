# Service-desk compatibility port

Admitted by owner-merged UniqueOS #4574 (855509d70). SDK base bf3a0c31. Ports UniqueOS vendor/pyzammad contract into pyzammad.service_desk without replacing the public read client or exporting conflicting top-level names. Adds requests>=2.32,<3 as the compatibility transport dependency; keeps injected-session, connect/read tuple, existing redirect, error ambiguity, streaming response close and webhook semantics. This is not a transport rewrite or an overall wall-clock deadline.

Changes: service_desk.py, copied and expanded synthetic tests, dependency and README. Python 3.14-only unparenthesized exception tuples rewritten for Python>=3.11. No live provider/tenant/customer data. App still uses its legacy copy until a separate owner-merged SDK pin/dependency/import migration.

Validation: 17 SDK tests pass (6 existing read, 11 compatibility), mocked HTTP only. Python3.11 grammar parses the port. Changed-source Ruff lint and full formatting/diff checks pass. Repository-wide Ruff reports one pre-existing I001 in unchanged tests/test_client.py; not introduced here. No supported-version runtime matrix claimed locally.

Risk medium: new compatibility write surface and requests dependency, retaining established behavior. No automatic retry or new write authority. Rollback this additive module/dependency; top-level API unchanged. Owner review/merge required before app consumption. Follow-up: app seam imports from pyzammad.service_desk, lock/pin change and legacy removal with adapter and SDK contracts verified.
