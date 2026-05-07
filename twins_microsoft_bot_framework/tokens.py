"""Bot Framework JWT issuance and validation.

Two distinct claim shapes per Microsoft's public auth docs (retrieved
2026-05-07,
https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication):

* **Channel → Bot.** ``iss = "https://api.botframework.com"``, ``aud = bot's
  appId``, plus ``serviceUrl`` claim matching the activity's ``serviceUrl``.
  The bot validates against the channel's OpenID metadata.

* **Bot → Channel** (i.e. the access token the channel issues at its
  ``/oauth2/v2.0/token`` endpoint). ``iss = "https://api.botframework.com"``,
  ``aud = "https://api.botframework.com"``, plus ``appid`` claim equal to
  the bot's appId.

The twin signs both with the channel's RSA key. The validate side accepts
JWTs whose ``kid`` is in a JWKS fetched from a configured OpenID metadata
URL — this is the bot half's "manual trust" point.
"""

import time
from dataclasses import dataclass
from typing import Optional

import jwt
import requests

from .crypto import jwk_for_public_key, load_private_key, load_public_key

ISSUER = "https://api.botframework.com"
"""Constant ``iss`` for both directions, matching real Bot Framework."""

DEFAULT_TOKEN_TTL_SECONDS = 3600
"""1 hour — matches real Bot Framework token TTL."""

CLOCK_SKEW_SECONDS = 5 * 60
"""Industry-standard 5-minute skew, per BF auth docs."""

JWKS_CACHE_SECONDS = 5 * 60
"""Cache JWKS responses for 5 minutes; lower than the BF-recommended 24 h
because tests rotate keys frequently."""


# ---- channel-side issuance ----


def sign_channel_to_bot_jwt(
    *,
    private_pem: str,
    kid: str,
    audience: str,
    service_url: str,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
) -> str:
    """Sign a JWT the channel includes when delivering an Activity to a bot.

    The bot validates this token (BF auth doc §"Connector to Bot").
    """
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": audience,
        "serviceUrl": service_url,
        "nbf": now - 5,
        "exp": now + ttl_seconds,
        "iat": now,
    }
    return jwt.encode(
        payload,
        load_private_key(private_pem),
        algorithm="RS256",
        headers={"kid": kid, "typ": "JWT"},
    )


def sign_bot_to_channel_access_token(
    *,
    private_pem: str,
    kid: str,
    app_id: str,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
) -> str:
    """Sign the access token the channel returns at its
    ``/oauth2/v2.0/token`` endpoint. The bot uses it to call
    ``POST /v3/conversations/.../activities``."""
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": ISSUER,
        "appid": app_id,
        "nbf": now - 5,
        "exp": now + ttl_seconds,
        "iat": now,
    }
    return jwt.encode(
        payload,
        load_private_key(private_pem),
        algorithm="RS256",
        headers={"kid": kid, "typ": "JWT"},
    )


# ---- channel-side validation (bot→channel direction) ----


@dataclass
class ValidationFailure(Exception):
    reason: str
    """Specific machine-readable rejection reason. Intentionally enumerated:
    ``bad-iss`` / ``bad-aud`` / ``expired`` / ``unknown-kid`` / ``sig-invalid``
    / ``service-url-mismatch`` / ``missing-bearer`` / ``missing-claim`` /
    ``unsupported-alg``. Tests assert on these literals."""


