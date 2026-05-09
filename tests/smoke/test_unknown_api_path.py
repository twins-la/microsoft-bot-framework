"""Sweep test: unknown ``/api/<rest>`` and ``/v3/<rest>`` paths return
Bot-Framework-shaped JSON 404. Closes twins-la/twins-la#2 (msbf half).
"""

import pytest


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "api/foo"),
        ("POST", "api/messages-misspell"),
        ("DELETE", "api/random/nested"),
        ("PUT", "api/no-such-endpoint"),
        ("GET", "v3/conversations/no-such-conversation/something-else"),
        ("POST", "v3/foo/bar"),
        ("PATCH", "v3/Activities"),
    ],
)
def test_unknown_api_or_v3_path_returns_json_404(client, method, path):
    full = f"/{path}"
    resp = client.open(
        full,
        method=method,
        json={"foo": "bar"} if method in ("POST", "PUT", "PATCH") else None,
    )
    assert resp.status_code == 404, f"{method} {full} got {resp.status_code}"
    assert resp.headers["Content-Type"].startswith("application/json"), (
        f"{method} {full} returned {resp.headers.get('Content-Type')!r} "
        f"body={resp.get_data(as_text=True)[:200]!r}"
    )
    body = resp.get_json()
    assert body is not None and "error" in body
    # Bot Framework REST error shape: {error: {code, message}}.
    assert isinstance(body["error"], dict), body
    assert body["error"]["code"] == "ResourceNotFound"
    assert "does not exist" in body["error"]["message"]


def test_unknown_api_path_no_html_leak(client):
    resp = client.get("/api/literally-anything")
    body = resp.get_data(as_text=True)
    assert "<!doctype" not in body.lower()


def test_unknown_v3_path_no_html_leak(client):
    resp = client.get("/v3/literally-anything")
    body = resp.get_data(as_text=True)
    assert "<!doctype" not in body.lower()
