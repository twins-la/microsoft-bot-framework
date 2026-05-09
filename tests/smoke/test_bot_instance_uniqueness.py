"""Closes twins-la/microsoft-bot-framework#1 — `(tenant_id, app_id)` is
unique on `bot_instances`. Creating a second bot_instance with an
already-claimed app_id within the same tenant returns 409 from
``POST /_twin/accounts``.
"""


def test_create_bot_instance_conflict_returns_409(client, tenant_headers):
    payload = {
        "kind": "bot_instance",
        "app_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
        "trusted_openid_url": "http://localhost:8080/v1/.well-known/openidconfiguration",
        "friendly_name": "First instance",
    }

    first = client.post("/_twin/accounts", headers=tenant_headers, json=payload)
    assert first.status_code == 201, first.get_data(as_text=True)
    body = first.get_json()
    assert body["app_id"] == payload["app_id"]

    # Second bot_instance with the same app_id within the same tenant.
    second = client.post(
        "/_twin/accounts",
        headers=tenant_headers,
        json={
            **payload,
            "friendly_name": "Second instance (should conflict)",
        },
    )
    assert second.status_code == 409, second.get_data(as_text=True)
    err = second.get_json()
    # Twin Plane error shape is flat: {"error": "<message>"}.
    assert "already exists" in err["error"]


def test_create_bot_instance_same_app_id_different_tenant_succeeds(
    client, tenant_store, tenant_headers
):
    """Uniqueness is scoped to ``(tenant_id, app_id)``: a different
    tenant may claim the same `app_id` independently."""
    import base64

    from twins_local.tenants import (
        generate_tenant_id,
        generate_tenant_secret,
        hash_secret,
    )

    payload = {
        "kind": "bot_instance",
        "app_id": "00000000-0000-0000-0000-bbbbbbbbbbbb",
        "trusted_openid_url": "http://localhost:8080/v1/.well-known/openidconfiguration",
    }

    first = client.post("/_twin/accounts", headers=tenant_headers, json=payload)
    assert first.status_code == 201

    # Bootstrap a second tenant.
    second_tid = generate_tenant_id()
    second_secret = generate_tenant_secret()
    tenant_store.create_tenant(
        tenant_id=second_tid,
        secret_hash=hash_secret(second_secret),
        friendly_name="Second Tenant",
    )
    creds = base64.b64encode(
        f"{second_tid}:{second_secret}".encode()
    ).decode()
    second_tenant_headers = {"Authorization": f"Basic {creds}"}

    second = client.post(
        "/_twin/accounts",
        headers=second_tenant_headers,
        json=payload,
    )
    assert second.status_code == 201, second.get_data(as_text=True)
