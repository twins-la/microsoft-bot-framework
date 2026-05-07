"""Activity / ConversationAccount / ChannelAccount shapes.

The Bot Framework Activity is documented at
https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-api-reference#activity-object
(retrieved 2026-05-07).

The twin emits the subset of fields required for a text ``message`` activity
on the ``msteams`` channel: ``type``, ``id``, ``timestamp``, ``serviceUrl``,
``channelId``, ``from``, ``conversation``, ``recipient``, ``text``,
``replyToId``. Out-of-scope fields (attachments, suggestedActions,
channelData) are accepted on inbound but not interpreted.
"""

from datetime import datetime, timezone


def now_iso_z() -> str:
    """ISO-8601 UTC timestamp with millisecond precision and ``Z`` suffix."""
    n = datetime.now(tz=timezone.utc)
    return f"{n.strftime('%Y-%m-%dT%H:%M:%S')}.{n.microsecond // 1000:03d}Z"


def channel_account(*, id: str, name: str = "", role: str = "") -> dict:
    """A ``ChannelAccount`` — the user/bot identity within a channel."""
    out = {"id": id, "name": name}
    if role:
        out["role"] = role
    return out


def conversation_account(*, id: str, conversation_type: str = "personal") -> dict:
    return {"id": id, "conversationType": conversation_type}


def build_activity(
    *,
    activity_id: str,
    type_: str,
    service_url: str,
    channel_id: str,
    from_account: dict,
    recipient_account: dict,
    conversation: dict,
    text: str = "",
    reply_to_id: str = "",
    extra: dict | None = None,
) -> dict:
    """Build an Activity object suitable for delivery or storage."""
    activity = {
        "type": type_,
        "id": activity_id,
        "timestamp": now_iso_z(),
        "serviceUrl": service_url,
        "channelId": channel_id,
        "from": from_account,
        "recipient": recipient_account,
        "conversation": conversation,
        "text": text,
    }
    if reply_to_id:
        activity["replyToId"] = reply_to_id
    if extra:
        for k, v in extra.items():
            activity.setdefault(k, v)
    return activity