def validate_channel_self_issued_token(
    *, token: str, public_pem: str, kid: str
) -> dict:
    """Validate a token the channel itself issued (i.e. a bot→channel
    access token). Used on ``POST /v3/conversations/.../activities`` to
    authenticate the calling bot against the channel."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise ValidationFailure("sig-invalid") from exc
    if header.get("alg") != "RS256":
        raise ValidationFailure("unsupported-alg")
    if header.get("kid") != kid:
        raise ValidationFailure("unknown-kid")
    try:
        claims = jwt.decode(
            token,
            load_public_key(public_pem),
            algorithms=["RS256"],
            audience=ISSUER,
            issuer=ISSUER,
            leeway=CLOCK_SKEW_SECONDS,
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValidationFailure("expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise ValidationFailure("bad-aud") from exc
    except jwt.InvalidIssuerError as exc:
        raise ValidationFailure("bad-iss") from exc
    except jwt.InvalidTokenError as exc:
        raise ValidationFailure("sig-invalid") from exc
    if "appid" not in claims:
        raise ValidationFailure("missing-claim")
    return claims


# ---- bot-side validation (channel→bot direction) ----

_jwks_cache: dict[str, tuple[float, dict]] = {}


def _fetch_openid_config(openid_url: str) -> dict:
    resp = requests.get(openid_url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _fetch_jwks(jwks_uri: str) -> dict:
    cached = _jwks_cache.get(jwks_uri)
    now = time.time()
    if cached and (now - cached[0]) < JWKS_CACHE_SECONDS:
        return cached[1]
    resp = requests.get(jwks_uri, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    _jwks_cache[jwks_uri] = (now, body)
    return body


def clear_jwks_cache() -> None:
    """Test hook — callers that rotate keys mid-test must clear the cache."""
    _jwks_cache.clear()


def validate_channel_to_bot_jwt(
    *,
    token: str,
    audience: str,
    expected_service_url: str,
    trusted_openid_url: str,
) -> dict:
    """Validate a channel→bot JWT against the channel's published metadata.

    This is the bot-half hot path. Returns the decoded claims on success;
    raises :class:`ValidationFailure` with a specific ``reason`` on the
    rejection paths the BF auth doc enumerates.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise ValidationFailure("sig-invalid") from exc
    alg = header.get("alg")
    if alg != "RS256":
        raise ValidationFailure("unsupported-alg")
    kid = header.get("kid")
    if not kid:
        raise ValidationFailure("missing-claim")

    config = _fetch_openid_config(trusted_openid_url)
    jwks = _fetch_jwks(config["jwks_uri"])
    matching = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not matching:
        raise ValidationFailure("unknown-kid")

    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching)
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=config.get("issuer", ISSUER),
            leeway=CLOCK_SKEW_SECONDS,
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValidationFailure("expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise ValidationFailure("bad-aud") from exc
    except jwt.InvalidIssuerError as exc:
        raise ValidationFailure("bad-iss") from exc
    except jwt.InvalidTokenError as exc:
        raise ValidationFailure("sig-invalid") from exc

    if claims.get("serviceUrl") and claims["serviceUrl"] != expected_service_url:
        raise ValidationFailure("service-url-mismatch")
    return claims


def acquire_bot_to_channel_token(
    *,
    trusted_openid_url: str,
    app_id: str,
    app_password: str,
) -> Optional[str]:
    """Bot-side helper: discover the channel's token endpoint via the
    OpenID metadata, then exchange ``app_id``/``app_password`` for a
    bearer the bot can present back to the channel.

    Returns the access_token on success; raises ``requests.HTTPError`` or
    a :class:`ValidationFailure` with a specific reason on failure.
    """
    config = _fetch_openid_config(trusted_openid_url)
    token_endpoint = config.get("token_endpoint")
    if not token_endpoint:
        raise ValidationFailure("missing-token-endpoint")
    resp = requests.post(
        token_endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_password,
            "scope": f"{ISSUER}/.default",
        },
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("access_token")


def jwks_doc_for_storage_keypair(storage_keypair: dict, *, endorsements: list[str]) -> dict:
    """Render the channel's stored keypair as a JWKS document for
    publication at ``/v1/.well-known/keys``."""
    public_key = load_public_key(storage_keypair["public_pem"])
    return {
        "keys": [
            jwk_for_public_key(
                public_key,
                kid=storage_keypair["kid"],
                endorsements=endorsements,
            )
        ]
    }
