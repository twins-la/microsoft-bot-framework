# Microsoft Bot Framework Twin

A digital twin of two halves of the [Microsoft Bot Framework](https://learn.microsoft.com/en-us/azure/bot-service/) for [twins.la](https://twins.la). Both halves work independently — a real bot can be pointed at the twin's channel, a real channel can be pointed at the twin's bot, or the twin can drive itself end-to-end.

## What this is

- **Channel half** — emulates a Bot Framework channel (default `channelId="msteams"`). Publishes JWKS, issues OAuth client-credentials tokens, signs channel→bot JWTs, accepts bot→channel activity POSTs.
- **Bot half** — emulates a Bot Framework bot at `POST /api/messages`. Validates inbound channel JWTs against a configured OpenID metadata URL. Operator-driven replies via the channel's `serviceUrl`.

## Manual-trust requirement

Real Bot Framework SDKs hardcode `login.botframework.com` as the trusted JWKS source. To use this twin's channel half from a real bot, configure the SDK's authentication-configuration override (`ToBotFromChannelOpenIdMetadataUrl` in .NET / JS, `to_bot_from_channel_open_id_metadata_url` in botbuilder-py) to point at this twin's `/v1/.well-known/openidconfiguration`. See [`SCENARIOS.md`](SCENARIOS.md#manual-trust-requirement) for the per-SDK details.

## Supported scenarios

See [`SCENARIOS.md`](SCENARIOS.md) for the full scope and authoritative references.

- `channel-msteams` — OpenID metadata + JWKS publication, OAuth token issue, channel→bot JWT signing, bot→channel activity POSTs, operator-driven inbound simulation.
- `bot-receiver` — `/api/messages` with channel JWT validation against a configurable trusted OpenID URL, with specific machine-readable rejection reasons. Inbox inspection + operator-driven replies via the Twin Plane.

## Usage

This package is not run directly. It is loaded by a host:

- **Local**: `twins-microsoft-bot-framework-local` (sibling package under `twins_microsoft_bot_framework_local/`) — run via gunicorn or `python -m twins_microsoft_bot_framework_local`.
- **Cloud**: available at [microsoft-bot-framework.twins.la](https://microsoft-bot-framework.twins.la).

## Quick Start (local)

```bash
pip install -e . ./twins_microsoft_bot_framework_local/
python -m twins_microsoft_bot_framework_local
```

Then drive a synthetic round-trip:

```bash
# Bootstrap a tenant
curl -X POST http://localhost:8080/_twin/tenants \
  -H "Content-Type: application/json" \
  -d '{"friendly_name": "Dev"}'
# -> { "tenant_id": "...", "tenant_secret": "..." }

# Register a bot the channel will deliver to
curl -X POST http://localhost:8080/_twin/accounts \
  -u "TENANT_ID:TENANT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"kind":"bot","messaging_endpoint":"http://localhost:8080/api/messages","friendly_name":"Demo Bot"}'
# -> { "app_id": "...", "app_password": "...", ... }

# Register the SAME process as a bot instance pointing at its own channel
# (this is the twin "driving itself" — useful for tests)
curl -X POST http://localhost:8080/_twin/accounts \
  -u "TENANT_ID:TENANT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"kind":"bot_instance","app_id":"<APP_ID_FROM_PREVIOUS>","trusted_openid_url":"http://localhost:8080/v1/.well-known/openidconfiguration"}'

# Drive an inbound user message
curl -X POST http://localhost:8080/_twin/simulate/inbound \
  -u "TENANT_ID:TENANT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"bot_app_id":"<APP_ID>","text":"hello"}'
# -> { "activity": {...}, "webhook": { "webhook_delivered": true, ... } }
```

The Twin Plane (`/_twin/*`) is documented in [twins-la/TWIN_PLANE.md](https://github.com/twins-la/twins-la/blob/main/TWIN_PLANE.md).

## Tests

```bash
pip install -e .[dev] ./twins_microsoft_bot_framework_local/
pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
