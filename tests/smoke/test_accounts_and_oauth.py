"""Account creation + the channel's OAuth client-credentials endpoint."""


def test_create_bot_account(client, tenant_headers):
    resp = client.post(
        "/_twin/accounts",
        json={
            "kind": "bot",
            "messaging_endpoint": "http://localhost:9999/api/messages",
            "friendly_name": "Bot A",
        },
        headers=tenant_headers,
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["kind"] == "bot"
    assert body["app_id"]
    assert body["app_password"]
    assert body["messaging_endpoint"] == "http://localhost:9999/api/messages"


def test_create_bot_instance_account(client, tenant_headers):
    resp = client.post(
        "/_twin/accounts",
        json={
            "kind": "bot_instance",
            "trusted_openid_url": "http://localhost:8080/v1/.well-known/openidconfiguration",
            "friendly_name": "Bot B",
        },
        headers=tenant_headers,
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["kind"] == "bot_instance"
    assert body["bot_id"].startswith("bi_")
    assert body["app_id"]


def test_oauth_token_happy_path(client, tenant_headers):
    create = client.post(
        "/_twin/accounts",
        json={"kind": "bot", "messaging_endpoint": "http://localhost:9000/api/messages"},
        headers=tenant_headers,
    ).get_json()
    resp = client.post(
        "/v1/.well-known/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": create["app_id"],
            "client_secret": create["app_password"],
            "scope": "https://api.botframework.com/.default",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"].count(".") == 2  # JWT


def test_oauth_token_rejects_wrong_secret(client, tenant_headers):
    create = client.post(
        "/_twin/accounts",
        json={"kind": "bot", "messaging_endpoint": "http://localhost:9000/api/messages"},
        headers=tenant_headers,
    ).get_json()
    resp = client.post(
        "/v1/.well-known/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": create["app_id"],
            "client_secret": "not-the-real-secret",
        },
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "invalid_client"


def test_oauth_token_rejects_wrong_grant(client, tenant_headers):
    resp = client.post(
        "/v1/.well-known/oauth2/v2.0/token",
        data={"grant_type": "password", "client_id": "x", "client_secret": "y"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_grant"
