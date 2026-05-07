"""Tenant bootstrap and Basic-auth gating."""


def test_tenant_bootstrap_returns_secret_once(client):
    resp = client.post("/_twin/tenants", json={"friendly_name": "Sample"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["tenant_id"]
    assert body["tenant_secret"]
    assert body["friendly_name"] == "Sample"
    assert body["created_at"]


def test_tenant_required_for_logs(client):
    resp = client.get("/_twin/logs")
    assert resp.status_code == 401


def test_tenant_required_for_accounts_create(client):
    resp = client.post(
        "/_twin/accounts",
        json={"kind": "bot", "messaging_endpoint": "http://localhost:9000/api/messages"},
    )
    assert resp.status_code == 401


def test_tenant_credentials_are_validated(client, tenant):
    import base64

    bad = base64.b64encode(f"{tenant['tenant_id']}:wrong".encode()).decode()
    resp = client.get("/_twin/logs", headers={"Authorization": f"Basic {bad}"})
    assert resp.status_code == 401
