"""Explainer landing page + agent instructions for the twin.

Serves:
  GET /                          — HTML explainer page for humans and agents
  GET /_twin/agent-instructions  — Plain-text agent instructions
"""

from flask import Blueprint, Response

explainer_bp = Blueprint("explainer", __name__)

AGENT_INSTRUCTIONS = """\
# Microsoft Bot Framework Twin — microsoft-bot-framework.twins.la

A high-fidelity digital twin of two halves of the Microsoft Bot Framework
that work independently:

  * Channel half (default channelId="msteams") — issues signed JWTs to
    bots, publishes JWKS, accepts bot-to-channel activity POSTs.
  * Bot half — emulates a Bot Framework bot at /api/messages and
    validates inbound channel JWTs.

## Manual-trust requirement

Real Bot Framework SDKs hardcode `login.botframework.com` as the trusted
JWKS source. To use this twin's channel half from a real bot, the SDK
must be configured to trust the twin's JWKS URL:

  * .NET: `ConfigurationBotFrameworkAuthentication` with a
    `ToBotFromChannelOpenIdMetadataUrl` setting pointing at
    `<base>/v1/.well-known/openidconfiguration`.
  * Python (botbuilder-py): `AuthenticationConfiguration` with
    `to_bot_from_channel_open_id_metadata_url` overridden.
  * JS: `ConfigurationBotFrameworkAuthentication` with
    `ToBotFromChannelOpenIdMetadataUrl` overridden.

The twin documents this URL prominently — see /_twin/settings.

## Authentication

Twin Plane: HTTP Basic (tenant_id:tenant_secret)
  Bootstrap a tenant first:
    POST /_twin/tenants -> {tenant_id, tenant_secret}

Twin Plane Admin: Bearer token (set by deployment owner)
  Authorization: Bearer <admin_token>
  Or: X-Twin-Admin-Token: <admin_token>

Provider:
  Channel side: bot acquires bearer at POST /v1/.well-known/oauth2/v2.0/token
                using client_id (= app_id) + client_secret (= app_password).
  Bot side: incoming requests carry Authorization: Bearer <jwt> signed
            by the channel; the bot validates against the channel's JWKS.

## Key Endpoints

Twin Plane (no auth):
  GET  /_twin/health
  GET  /_twin/scenarios
  GET  /_twin/settings
  GET  /_twin/references
  POST /_twin/tenants

Twin Plane (Basic tenant_id:tenant_secret):
  POST /_twin/accounts            — kind=bot OR kind=bot_instance
  GET  /_twin/accounts            — list both kinds
  GET  /_twin/logs
  POST /_twin/simulate/inbound    — drive a user→channel→bot delivery
  GET  /_twin/bots/<bot_id>/inbox — bot-half receive queue
  POST /_twin/bots/<bot_id>/reply — operator-driven bot→channel reply
  POST /_twin/feedback
  GET  /_twin/feedback

Channel half (no auth):
  GET  /v1/.well-known/openidconfiguration
  GET  /v1/.well-known/keys
  POST /v1/.well-known/oauth2/v2.0/token  (client_credentials)

Channel half (Bearer):
  POST /v3/conversations/{conversationId}/activities
  POST /v3/conversations/{conversationId}/activities/{activityId}

Bot half (Bearer JWT):
  POST /api/messages

## Quick Start (local)

1. pip install twins-microsoft-bot-framework twins-microsoft-bot-framework-local
   python -m twins_microsoft_bot_framework_local

2. Bootstrap a tenant:
   curl -X POST http://localhost:8080/_twin/tenants \\
     -H "Content-Type: application/json" \\
     -d '{"friendly_name": "Dev"}'
   # -> { tenant_id, tenant_secret }

3. Register a bot the channel will deliver to:
   curl -X POST http://localhost:8080/_twin/accounts \\
     -u "TENANT_ID:TENANT_SECRET" \\
     -H "Content-Type: application/json" \\
     -d '{"kind":"bot","messaging_endpoint":"http://localhost:9000/api/messages"}'
   # -> { app_id, app_password, ... }

4. Drive a synthetic user→channel→bot delivery:
   curl -X POST http://localhost:8080/_twin/simulate/inbound \\
     -u "TENANT_ID:TENANT_SECRET" \\
     -H "Content-Type: application/json" \\
     -d '{"bot_app_id":"<APP_ID>","text":"hello"}'
   # -> { activity, webhook: { webhook_delivered, webhook_url, reason, status_code } }

5. (Optional) point the same instance at itself to drive a round-trip
   without external code: register a bot_instance with
   trusted_openid_url=http://localhost:8080/v1/.well-known/openidconfiguration
   and set the bot's messaging_endpoint to /api/messages on the same
   process.

## Reference

GitHub:           https://github.com/twins-la/microsoft-bot-framework
Project overview: https://twins.la
All twins:        https://github.com/twins-la/twins-la
"""


