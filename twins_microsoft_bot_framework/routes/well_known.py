"""OpenID Connect Discovery + JWKS — channel-half public surface.

Real Bot Framework publishes:
  * ``GET https://login.botframework.com/v1/.well-known/openidconfiguration``
  * ``GET https://login.botframework.com/v1/.well-known/keys``

The twin mirrors the same paths (under its own ``base_url``) and the same
document shapes. A consumer override that points the bot SDK at
``<twin>/v1/.well-known/openidconfiguration`` is sufficient to make a
real Bot Framework bot accept the twin's tokens — the rest of the
protocol matches.

References (retrieved 2026-05-07):
  - https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication
"""

from flask import Blueprint, g, jsonify

from ..crypto import ensure_keypair
from twins_local.logs import ANONYMOUS_TENANT_ID

from ..logs import emit
from ..tokens import ISSUER, jwks_doc_for_storage_keypair

well_known_bp = Blueprint("well_known", __name__, url_prefix="/v1/.well-known")

ENDORSED_CHANNELS = ["msteams"]


@well_known_bp.route("/openidconfiguration", methods=["GET"])
def openid_configuration():
    """OpenID Connect Discovery doc.

    Real BF returns a fixed body keyed off ``login.botframework.com``;
    the twin substitutes its own ``base_url`` so consumers can route
    JWKS fetches and token requests to it.
    """
    base = g.base_url.rstrip("/")
    body = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{base}/v1/.well-known/oauth2/v2.0/authorize",
        "token_endpoint": f"{base}/v1/.well-known/oauth2/v2.0/token",
        "jwks_uri": f"{base}/v1/.well-known/keys",
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }
    emit(
        g.storage,
        tenant_id=ANONYMOUS_TENANT_ID,
        plane="data",
        operation="data.openid.fetch",
        details={"endpoint": "openidconfiguration"},
    )
    return jsonify(body)


@well_known_bp.route("/keys", methods=["GET"])
def jwks():
    """JWKS — RFC 7517 with the BF ``endorsements`` extension."""
    keypair = ensure_keypair(g.storage)
    body = jwks_doc_for_storage_keypair(keypair, endorsements=ENDORSED_CHANNELS)
    emit(
        g.storage,
        tenant_id=ANONYMOUS_TENANT_ID,
        plane="data",
        operation="data.jwks.fetch",
        details={"keys": len(body["keys"])},
    )
    return jsonify(body)
