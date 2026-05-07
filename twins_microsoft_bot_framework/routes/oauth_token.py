"""Channel-side OAuth 2.0 token endpoint.

Emulates ``POST https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token``
(retrieved 2026-05-07). A bot exchanges ``client_id`` + ``client_secret``
for a bearer the channel will accept on ``POST /v3/conversations/.../activities``.

Real Bot Framework hosts this on a separate hostname; the twin co-locates
it under its own ``base_url`` because there is only one hostname to
override on the consumer side ("manual trust" point per README).
"""

from flask import Blueprint, g, jsonify, request

from twins_local.logs import ANONYMOUS_TENANT_ID
from twins_local.tenants.ids import verify_secret

from ..crypto import ensure_keypair
from ..errors import bf_error
from ..logs import emit
from ..tokens import DEFAULT_TOKEN_TTL_SECONDS, ISSUER, sign_bot_to_channel_access_token

oauth_token_bp = Blueprint("oauth_token", __name__, url_prefix="/v1/.well-known/oauth2/v2.0")


@oauth_token_bp.route("/token", methods=["POST"])
def token():
    """``application/x-www-form-urlencoded`` body. Returns the standard
    ``{access_token, token_type:"Bearer", expires_in}`` shape.
    """
    grant_type = request.form.get("grant_type", "")
    if grant_type != "client_credentials":
        emit(
            g.storage,
            tenant_id=ANONYMOUS_TENANT_ID,
            plane="control",
            operation="control.token.issue",
            outcome="failure",
            reason=f"unsupported grant_type {grant_type!r}",
        )
        return bf_error(
            "invalid_grant",
            "Only grant_type=client_credentials is supported",
            400,
        )

    client_id = request.form.get("client_id", "")
    client_secret = request.form.get("client_secret", "")
    scope = request.form.get("scope", "")

    bot = g.storage.get_bot(client_id)
    if not bot or not verify_secret(client_secret, bot["app_password_hash"]):
        emit(
            g.storage,
            tenant_id=bot["tenant_id"] if bot else ANONYMOUS_TENANT_ID,
            plane="control",
            operation="control.token.issue",
            outcome="failure",
            reason="invalid client_id or client_secret",
            details={"client_id": client_id},
        )
        return bf_error("invalid_client", "Bot credentials are invalid", 401)

    expected_scope = f"{ISSUER}/.default"
    if scope and scope != expected_scope:
        emit(
            g.storage,
            tenant_id=bot["tenant_id"],
            plane="control",
            operation="control.token.issue",
            outcome="failure",
            reason=f"unexpected scope {scope!r} (expected {expected_scope!r})",
            details={"client_id": client_id},
        )
        return bf_error("invalid_scope", f"Expected scope {expected_scope}", 400)

    keypair = ensure_keypair(g.storage)
    access_token = sign_bot_to_channel_access_token(
        private_pem=keypair["private_pem"],
        kid=keypair["kid"],
        app_id=client_id,
    )

    emit(
        g.storage,
        tenant_id=bot["tenant_id"],
        plane="control",
        operation="control.token.issue",
        resource={"type": "bot", "id": client_id},
        details={"client_id": client_id, "expires_in": DEFAULT_TOKEN_TTL_SECONDS},
    )

    return jsonify(
        {
            "token_type": "Bearer",
            "expires_in": DEFAULT_TOKEN_TTL_SECONDS,
            "ext_expires_in": DEFAULT_TOKEN_TTL_SECONDS,
            "access_token": access_token,
        }
    )
