"""Activity delivery — channel POSTs to a bot's messaging endpoint.

The channel-to-bot half of the protocol. The channel signs a short-lived
JWT carrying ``iss=https://api.botframework.com``, ``aud=<bot.appId>`` and
``serviceUrl=<channel.base_url>``, then POSTs the Activity to the bot's
``messaging_endpoint`` with ``Authorization: Bearer <jwt>``.

A returns-tuple shape matches ``twins_telegram.webhooks.deliver_update``
so callers can use the same ``webhook_delivered``/``reason``/``status_code``
report shape across messaging twins (TWIN_PLANE.md "Twin-Specific Endpoints").
"""

from typing import Optional, Tuple

import requests

from .tokens import sign_channel_to_bot_jwt

WEBHOOK_TIMEOUT_SECONDS = 15


def deliver_activity(
    *,
    url: str,
    activity: dict,
    private_pem: str,
    kid: str,
    audience: str,
    service_url: str,
) -> Tuple[bool, Optional[str], Optional[int]]:
    """POST an Activity to the bot's messaging endpoint with a signed
    bearer token.

    Returns ``(ok, reason, status_code)``:
      * ``ok=True`` when the bot returns a 2xx.
      * ``reason`` is ``None`` on success and a specific failure string
        otherwise — exactly the values the messaging-twin contract
        requires for the operator-visible delivery report.
    """
    token = sign_channel_to_bot_jwt(
        private_pem=private_pem,
        kid=kid,
        audience=audience,
        service_url=service_url,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = requests.post(
            url, json=activity, headers=headers, timeout=WEBHOOK_TIMEOUT_SECONDS
        )
    except requests.exceptions.Timeout:
        return (False, f"messaging endpoint timed out after {WEBHOOK_TIMEOUT_SECONDS}s", None)
    except requests.exceptions.ConnectionError as exc:
        return (False, f"messaging endpoint unreachable: {exc}", None)
    except requests.exceptions.RequestException as exc:
        return (False, f"messaging endpoint raised: {exc.__class__.__name__}", None)
    if 200 <= resp.status_code < 300:
        return (True, None, resp.status_code)
    return (False, f"messaging endpoint returned HTTP {resp.status_code}", resp.status_code)
