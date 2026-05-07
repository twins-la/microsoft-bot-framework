"""Twin Plane management API for the Microsoft Bot Framework twin.

Served at ``/_twin/`` per TWIN_PLANE.md. Two account *kinds* live under
the same ``/_twin/accounts`` resource because both halves of the twin
share a tenant:

* ``kind = "bot"`` — channel-side: a bot the channel will deliver to.
  Returns ``app_id``, ``app_password``, ``messaging_endpoint``.
* ``kind = "bot_instance"`` — bot-side: a bot the twin emulates. Returns
  ``bot_id``, ``app_id``, ``trusted_openid_url``.

The simulate-inbound endpoint is the operator's "user sent a message"
button: it signs a channel→bot JWT and POSTs to the bot's messaging
endpoint, returning the same delivery report shape Telegram + Twilio use.
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from twins_local.tenants import (
    OPERATOR_ADMIN_TENANT_ID,
    generate_tenant_id,
    generate_tenant_secret,
    hash_secret,
    reject_default_in_cloud,
)

from .. import __version__
from ..crypto import ensure_keypair
from ..errors import plane_error
from ..logs import emit
from ..models import (
    build_activity,
    channel_account,
    conversation_account,
    now_iso_z,
)
from ..sids import (
    generate_activity_id,
    generate_app_id,
    generate_app_password,
    generate_bot_instance_id,
    generate_conversation_id,
    generate_feedback_id,
)
from ..tokens import ValidationFailure, acquire_bot_to_channel_token
from ..webhooks import deliver_activity
from .auth import require_admin, require_tenant, require_tenant_or_admin

logger = logging.getLogger(__name__)

twin_plane_bp = Blueprint("twin_plane", __name__, url_prefix="/_twin")


def _scope_tenant_id() -> str:
    return OPERATOR_ADMIN_TENANT_ID if g.get("is_admin") else g.tenant_id


# ---- Public info endpoints ----


@twin_plane_bp.route("/health", methods=["GET"])
def health():
    return jsonify(
        {"status": "ok", "twin": "microsoft-bot-framework", "version": __version__}
    )


@twin_plane_bp.route("/scenarios", methods=["GET"])
def scenarios():
    return jsonify(
        {
            "scenarios": [
                {
                    "name": "channel-msteams",
                    "status": "supported",
                    "description": (
                        "Emulates a Microsoft Bot Framework channel with "
                        "channelId='msteams'. Signs channel-to-bot JWTs, "
                        "publishes a JWKS document, issues OAuth client-"
                        "credentials tokens, and accepts bot-to-channel "
                        "activity POSTs."
                    ),
                    "capabilities": [
                        "openid_metadata_publication",
                        "jwks_publication",
                        "oauth_client_credentials_token_issue",
                        "channel_to_bot_jwt_signing",
                        "bot_to_channel_activity_post",
                        "operator_driven_inbound_simulation",
                    ],
                },
                {
                    "name": "bot-receiver",
                    "status": "supported",
                    "description": (
                        "Emulates a Bot Framework bot's /api/messages "
                        "endpoint. Validates inbound channel JWTs against a "
                        "configured OpenID metadata URL and exposes the "
                        "received activities via the Twin Plane inbox. "
                        "Operator-driven replies use the channel's "
                        "serviceUrl + token endpoint."
                    ),
                    "capabilities": [
                        "channel_jwt_validation",
                        "specific_validation_failure_reasons",
                        "configurable_trusted_openid_url",
                        "operator_driven_reply",
                        "inbox_inspection",
                    ],
                },
            ]
        }
    )


@twin_plane_bp.route("/references", methods=["GET"])
def references():
    return jsonify(
        {
            "references": [
                {
                    "title": "Bot Framework REST: Authenticate requests with the Bot Connector API",
                    "url": "https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication",
                    "retrieved": "2026-05-07",
                },
                {
                    "title": "Bot Framework REST: Create messages",
                    "url": "https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-create-messages",
                    "retrieved": "2026-05-07",
                },
                {
                    "title": "Bot Framework REST: API reference (Activity object)",
                    "url": "https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-api-reference",
                    "retrieved": "2026-05-07",
                },
                {
                    "title": "Microsoft Teams platform: Conversation basics",
                    "url": "https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/conversation-basics",
                    "retrieved": "2026-05-07",
                },
                {
                    "title": "RFC 7517 — JSON Web Key (JWK)",
                    "url": "https://datatracker.ietf.org/doc/html/rfc7517",
                    "retrieved": "2026-05-07",
                },
                {
                    "title": "RFC 7519 — JSON Web Token (JWT)",
                    "url": "https://datatracker.ietf.org/doc/html/rfc7519",
                    "retrieved": "2026-05-07",
                },
            ]
        }
    )


@twin_plane_bp.route("/settings", methods=["GET"])
def get_settings():
    return jsonify(
        {
            "twin": "microsoft-bot-framework",
            "version": __version__,
            "base_url": g.base_url,
        }
    )


@twin_plane_bp.route("/agent-instructions", methods=["GET"])
def agent_instructions_endpoint():
    """Serve the same plain-text agent instructions the explainer page
    embeds. Lives here (under ``/_twin/``) per TWIN_PLANE.md."""
    from flask import Response

    from ..explainer import AGENT_INSTRUCTIONS

    return Response(AGENT_INSTRUCTIONS, mimetype="text/plain")


# ---- Tenants (bootstrap) ----


@twin_plane_bp.route("/tenants", methods=["POST"])
def create_tenant():
    payload = request.get_json(silent=True) or {}
    friendly_name = payload.get("friendly_name", "") if isinstance(payload, dict) else ""

    tenant_id = generate_tenant_id()
    if g.is_cloud:
        reject_default_in_cloud(tenant_id)

    tenant_secret = generate_tenant_secret()
    tenant = g.tenants.create_tenant(
        tenant_id=tenant_id,
        secret_hash=hash_secret(tenant_secret),
        friendly_name=friendly_name,
    )

    emit(
        g.storage,
        tenant_id=tenant_id,
        plane="twin",
        operation="twin.tenant.create",
        resource={"type": "tenant", "id": tenant_id},
    )

    resp = jsonify(
        {
            "tenant_id": tenant_id,
            "tenant_secret": tenant_secret,
            "friendly_name": tenant["friendly_name"],
            "created_at": tenant["created_at"],
        }
    )
    resp.status_code = 201
    return resp


# ---- Logs ----


@twin_plane_bp.route("/logs", methods=["GET"])
@require_tenant_or_admin
def list_logs():
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    tenant_id = None if g.is_admin else g.tenant_id
    entries = g.storage.list_logs(limit=limit, offset=offset, tenant_id=tenant_id)
    return jsonify({"logs": entries, "limit": limit, "offset": offset})


# ---- Accounts (bots + bot_instances) ----


def _bot_public(bot: dict) -> dict:
    return {
        "kind": "bot",
        "app_id": bot["app_id"],
        "messaging_endpoint": bot["messaging_endpoint"],
        "friendly_name": bot.get("friendly_name", ""),
        "tenant_id": bot["tenant_id"],
    }


def _bot_instance_public(inst: dict) -> dict:
    return {
        "kind": "bot_instance",
        "bot_id": inst["bot_id"],
        "app_id": inst["app_id"],
        "trusted_openid_url": inst["trusted_openid_url"],
        "friendly_name": inst.get("friendly_name", ""),
        "tenant_id": inst["tenant_id"],
    }


@twin_plane_bp.route("/accounts", methods=["POST"])
@require_tenant
def create_account():
    payload = request.get_json(silent=True) or {}
    kind = payload.get("kind", "bot")

    if kind == "bot":
        messaging_endpoint = payload.get("messaging_endpoint", "")
        if not messaging_endpoint:
            return plane_error("messaging_endpoint is required for kind='bot'", 400)
        if g.is_cloud and not messaging_endpoint.startswith("https://"):
            return plane_error(
                "messaging_endpoint MUST use https in cloud deployments", 400
            )
        app_id = generate_app_id()
        app_password = generate_app_password()
        bot = g.storage.create_bot(
            tenant_id=g.tenant_id,
            app_id=app_id,
            app_password_hash=hash_secret(app_password),
            messaging_endpoint=messaging_endpoint,
            friendly_name=payload.get("friendly_name", ""),
        )
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="twin",
            operation="twin.account.create",
            resource={"type": "bot", "id": app_id},
            details={"kind": "bot"},
        )
        resp = jsonify(
            {
                "kind": "bot",
                "app_id": app_id,
                "app_password": app_password,
                "messaging_endpoint": bot["messaging_endpoint"],
                "friendly_name": bot["friendly_name"],
            }
        )
        resp.status_code = 201
        return resp

    if kind == "bot_instance":
        trusted_openid_url = payload.get("trusted_openid_url", "")
        if not trusted_openid_url:
            return plane_error(
                "trusted_openid_url is required for kind='bot_instance'", 400
            )
        if g.is_cloud and not trusted_openid_url.startswith("https://"):
            return plane_error(
                "trusted_openid_url MUST use https in cloud deployments", 400
            )
        app_id = payload.get("app_id") or generate_app_id()
        bot_id = generate_bot_instance_id()
        instance = g.storage.create_bot_instance(
            tenant_id=g.tenant_id,
            bot_id=bot_id,
            app_id=app_id,
            trusted_openid_url=trusted_openid_url,
            friendly_name=payload.get("friendly_name", ""),
        )
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="twin",
            operation="twin.account.create",
            resource={"type": "bot_instance", "id": bot_id},
            details={"kind": "bot_instance"},
        )
        resp = jsonify(_bot_instance_public(instance))
        resp.status_code = 201
        return resp

    return plane_error(f"Unknown account kind {kind!r}; use 'bot' or 'bot_instance'", 400)


@twin_plane_bp.route("/accounts", methods=["GET"])
@require_tenant_or_admin
def list_accounts():
    if g.is_admin:
        bots = g.storage.list_bots()
        instances = g.storage.list_bot_instances()
    else:
        bots = g.storage.list_bots(tenant_id=g.tenant_id)
        instances = g.storage.list_bot_instances(tenant_id=g.tenant_id)
    return jsonify(
        {
            "accounts": [_bot_public(b) for b in bots]
            + [_bot_instance_public(i) for i in instances]
        }
    )


# ---- Inbound simulation ----


@twin_plane_bp.route("/simulate/inbound", methods=["POST"])
@require_tenant
def simulate_inbound():
    """Drive a synthetic user→channel→bot delivery.

    Body:
        bot_app_id (str, required): which channel-side bot to deliver to.
        text (str, required): message text.
        from_id (str, optional): sender id (defaults to a synthetic value).
        from_name (str, optional)
        conversation_id (str, optional): reused on subsequent calls to
          continue an existing conversation.
        channel_id (str, optional): defaults to ``"msteams"``.

    Behaviour mirrors the messaging-twin contract: persist the activity,
    sign a channel-to-bot JWT, POST to the bot's messaging_endpoint, and
    return ``{activity, webhook: {webhook_delivered, webhook_url, reason,
    status_code}}``.
    """
    payload = request.get_json(silent=True) or {}
    bot_app_id = payload.get("bot_app_id")
    text = payload.get("text")
    if not bot_app_id:
        return plane_error("'bot_app_id' is required", 400)
    if not text or not isinstance(text, str) or not text.strip():
        return plane_error("'text' is required", 400)

    bot = g.storage.get_bot(bot_app_id)
    if not bot or bot["tenant_id"] != g.tenant_id:
        return plane_error("Bot not found in this tenant", 404)

    channel_id = payload.get("channel_id", "msteams")
    conversation_id = payload.get("conversation_id") or generate_conversation_id()
    from_id = payload.get("from_id", "user-1")
    from_name = payload.get("from_name", "Test User")

    conv = g.storage.upsert_conversation(
        {
            "id": conversation_id,
            "bot_app_id": bot_app_id,
            "tenant_id": bot["tenant_id"],
            "channel_id": channel_id,
            "service_url": g.base_url.rstrip("/"),
        }
    )

    activity_id = generate_activity_id()
    activity = build_activity(
        activity_id=activity_id,
        type_="message",
        service_url=conv["service_url"],
        channel_id=channel_id,
        from_account=channel_account(id=from_id, name=from_name, role="user"),
        recipient_account=channel_account(
            id=bot["app_id"], name=bot.get("friendly_name", ""), role="bot"
        ),
        conversation=conversation_account(id=conversation_id),
        text=text,
    )

    g.storage.create_activity(
        {
            "id": activity_id,
            "conversation_id": conversation_id,
            "tenant_id": bot["tenant_id"],
            "direction": "channel_to_bot",
            "from_id": from_id,
            "recipient_id": bot["app_id"],
            "channel_id": channel_id,
            "service_url": conv["service_url"],
            "text": text,
            "reply_to_id": "",
            "raw_json": activity,
        }
    )

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.simulate.inbound",
        resource={"type": "activity", "id": activity_id},
        details={
            "bot_app_id": bot_app_id,
            "conversation_id": conversation_id,
            "channel_id": channel_id,
        },
    )

    keypair = ensure_keypair(g.storage)
    ok, reason, status_code = deliver_activity(
        url=bot["messaging_endpoint"],
        activity=activity,
        private_pem=keypair["private_pem"],
        kid=keypair["kid"],
        audience=bot["app_id"],
        service_url=conv["service_url"],
    )
    delivery = {
        "webhook_delivered": ok,
        "webhook_url": bot["messaging_endpoint"],
        "reason": reason,
        "status_code": status_code,
    }
    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="runtime",
        operation="runtime.activity.deliver",
        resource={"type": "activity", "id": activity_id},
        outcome="success" if ok else "failure",
        reason=reason,
        details={
            "bot_app_id": bot_app_id,
            "url": bot["messaging_endpoint"],
            "status_code": status_code,
        },
    )

    return jsonify({"activity": activity, "webhook": delivery}), 201


# ---- Bot inbox + reply (bot-half operator surface) ----


@twin_plane_bp.route("/bots/<bot_id>/inbox", methods=["GET"])
@require_tenant_or_admin
def get_inbox(bot_id: str):
    instance = g.storage.get_bot_instance(bot_id)
    if not instance:
        return plane_error("Bot instance not found", 404)
    if not g.is_admin and instance["tenant_id"] != g.tenant_id:
        return plane_error("Bot instance not found", 404)
    items = g.storage.list_inbox(bot_id, limit=request.args.get("limit", 100, type=int))
    return jsonify({"bot_id": bot_id, "inbox": items})


@twin_plane_bp.route("/bots/<bot_id>/reply", methods=["POST"])
@require_tenant
def post_reply(bot_id: str):
    """Operator-driven bot reply.

    Body:
        conversation_id (str, required)
        service_url (str, required)
        text (str, required)
        in_reply_to (str, optional)
        app_password (str, required) — the bot's secret on the channel
          side (Stage 1 has no client-credential storage on the bot half;
          the operator passes the password through explicitly).
    """
    instance = g.storage.get_bot_instance(bot_id)
    if not instance or instance["tenant_id"] != g.tenant_id:
        return plane_error("Bot instance not found", 404)

    payload = request.get_json(silent=True) or {}
    conversation_id = payload.get("conversation_id")
    service_url = payload.get("service_url")
    text = payload.get("text")
    app_password = payload.get("app_password")
    in_reply_to = payload.get("in_reply_to", "")

    for name, value in [
        ("conversation_id", conversation_id),
        ("service_url", service_url),
        ("text", text),
        ("app_password", app_password),
    ]:
        if not value:
            return plane_error(f"'{name}' is required", 400)

    try:
        access_token = acquire_bot_to_channel_token(
            trusted_openid_url=instance["trusted_openid_url"],
            app_id=instance["app_id"],
            app_password=app_password,
        )
    except ValidationFailure as exc:
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="runtime",
            operation="runtime.token.acquire",
            outcome="failure",
            reason=exc.reason,
            details={"trusted_openid_url": instance["trusted_openid_url"]},
        )
        return plane_error(exc.reason, 502)
    except Exception as exc:
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="runtime",
            operation="runtime.token.acquire",
            outcome="failure",
            reason=f"token endpoint error: {exc.__class__.__name__}",
            details={"trusted_openid_url": instance["trusted_openid_url"]},
        )
        return plane_error(f"token endpoint error: {exc.__class__.__name__}", 502)

    if not access_token:
        return plane_error("token endpoint returned no access_token", 502)

    import requests as _requests

    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
    if in_reply_to:
        url = f"{url}/{in_reply_to}"
    activity_body = {
        "type": "message",
        "from": {"id": instance["app_id"], "role": "bot"},
        "conversation": {"id": conversation_id},
        "text": text,
        "channelId": "msteams",
        "serviceUrl": service_url.rstrip("/"),
    }
    try:
        resp = _requests.post(
            url,
            json=activity_body,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
    except _requests.exceptions.RequestException as exc:
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="runtime",
            operation="runtime.activity.reply",
            outcome="failure",
            reason=f"channel unreachable: {exc.__class__.__name__}",
            details={"bot_id": bot_id, "url": url},
        )
        return plane_error(f"channel unreachable: {exc.__class__.__name__}", 502)

    success = 200 <= resp.status_code < 300
    body = resp.json() if success else {}
    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="runtime",
        operation="runtime.activity.reply",
        resource={"type": "bot_instance", "id": bot_id},
        outcome="success" if success else "failure",
        reason=None if success else f"channel returned HTTP {resp.status_code}",
        details={"bot_id": bot_id, "url": url, "status_code": resp.status_code},
    )
    return jsonify(
        {
            "delivered": success,
            "status_code": resp.status_code,
            "channel_response": body,
        }
    ), 200 if success else 502


# ---- Feedback ----


@twin_plane_bp.route("/feedback", methods=["POST"])
@require_tenant
def submit_feedback():
    payload = request.get_json(silent=True) or {}
    body = payload.get("body")
    if not body or not isinstance(body, str) or not body.strip():
        return plane_error("'body' is required", 400)

    feedback_id = generate_feedback_id()
    now = now_iso_z()
    record = g.storage.create_feedback(
        {
            "id": feedback_id,
            "tenant_id": g.tenant_id,
            "body": body.strip(),
            "category": payload.get("category", ""),
            "context": payload.get("context", {}),
            "status": "pending",
            "date_created": now,
            "date_updated": now,
        }
    )
    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.feedback.submit",
        resource={"type": "feedback", "id": feedback_id},
        details={"category": record["category"]},
    )
    return jsonify(record), 201


@twin_plane_bp.route("/feedback", methods=["GET"])
@require_tenant_or_admin
def list_feedback():
    status = request.args.get("status")
    tenant_id = None if g.is_admin else g.tenant_id
    items = g.storage.list_feedback(status=status, tenant_id=tenant_id)
    return jsonify({"feedback": items})


@twin_plane_bp.route("/feedback/<feedback_id>", methods=["GET"])
@require_tenant_or_admin
def get_feedback(feedback_id):
    record = g.storage.get_feedback(feedback_id)
    if not record:
        return plane_error("Feedback not found", 404)
    if not g.is_admin and record.get("tenant_id") != g.tenant_id:
        return plane_error("Feedback not found", 404)
    return jsonify(record)


@twin_plane_bp.route("/feedback/<feedback_id>", methods=["POST"])
@require_tenant_or_admin
def update_feedback(feedback_id):
    record = g.storage.get_feedback(feedback_id)
    if not record:
        return plane_error("Feedback not found", 404)
    if not g.is_admin and record.get("tenant_id") != g.tenant_id:
        return plane_error("Feedback not found", 404)
    payload = request.get_json(silent=True) or {}
    updates: dict = {}
    if "status" in payload:
        updates["status"] = payload["status"]
    updates["date_updated"] = now_iso_z()
    record = g.storage.update_feedback(feedback_id, updates)
    emit(
        g.storage,
        tenant_id=_scope_tenant_id(),
        plane="twin",
        operation="twin.feedback.update",
        resource={"type": "feedback", "id": feedback_id},
        details={"status": updates.get("status", "")},
    )
    return jsonify(record)
