"""Channel-to-bot direction.

Drive a synthetic user→channel→bot delivery and verify the bot half (in
the same process) accepts the JWT, validates it against the channel's
JWKS, and writes the activity to the inbox.

This is the primary end-to-end smoke test: it exercises the JWKS
publication, JWT signing, requests fetch of the OpenID metadata, JWT
validation, and inbox storage in one round-trip.
"""


def _register(client, tenant_headers, *, base_url):
    """Register a co-located bot + bot_instance pointing at the same process."""
    bot = client.post(
        "/_twin/accounts",
        json={
            "kind": "bot",
            "messaging_endpoint": f"{base_url}/api/messages",
            "friendly_name": "Echo Bot",
        },
        headers=tenant_headers,
    ).get_json()
    instance = client.post(
        "/_twin/accounts",
        json={
            "kind": "bot_instance",
            "app_id": bot["app_id"],
            "trusted_openid_url": f"{base_url}/v1/.well-known/openidconfiguration",
        },
        headers=tenant_headers,
    ).get_json()
    return bot, instance


def test_simulate_inbound_round_trip(twin_app, client, tenant_headers, monkeypatch):
    base_url = "http://localhost:8080"
    bot, instance = _register(client, tenant_headers, base_url=base_url)

    # The simulate path POSTs to the bot's messaging_endpoint via
    # `requests.post`. Because both halves live in the same Flask test
    # client, we patch `requests.post` to route to the test client; the
    # bot half then validates the JWT against /v1/.well-known/* — for
    # which we patch `requests.get` to do the same.
    import requests as _requests
    from urllib.parse import urlparse

    def _route(url, **kwargs):
        path = urlparse(url).path
        return _client_request("POST" if "json" in kwargs or "data" in kwargs else "GET", path, **kwargs)

    def _client_request(method, path, **kwargs):
        json = kwargs.get("json")
        data = kwargs.get("data")
        headers = kwargs.get("headers", {})
        if method == "POST":
            r = client.post(path, json=json, data=data, headers=headers)
        else:
            r = client.get(path, headers=headers)
        return _ResponseAdapter(r)

    class _ResponseAdapter:
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

        @property
        def text(self):
            return self._r.get_data(as_text=True)

        @property
        def content(self):
            return self._r.get_data()

    def _post(url, **kwargs):
        path = urlparse(url).path
        return _client_request("POST", path, **kwargs)

    def _get(url, **kwargs):
        path = urlparse(url).path
        return _client_request("GET", path, **kwargs)

    monkeypatch.setattr(_requests, "post", _post)
    monkeypatch.setattr(_requests, "get", _get)

    resp = client.post(
        "/_twin/simulate/inbound",
        json={"bot_app_id": bot["app_id"], "text": "hello", "from_id": "user-42"},
        headers=tenant_headers,
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["webhook"]["webhook_delivered"] is True, body["webhook"]
    assert body["webhook"]["status_code"] == 200

    # Inbox now carries the activity.
    inbox = client.get(
        f"/_twin/bots/{instance['bot_id']}/inbox", headers=tenant_headers
    ).get_json()["inbox"]
    assert len(inbox) == 1
    assert inbox[0]["activity"]["text"] == "hello"
    assert inbox[0]["activity"]["channelId"] == "msteams"
    assert inbox[0]["activity"]["serviceUrl"] == "http://localhost:8080"
    assert inbox[0]["claims"]["iss"] == "https://api.botframework.com"
    assert inbox[0]["claims"]["aud"] == bot["app_id"]