EXPLAINER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>microsoft-bot-framework.twins.la &mdash; Microsoft Bot Framework Twin</title>
    <link rel="icon" type="image/png" href="https://twins.la/twins.png">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            min-height: 100vh;
            background: #f8f8f8;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #374151;
            padding: 4rem 2rem;
            line-height: 1.7;
        }
        main { max-width: 700px; margin: 0 auto; }
        h1 {
            font-size: clamp(2rem, 5vw, 3rem);
            font-weight: 600;
            letter-spacing: -0.03em;
            color: #1a2e4a;
            margin-bottom: 0.5rem;
        }
        h1 .microsoft-bot-framework { color: #4b53bc; }
        .tagline { font-size: 1.1rem; color: #6b7280; margin-bottom: 2.5rem; font-weight: 300; }
        h2 {
            font-size: 1.25rem;
            font-weight: 600;
            color: #1a2e4a;
            margin: 2rem 0 0.75rem;
            letter-spacing: -0.01em;
        }
        p { margin-bottom: 1rem; color: #6b7280; }
        p strong { color: #1a2e4a; }
        a { color: #4b53bc; text-decoration: none; }
        a:hover { color: #353a82; text-decoration: underline; }
        ul { list-style: none; padding: 0; margin-bottom: 1rem; }
        ul li { padding: 0.3rem 0; color: #6b7280; }
        ul li::before { content: "\\2192  "; color: #4b53bc; }
        code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85em;
            background: #f3f4f6;
            padding: 0.15em 0.4em;
            border-radius: 4px;
            color: #1a2e4a;
            border: 1px solid #e5e7eb;
        }
        .snippet-box {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 1.5rem;
            margin: 1rem 0;
            position: relative;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .snippet-box pre {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: #6b7280;
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.5;
            max-height: 400px;
            overflow-y: auto;
        }
        .copy-btn {
            position: absolute;
            top: 0.75rem;
            right: 0.75rem;
            background: #f3f4f6;
            color: #6b7280;
            border: 1px solid #e5e7eb;
            padding: 0.3rem 0.7rem;
            border-radius: 6px;
            font-size: 0.75rem;
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            transition: background 0.15s, color 0.15s;
        }
        .copy-btn:hover { background: #1a2e4a; color: #ffffff; }
        .links { margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid #e5e7eb; }
        .links a { margin-right: 1.5rem; font-size: 0.9rem; }
        footer { margin-top: 3rem; color: #6b7280; font-size: 0.8rem; }
        footer .dot { color: #4b53bc; }
        .breadcrumb { margin-bottom: 0.5rem; font-size: 0.85rem; }
        .breadcrumb a { color: #0e7490; }
        .breadcrumb a:hover { color: #1a2e4a; }
        .callout {
            background: #fff7ed;
            border: 1px solid #f4d6a3;
            border-radius: 10px;
            padding: 1rem 1.25rem;
            margin: 1.25rem 0;
            color: #5b4012;
        }
    </style>
</head>
<body>
    <main>
        <p class="breadcrumb"><a href="https://twins.la">twins.la</a></p>
        <h1><span class="microsoft-bot-framework">microsoft-bot-framework</span>.twins.la</h1>
        <p class="tagline">A digital twin of the Microsoft Bot Framework.</p>

        <h2>What is this?</h2>
        <p>
            A high-fidelity digital twin of two halves of the Microsoft Bot
            Framework that work independently:
        </p>
        <ul>
            <li><strong>Channel half</strong> &mdash; emulates a channel (default <code>msteams</code>). Signs channel-to-bot JWTs, publishes JWKS, issues OAuth tokens, accepts bot-to-channel POSTs.</li>
            <li><strong>Bot half</strong> &mdash; emulates a Bot Framework bot at <code>/api/messages</code> and validates inbound channel JWTs against a configured OpenID metadata URL.</li>
        </ul>

        <div class="callout">
            <strong>Manual-trust requirement.</strong> Real Bot Framework SDKs
            hardcode <code>login.botframework.com</code> as the trusted JWKS
            source. To use this twin's channel from a real bot, configure the
            SDK's <code>ToBotFromChannelOpenIdMetadataUrl</code>
            (<code>to_bot_from_channel_open_id_metadata_url</code> in
            botbuilder-py) to point at this twin's
            <code>/v1/.well-known/openidconfiguration</code>. The twin cannot
            patch the SDK for you &mdash; the override is the consumer side
            of the contract.
        </div>

        <h2>Supported scenarios</h2>
        <ul>
            <li><code>channel-msteams</code> &mdash; OpenID metadata + JWKS publication, OAuth token issue, bot-to-channel activity POSTs, operator-driven inbound simulation</li>
            <li><code>bot-receiver</code> &mdash; <code>/api/messages</code> with channel-JWT validation, configurable trusted OpenID URL, inbox + operator-driven reply</li>
        </ul>

        <h2>How to use it</h2>
        <p>
            <strong>Cloud:</strong> Point your Bot Framework SDK's
            <code>ToBotFromChannelOpenIdMetadataUrl</code> at
            <code>https://microsoft-bot-framework.twins.la/v1/.well-known/openidconfiguration</code>,
            and use the <code>app_id</code>/<code>app_password</code>
            returned by <code>POST /_twin/accounts</code>.
        </p>
        <p>
            <strong>Local:</strong> Install with
            <code>pip install twins-microsoft-bot-framework-local</code> and
            run a local instance on any port. Same API, same behavior, your
            machine.
        </p>

        <h2>For agents</h2>
        <p>
            Copy this into your agent's system prompt, tool configuration, or
            CLAUDE.md. Also available as plain text at
            <a href="/_twin/agent-instructions"><code>/_twin/agent-instructions</code></a>.
        </p>
        <div class="snippet-box">
            <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('agent-snippet').textContent).then(()=>{this.textContent='Copied!';setTimeout(()=>this.textContent='Copy',1500)})">Copy</button>
            <pre id="agent-snippet">""" + AGENT_INSTRUCTIONS.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + """</pre>
        </div>

        <div class="links">
            <a href="https://github.com/twins-la/microsoft-bot-framework">GitHub</a>
            <a href="https://twins.la">twins.la</a>
            <a href="/_twin/health">Health</a>
            <a href="/_twin/scenarios">Scenarios</a>
        </div>

        <footer>twins.la <span class="dot">&middot;</span> Where agents meet their environment.</footer>
    </main>
</body>
</html>
"""


@explainer_bp.route("/", methods=["GET"])
def explainer_page():
    return EXPLAINER_HTML
