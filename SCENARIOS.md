# Microsoft Bot Framework Twin — Supported Scenarios

The twin emulates two halves of the [Microsoft Bot Framework](https://learn.microsoft.com/en-us/azure/bot-service/) protocol that work independently: a **channel** half and a **bot** half. A consumer can run code against either half without touching the other.

## Manual-trust requirement

Real Bot Framework SDKs hardcode `https://login.botframework.com/v1/.well-known/openidconfiguration` as the trusted source for channel signing keys. The twin publishes its own JWKS at the same path under its `base_url`, but a real bot SDK will not pick it up automatically. The bot must be configured to trust the twin's URL via the SDK's authentication-configuration override:

- **.NET (`Microsoft.Bot.Connector.Authentication`)** — set `ToBotFromChannelOpenIdMetadataUrl` (or supply an `AuthenticationConfiguration` with the equivalent override).
- **Python (`botbuilder.core.integration`)** — override `to_bot_from_channel_open_id_metadata_url` on the `AuthenticationConfiguration`.
- **JavaScript (`botbuilder`)** — pass `ToBotFromChannelOpenIdMetadataUrl` into `ConfigurationBotFrameworkAuthentication`.

This override is the consumer side of the twin contract. The twin cannot patch the SDK; surfacing the URL clearly is the most the twin can do.

## `channel-msteams` (Supported)

Emulates a Bot Framework channel with `channelId="msteams"`. Within this scenario, code that issues channel-side traffic against this twin behaves the same way against a real Bot Framework Connector.

### Scope

**In scope:**
- OpenID Connect Discovery document at `GET /v1/.well-known/openidconfiguration` — `issuer="https://api.botframework.com"`, `id_token_signing_alg_values_supported=["RS256"]`, `token_endpoint`/`jwks_uri` rooted at the twin's `base_url`.
- JWKS document at `GET /v1/.well-known/keys` — RFC 7517 shape with `kty="RSA"`, `use="sig"`, `alg="RS256"`, RFC 7638 thumbprint as `kid`, and the Bot Framework `endorsements` extension carrying `["msteams"]`.
- OAuth 2.0 client-credentials token endpoint at `POST /v1/.well-known/oauth2/v2.0/token` — accepts `grant_type=client_credentials`, `client_id`, `client_secret`, optional `scope=https://api.botframework.com/.default`. Returns `{access_token, token_type:"Bearer", expires_in:3600}` shape.
- Channel→bot JWT signing per the Bot Framework "Connector to Bot" claim shape: `iss="https://api.botframework.com"`, `aud=<bot.app_id>`, `serviceUrl=<channel base_url>`, RS256.
- Bot→channel POST at `POST /v3/conversations/{conversationId}/activities` and `POST /v3/conversations/{conversationId}/activities/{activityId}` (reply variant). Validates the bearer token's `iss`/`aud`/`appid`/`kid`/expiry/signature — failure returns the specific reason in the response body and emits a `data.activity.validate` log entry with the same `reason`.
- Operator-driven inbound simulation at `POST /_twin/simulate/inbound` — drives a synthetic user→channel→bot delivery and returns the standard messaging-twin delivery report (`webhook_delivered`, `webhook_url`, `reason`, `status_code`).

**Out of scope (behavior may be fabricated or absent):**
- Channels other than `msteams` (the channelId field is parameterised but other channels are not tested).
- Activity types other than `message` with `text` (no attachments, suggestedActions, channelData fidelity beyond accepting the field).
- Endorsement chain validation across multiple channels in one request.
- Skill-to-skill auth and OAuth user-sign-in flows.
- Long-polling activity streams.
- Real Microsoft Teams `channelData` round-tripping (the twin accepts and stores the field but does not enrich it).
- Trafficmanager-style `serviceUrl` rewriting (`smba.trafficmanager.net/...`).

## `bot-receiver` (Supported)

Emulates a Bot Framework bot's `/api/messages` endpoint. Within this scenario, code that issues channel-side traffic to a real bot can be pointed at the twin's bot half by changing only the URL.

### Scope

**In scope:**
- `POST /api/messages` accepting an Activity JSON body and a `Authorization: Bearer <jwt>` header.
- Inbound JWT validation against a configured `trusted_openid_url`. Validation enforces: `iss` matches the document's `issuer`, `aud` equals the registered bot instance's `app_id`, `nbf`/`exp` with 5-minute leeway, RS256 signature against a key in the JWKS, and the `serviceUrl` claim matches the Activity's `serviceUrl`.
- Specific machine-readable rejection reasons returned in the response body and stamped on the `data.activity.validate` log entry: `missing-bearer`, `bad-iss`, `bad-aud`, `expired`, `unknown-kid`, `sig-invalid`, `service-url-mismatch`, `unsupported-alg`, `missing-claim`.
- Inbox inspection at `GET /_twin/bots/<bot_id>/inbox` (tenant-auth).
- Operator-driven reply at `POST /_twin/bots/<bot_id>/reply` — acquires an OAuth token from the configured channel's `token_endpoint` and POSTs a Bot Framework Activity to `serviceUrl + /v3/conversations/{conversationId}/activities`.

**Out of scope:**
- Synchronous dialog logic: the twin does not auto-reply on inbound. Replies are operator-driven via the Twin Plane.
- ConversationUpdate / messageReaction / typing indicator activities (accepted but not interpreted).
- Multi-tenant skill scenarios (single-tenant per bot instance).
- OAuth user-token retrieval for bots (`/api/usertoken/...`).

## Authoritative References

- Bot Framework REST: Authenticate requests with the Bot Connector API — https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication (retrieved 2026-05-07)
- Bot Framework REST: Create messages — https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-create-messages (retrieved 2026-05-07)
- Bot Framework REST: API reference (Activity object) — https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-api-reference (retrieved 2026-05-07)
- Microsoft Teams platform: Conversation basics — https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/conversation-basics (retrieved 2026-05-07)
- RFC 7517 — JSON Web Key (JWK) — https://datatracker.ietf.org/doc/html/rfc7517 (retrieved 2026-05-07)
- RFC 7519 — JSON Web Token (JWT) — https://datatracker.ietf.org/doc/html/rfc7519 (retrieved 2026-05-07)
- RFC 7638 — JSON Web Key (JWK) Thumbprint — https://datatracker.ietf.org/doc/html/rfc7638 (retrieved 2026-05-07)

### Version

- 0.1.0 — Initial release. Both halves working independently; channel half supports `msteams` channelId; bot half validates against any compatible OpenID metadata URL. Operator-driven inbound simulation and bot reply.
