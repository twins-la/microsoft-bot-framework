"""Channel-half conversation endpoints.

The bot-to-channel direction. A real bot calls
``POST {serviceUrl}/v3/conversations/{conversationId}/activities`` to send
an Activity to the channel; the twin matches that path verbatim. The
bearer token is validated against the channel's own keypair (the bot
acquired it from the twin's ``/oauth2/v2.0/token`` endpoint).

Reference (retrieved 2026-05-07):
  - https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-create-messages
"""

from flask import Blueprint, g, jsonify, request

from twins_local.logs import ANONYMOUS_TENANT_ID

from ..crypto import ensure_keypair
from ..errors import bf_bad_request, bf_unauthorized
from ..logs import emit
from ..models import build_activity, channel_account, conversation_account
from ..sids import generate_activity_id, generate_conversation_id
from ..tokens import ValidationFailure, validate_channel_self_issued_token

channel_bp = Blueprint("channel", __name__, url_prefix="/v3/conversations")


def _bearer():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth[7:]


def _authenticate_bot() -> tuple[dict | None, str | None]:
    """Validate the bearer token; return (bot, error_reason).

    On success ``bot`` is the storage row; on failure ``error_reason`` is
    one of the enumerated reason strings the validate path uses.
    """
    token = _bearer()
    if not token:
        return None, "missing-bearer"
    keypair = ensure_keypair(g.storage)
    try:
        claims = validate_channel_self_issued_token(
            token=token, public_pem=keypair["public_pem"], kid=keypair["kid"]
        )
    except ValidationFailure as exc:
        return None, exc.reason
    bot = g.storage.get_bot(claims.get("appid", ""))
    if not bot:
        return None, "unknown-appid"
    return bot, None


@channel_bp.route("/<conversation_id>/activities", methods=["POST"])
def post_activity(conversation_id: str):
    return _post_activity(conversation_id, reply_to=None)


@channel_bp.route("/<conversation_id>/activities/<activity_id>", methods=["POST"])
def post_reply(conversation_id: str, activity_id: str):
    return _post_activity(conversation_id, reply_to=activity_id)


def _post_activity(conversation_id: str, *, reply_to: str | None):
    bot, error_reason = _authenticate_bot()
    if error_reason:
        emit(
            g.storage,
            tenant_id=bot["tenant_id"] if bot else ANONYMOUS_TENANT_ID,
            plane="data",
            operation="data.activity.validate",
            outcome="failure",
            reason=error_reason,
            details={"conversation_id": conversation_id, "direction": "bot_to_channel"},
        )
        return bf_unauthorized(error_reason)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return bf_bad_request("Activity body MUST be a JSON object")

    text = payload.get("text", "")
    if payload.get("type", "message") == "message" and not text:
        return bf_bad_request("text is required for message activities")

    conv = g.storage.get_conversation(conversation_id) or g.storage.upsert_conversation(
        {
            "id": conversation_id,
            "bot_app_id": bot["app_id"],
            "tenant_id": bot["tenant_id"],
            "channel_id": payload.get("channelId", "msteams"),
            "service_url": g.base_url.rstrip("/"),
        }
    )

    activity_id = generate_activity_id()
    activity = build_activity(
        activity_id=activity_id,
        type_=payload.get("type", "message"),
        service_url=conv["service_url"],
        channel_id=conv["channel_id"],
        from_account=channel_account(
            id=bot["app_id"], name=bot.get("friendly_name", ""), role="bot"
        ),
        recipient_account=payload.get("recipient")
        or channel_account(id="user", role="user"),
        conversation=conversation_account(id=conversation_id),
        text=text,
        reply_to_id=reply_to or "",
    )
    g.storage.create_activity(
        {
            "id": activity_id,
            "conversation_id": conversation_id,
            "tenant_id": bot["tenant_id"],
            "direction": "bot_to_channel",
            "from_id": bot["app_id"],
            "recipient_id": activity["recipient"]["id"],
            "channel_id": conv["channel_id"],
            "service_url": conv["service_url"],
            "text": text,
            "reply_to_id": reply_to or "",
            "raw_json": activity,
        }
    )

    emit(
        g.storage,
        tenant_id=bot["tenant_id"],
        plane="data",
        operation="data.conversation.activity.send",
        resource={"type": "activity", "id": activity_id},
        details={
            "conversation_id": conversation_id,
            "direction": "bot_to_channel",
            "channel_id": conv["channel_id"],
        },
    )

    return jsonify({"id": activity_id})
