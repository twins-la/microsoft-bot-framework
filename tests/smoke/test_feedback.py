"""Feedback parity with telegram twin."""


def test_submit_and_list_feedback(client, tenant_headers):
    resp = client.post(
        "/_twin/feedback",
        json={"body": "this is feedback", "category": "bug"},
        headers=tenant_headers,
    )
    assert resp.status_code == 201
    record = resp.get_json()
    assert record["body"] == "this is feedback"
    assert record["status"] == "pending"

    listed = client.get("/_twin/feedback", headers=tenant_headers).get_json()["feedback"]
    assert len(listed) == 1
    assert listed[0]["id"] == record["id"]


def test_empty_body_rejected(client, tenant_headers):
    resp = client.post(
        "/_twin/feedback", json={"body": "   "}, headers=tenant_headers
    )
    assert resp.status_code == 400
