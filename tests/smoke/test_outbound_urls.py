"""Outbound URL policy for the OpenID / JWKS / token-endpoint fetches.

In cloud deployments the twin only fetches https URLs whose host resolves
to public addresses, and does not follow redirects. Local deployments keep
the documented localhost workflow.
"""

import socket

import jwt as _jwt
import pytest
import requests as _requests

from twins_microsoft_bot_framework import outbound, tokens
from twins_microsoft_bot_framework.app import create_app
from twins_microsoft_bot_framework.crypto import generate_keypair_pem
from twins_microsoft_bot_framework.tokens import ValidationFailure

PUBLIC_HOSTS = {"channel.example": "93.184.216.34"}
PRIVATE_ADDRS = {
    "loopback.example": "127.0.0.1",
    "rfc1918.example": "10.0.0.5",
    "metadata.example": "169.254.169.254",
    "cgnat.example": "100.64.0.1",
    "v6loop.example": "::1",
    "v6mapped.example": "::ffff:127.0.0.1",
}


@pytest.fixture
def fake_dns(monkeypatch):
    table = {**PUBLIC_HOSTS, **PRIVATE_ADDRS}

    def _getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror("unknown host")
        addr = table[host]
        family = socket.AF_INET6 if ":" in addr else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (addr, port or 443))]

    monkeypatch.setattr(outbound.socket, "getaddrinfo", _getaddrinfo)


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.exceptions.HTTPError(str(self.status_code))


def _token(kid="k1", aud="app-1"):
    _, private_pem, _ = generate_keypair_pem()
    return _jwt.encode(
        {"aud": aud, "iss": tokens.ISSUER}, private_pem, algorithm="RS256",
        headers={"kid": kid},
    )


# ---- check_outbound_url ----


def test_public_https_url_is_allowed(fake_dns):
    outbound.check_outbound_url("https://channel.example/.well-known/openid")


@pytest.mark.parametrize("host", sorted(PRIVATE_ADDRS))
def test_non_public_addresses_are_rejected(fake_dns, host):
    with pytest.raises(outbound.OutboundURLRejected):
        outbound.check_outbound_url(f"https://{host}/x")


@pytest.mark.parametrize(
    "url",
    [
        "http://channel.example/x",
        "ftp://channel.example/x",
        "https:///x",
        "https://unresolvable.example/x",
        "https://127.0.0.1/x",
        "https://[::1]/x",
    ],
)
def test_bad_scheme_host_or_literal_is_rejected(fake_dns, url):
    with pytest.raises(outbound.OutboundURLRejected):
        outbound.check_outbound_url(url)


# ---- validate_channel_to_bot_jwt ----


def test_restricted_rejects_internal_jwks_uri_before_fetching(fake_dns, monkeypatch):
    calls = []

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        return _Resp({"jwks_uri": "http://169.254.169.254/metadata/keys"})

    monkeypatch.setattr(_requests, "get", _get)
    with pytest.raises(ValidationFailure) as exc:
        tokens.validate_channel_to_bot_jwt(
            token=_token(),
            audience="app-1",
            expected_service_url="https://channel.example",
            trusted_openid_url="https://channel.example/.well-known/openid",
            restrict_outbound=True,
        )
    assert exc.value.reason == "untrusted-url"
    assert [u for u, _ in calls] == ["https://channel.example/.well-known/openid"]
    assert calls[0][1].get("allow_redirects") is False


def test_restricted_rejects_internal_openid_url(fake_dns, monkeypatch):
    calls = []
    monkeypatch.setattr(_requests, "get", lambda url, **kw: calls.append(url))
    with pytest.raises(ValidationFailure) as exc:
        tokens.validate_channel_to_bot_jwt(
            token=_token(),
            audience="app-1",
            expected_service_url="https://channel.example",
            trusted_openid_url="https://rfc1918.example/.well-known/openid",
            restrict_outbound=True,
        )
    assert exc.value.reason == "untrusted-url"
    assert calls == []


def test_unrestricted_keeps_localhost_workflow(monkeypatch):
    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        if url.endswith("openid"):
            return _Resp({"jwks_uri": "http://localhost:8080/v1/keys"})
        return _Resp({"keys": []})

    monkeypatch.setattr(_requests, "get", _get)
    with pytest.raises(ValidationFailure) as exc:
        tokens.validate_channel_to_bot_jwt(
            token=_token(),
            audience="app-1",
            expected_service_url="http://localhost:8080",
            trusted_openid_url="http://localhost:8080/openid",
        )
    assert exc.value.reason == "unknown-kid"
    assert calls == ["http://localhost:8080/openid", "http://localhost:8080/v1/keys"]


def test_jwks_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(
        _requests, "get", lambda url, **kw: _Resp({"keys": []})
    )
    for i in range(tokens.JWKS_CACHE_MAX_ENTRIES + 50):
        tokens._fetch_jwks(f"http://localhost:8080/keys/{i}", restrict_outbound=False)
    assert len(tokens._jwks_cache) <= tokens.JWKS_CACHE_MAX_ENTRIES


# ---- acquire_bot_to_channel_token ----


def test_restricted_rejects_internal_token_endpoint(fake_dns, monkeypatch):
    posts = []
    monkeypatch.setattr(
        _requests, "get",
        lambda url, **kw: _Resp({"token_endpoint": "https://metadata.example/token"}),
    )
    monkeypatch.setattr(_requests, "post", lambda url, **kw: posts.append(url))
    with pytest.raises(ValidationFailure) as exc:
        tokens.acquire_bot_to_channel_token(
            trusted_openid_url="https://channel.example/.well-known/openid",
            app_id="app-1",
            app_password="pw",
            restrict_outbound=True,
        )
    assert exc.value.reason == "untrusted-url"
    assert posts == []


# ---- route wiring: cloud app applies the policy ----


def test_cloud_bot_endpoint_rejects_internal_jwks_uri(
    storage, tenant_store, tenant_headers, fake_dns, monkeypatch
):
    app = create_app(
        storage=storage,
        tenants=tenant_store,
        config={"base_url": "https://bf.example", "is_cloud": True},
    )
    app.config["TESTING"] = True
    client = app.test_client()
    inst = client.post(
        "/_twin/accounts",
        json={
            "kind": "bot_instance",
            "app_id": "00000000-0000-0000-0000-0000000000aa",
            "trusted_openid_url": "https://channel.example/.well-known/openid",
        },
        headers=tenant_headers,
    ).get_json()

    fetched = []

    def _get(url, **kwargs):
        fetched.append(url)
        return _Resp({"jwks_uri": "http://10.0.0.5/keys"})

    monkeypatch.setattr(_requests, "get", _get)
    resp = client.post(
        "/api/messages",
        json={
            "type": "message",
            "id": "act-1",
            "serviceUrl": "https://channel.example",
            "channelId": "msteams",
            "from": {"id": "user-1"},
            "recipient": {"id": inst["app_id"]},
            "conversation": {"id": "conv-1"},
            "text": "hi",
        },
        headers={"Authorization": f"Bearer {_token(aud=inst['app_id'])}"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["message"] == "untrusted-url"
    assert "http://10.0.0.5/keys" not in fetched
