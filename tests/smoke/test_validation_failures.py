"""Bot half rejects malformed / mis-signed channel JWTs with specific reasons.

The whole point of the bot half is to surface auth bugs in CI; the
specific rejection strings are part of the contract.
"""

import time

import jwt as _jwt

from twins_microsoft_bot_framework.crypto import generate_keypair_pem
from twins_microsoft_bot_framework.tokens import ISSUER


def _register_instance(client, tenant_headers, *, app_id, trusted_url):
    return client.post(
        "/_twin/accounts",
        json={
            "kind": "bot_instance",
            "app_id": app_id,
            "trusted_openid_url": trusted_url,
        },
        headers=tenant_headers,
    ).get_json()


def _patch_requests(monkeypatch, client):
    """Route requests.{get,post} through the Flask test client."""
    import requests as _requests
    from urllib.parse import urlparse

    class _Resp:
        def __init__(self, r):
            self._r = r
            self.status_code = r.status_code

        def json(self):
            return self._r.get_json()

        def raise_for_status(self):
            if self.status_code >= 400:
                raise _requests.exceptions.HTTPError(
                    f"{self.status_code}", response=self
                )

    def _get(url, **kwargs):
        return _Resp(client.get(urlparse(url).path, headers=kwargs.get("headers")))

    def _post(url, **kwargs):
        return _Resp(
            client.post(
                urlparse(url).path,
                json=kwargs.get("json"),
                data=kwargs.get("data"),
                headers=kwargs.get("headers"),
            )
        )

    monkeypatch.setattr(_requests, "get", _get)
    monkeypatch.setattr(_requests, "post", _post)


def _activity(*, app_id, service_url):
    return {
        "type": "message",
        "id": "act-1",
        "serviceUrl": service_url,
        "channelId": "msteams",
        "from": {"id": "user-1"},
        "recipient": {"id": app_id},
        "conversation": {"id": "conv-1"},
        "text": "hi",
    }


def test_missing_bearer_returns_specific_reason(client, tenant_headers, monkeypatch):
    _patch_requests(monkeypatch, client)
    inst = _register_instance(
        client,
        tenant_headers,
        app_id="00000000-0000-0000-0000-000000000001",
        trusted_url="http://localhost:8080/v1/.well-known/openidconfiguration",
    )
    resp = client.post(
        "/api/messages",
        json=_activity(app_id=inst["app_id"], service_url="http://localhost:8080"),
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"]["message"] == "missing-bearer"


def test_unknown_audience_returns_bad_aud(client, tenant_headers, monkeypatch):
    _patch_requests(monkeypatch, client)
    # Sign a token whose `aud` does not match any registered instance.
    kid, private_pem, _ = generate_keypair_pem()
    now = int(time.time())
    token = _jwt.encode(
        {
            "iss": ISSUER,
            "aud": "audience-no-instance-will-claim",
            "serviceUrl": "http://localhost:8080",
            "nbf": now - 5,
            "exp": now + 600,
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )
    resp = client.post(
        "/api/messages",
        json=_activity(app_id="audience-no-instance-will-claim", service_url="http://localhost:8080"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["message"] == "bad-aud"


def test_unknown_kid_returns_unknown_kid(client, tenant_headers, monkeypatch):
    _patch_requests(monkeypatch, client)
    inst = _register_instance(
        client,
        tenant_headers,
        app_id="00000000-0000-0000-0000-000000000002",
        trusted_url="http://localhost:8080/v1/.well-known/openidconfiguration",
    )
    # Sign with a key not in the channel's JWKS.
    foreign_kid, foreign_private, _ = generate_keypair_pem()
    now = int(time.time())
    token = _jwt.encode(
        {
            "iss": ISSUER,
            "aud": inst["app_id"],
            "serviceUrl": "http://localhost:8080",
            "nbf": now - 5,
            "exp": now + 600,
        },
        foreign_private,
        algorithm="RS256",
        headers={"kid": foreign_kid},
    )
    resp = client.post(
        "/api/messages",
        json=_activity(app_id=inst["app_id"], service_url="http://localhost:8080"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["message"] == "unknown-kid"


def _channel_signing_key(client, storage):
    """Force the channel half to publish its JWKS (which calls
    `ensure_keypair`) and read the resulting key out of storage so the
    test can sign tokens with the channel's actual private key.
    """
    jwks_resp = client.get("/v1/.well-known/keys")
    assert jwks_resp.status_code == 200, jwks_resp.get_data(as_text=True)
    key = storage.get_signing_key()
    assert key is not None, "channel did not publish a signing key"
    return key["kid"], key["private_pem"]


def test_expired_token_returns_expired(
    client, storage, tenant_headers, monkeypatch
):
    """Closes twins-la/microsoft-bot-framework#3 (expired-JWT half).

    A token signed by the channel's actual key but with `exp` in the
    past must be rejected with reason ``expired``.
    """
    _patch_requests(monkeypatch, client)
    inst = _register_instance(
        client,
        tenant_headers,
        app_id="00000000-0000-0000-0000-000000000003",
        trusted_url="http://localhost:8080/v1/.well-known/openidconfiguration",
    )
    kid, private_pem = _channel_signing_key(client, storage)
    now = int(time.time())
    # Expire well past the 5-minute CLOCK_SKEW_SECONDS leeway — 1 hour ago.
    token = _jwt.encode(
        {
            "iss": ISSUER,
            "aud": inst["app_id"],
            "serviceUrl": "http://localhost:8080",
            "nbf": now - 7200,
            "exp": now - 3600,
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )
    resp = client.post(
        "/api/messages",
        json=_activity(app_id=inst["app_id"], service_url="http://localhost:8080"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["message"] == "expired"


def test_service_url_mismatch_returns_specific_reason(
    client, storage, tenant_headers, monkeypatch
):
    """Closes twins-la/microsoft-bot-framework#3 (serviceUrl-mismatch half).

    A token whose ``serviceUrl`` claim does not match the activity's
    ``serviceUrl`` must be rejected with reason ``service-url-mismatch``.
    """
    _patch_requests(monkeypatch, client)
    inst = _register_instance(
        client,
        tenant_headers,
        app_id="00000000-0000-0000-0000-000000000004",
        trusted_url="http://localhost:8080/v1/.well-known/openidconfiguration",
    )
    kid, private_pem = _channel_signing_key(client, storage)
    now = int(time.time())
    token = _jwt.encode(
        {
            "iss": ISSUER,
            "aud": inst["app_id"],
            "serviceUrl": "http://claimed-service.example",
            "nbf": now - 5,
            "exp": now + 600,
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )
    # Activity carries a different serviceUrl than the token claim.
    resp = client.post(
        "/api/messages",
        json=_activity(
            app_id=inst["app_id"],
            service_url="http://different-service.example",
        ),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["message"] == "service-url-mismatch"
