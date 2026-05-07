"""Channel half: OpenID Connect Discovery + JWKS publication."""

from twins_microsoft_bot_framework.tokens import ISSUER


def test_openid_configuration(client):
    resp = client.get("/v1/.well-known/openidconfiguration")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["issuer"] == ISSUER
    assert body["jwks_uri"].endswith("/v1/.well-known/keys")
    assert body["token_endpoint"].endswith("/v1/.well-known/oauth2/v2.0/token")
    assert "RS256" in body["id_token_signing_alg_values_supported"]


def test_jwks_shape(client):
    resp = client.get("/v1/.well-known/keys")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "keys" in body and len(body["keys"]) >= 1
    key = body["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"]
    assert key["n"]
    assert key["e"]
    assert "msteams" in key["endorsements"]


def test_kid_is_stable_across_requests(client):
    a = client.get("/v1/.well-known/keys").get_json()["keys"][0]["kid"]
    b = client.get("/v1/.well-known/keys").get_json()["keys"][0]["kid"]
    assert a == b
