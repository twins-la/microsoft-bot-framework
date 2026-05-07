"""Bot-half ``/api/messages`` endpoint.

Real Bot Framework bots expose a single POST handler at ``/api/messages``
(or any path the bot operator chose; ``/api/messages`` is the
SDK-default). The twin matches that path. Inbound JWT validation is
the bot half's load-bearing job: rejecting tokens with the wrong issuer,
audience, key, or serviceUrl is exactly what surfaces real auth bugs in
CI.

This endpoint persists the activity into the bot instance's inbox; a
real bot would synchronously execute its dialog logic and reply via the
``serviceUrl``. The twin offers ``POST /_twin/bots/<bot_id>/reply`` for
operator-driven replies (see ``twin_plane/routes.py``).
"""

from flask import Blueprint, g, jsonify, request

from twins_local.logs import ANONYMOUS_TENANT_ID

from ..errors import bf_bad_request, bf_forbidden, bf_unauthorized
from ..logs import emit
from ..tokens import ValidationFailure, validate_channel_to_bot_jwt

bot_bp = Blueprint("bot", __name__, url_prefix="/api")


def _bearer() -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth[7:]


@bot_bp.route("/messages", methods=["POST"])
def messages():
    """Validate the inbound channel JWT and append the Activity to the
    addressed bot instance's inbox.

    The ``aud`` claim selects the bot instance — every instance carries a
    distinct ``app_id``. A token with an unknown audience is rejected with
    a specific reason, not a generic 401, so CI can assert on the failure
    shape.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return bf_bad_request("Activity body MUST be a JSON object")

    token = _bearer()
    if not token:
        emit(
            g.storage,
            tenant_id=ANONYMOUS_TENANT_ID,
            plane="data",
            operation="data.activity.validate",
            outcome="failure",
            reason="missing-bearer",
            details={"direction": "channel_to_bot"},
        )
        return bf_unauthorized("missing-bearer")

    activity_service_url = payload.get("serviceUrl", "").rstrip("/")
    if not activity_service_url:
        return bf_bad_request("Activity is missing serviceUrl")

    # Audience selects which bot instance is being addressed.
    import jwt as _jwt  # local import — only here for the unverified peek

    try:
        unverified = _jwt.decode(token, options={"verify_signature": False})
    except _jwt.InvalidTokenError:
        emit(
            g.storage,
            tenant_id=ANONYMOUS_TENANT_ID,
            plane="data",
            operation="data.activity.validate",
            outcome="failure",
            reason="sig-invalid",
            details={"direction": "channel_to_bot"},
        )
        return bf_unauthorized("sig-invalid")

    audience = unverified.get("aud", "")
    instance = g.storage.get_bot_instance_by_app_id(audience) if audience else None
    if not instance:
        emit(
            g.storage,
            tenant_id=ANONYMOUS_TENANT_ID,
            plane="data",
            operation="data.activity.validate",
            outcome="failure",
            reason="bad-aud",
            details={"direction": "channel_to_bot", "aud": audience},
        )
        return bf_forbidden("bad-aud")

    try:
        claims = validate_channel_to_bot_jwt(
            token=token,
            audience=instance["app_id"],
            expected_service_url=activity_service_url,
            trusted_openid_url=instance["trusted_openid_url"],
        )
    except ValidationFailure as exc:
        emit(
            g.storage,
            tenant_id=instance["tenant_id"],
            plane="data",
            operation="data.activity.validate",
            resource={"type": "bot_instance", "id": instance["bot_id"]},
            outcome="failure",
            reason=exc.reason,
            details={"direction": "channel_to_bot"},
        )
        return bf_forbidden(exc.reason)

    # Persist + inbox.
    g.storage.append_inbox(
        instance["bot_id"],
        {
            "activity": payload,
            "claims": {
                "iss": claims.get("iss"),
                "aud": claims.get("aud"),
                "serviceUrl": claims.get("serviceUrl"),
            },
        },
    )

    emit(
        g.storage,
        tenant_id=instance["tenant_id"],
        plane="data",
        operation="data.activity.receive",
        resource={"type": "bot_instance", "id": instance["bot_id"]},
        details={
            "channel_id": payload.get("channelId", ""),
            "conversation_id": (payload.get("conversation") or {}).get("id", ""),
            "direction": "channel_to_bot",
        },
    )
    return jsonify({"received": True})
