"""Microsoft Bot Framework digital twin.

Two independent halves under one Flask app:

* Channel half — emulates a Bot Framework channel (default ``channelId="msteams"``).
  Publishes JWKS at ``/v1/.well-known/keys`` + an OpenID Connect Discovery
  document at ``/v1/.well-known/openidconfiguration``. Issues OAuth
  client-credentials tokens at ``/v1/.well-known/oauth2/v2.0/token``.
  Accepts bot→channel POSTs at ``/v3/conversations/{conversationId}/activities``.

* Bot half — emulates a Bot Framework bot. Accepts ``POST /api/messages``,
  validates the inbound channel JWT against a configured ``trusted_openid_url``,
  and replies asynchronously via the channel's ``serviceUrl``.

Real Bot Framework SDKs hardcode ``login.botframework.com`` as the trusted
issuer; pointing a real bot at the twin requires the SDK's
``ConfigurationBotFrameworkAuthentication`` (or equivalent) to override the
OpenID metadata URL — see ``SCENARIOS.md``.
"""

__version__ = "0.2.0"
