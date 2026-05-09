"""Flask application factory for the Microsoft Bot Framework twin.

Both halves of the twin (channel + bot) live in this single Flask app.
Hosts inject a ``TwinStorage`` and a ``TenantStore``; behaviour
differences between local and cloud come from those injected dependencies
(SQLite vs Postgres) and the ``is_cloud`` flag, never from twin code
branching on the host type.
"""

import logging

from flask import Flask, g

from twins_local.logs import install_correlation_id

from .crypto import ensure_keypair
from .explainer import explainer_bp
from .routes.api_data import api_data_bp
from .routes.bot import bot_bp
from .routes.channel import channel_bp
from .routes.oauth_token import oauth_token_bp
from .routes.well_known import well_known_bp
from .storage import TwinStorage
from .twin_plane.routes import twin_plane_bp

logger = logging.getLogger(__name__)


def create_app(
    storage: TwinStorage,
    tenants=None,
    config: dict | None = None,
) -> Flask:
    """Create and configure the Microsoft Bot Framework twin Flask app.

    Args:
        storage: A :class:`TwinStorage` implementation provided by the host.
        tenants: A ``TenantStore`` implementation. Required for Twin Plane
            tenant auth.
        config: Configuration dict. Supported keys:
            - ``base_url`` (str): public-facing URL of the twin.
            - ``admin_token`` (str): operator-admin Bearer token.
            - ``is_cloud`` (bool): when True, the cloud guard rejects
              ``tenant_id="default"``, the simulate path requires HTTPS
              messaging endpoints, and bot instances require HTTPS
              ``trusted_openid_url`` values.
    """
    config = config or {}
    base_url = config.get("base_url", "http://localhost:8080")
    admin_token = config.get("admin_token", "")
    is_cloud = bool(config.get("is_cloud", False))

    app = Flask(__name__)
    app.config["TWIN_STORAGE"] = storage
    app.config["TWIN_TENANTS"] = tenants
    app.config["TWIN_BASE_URL"] = base_url
    app.config["TWIN_ADMIN_TOKEN"] = admin_token
    app.config["TWIN_IS_CLOUD"] = is_cloud

    install_correlation_id(app)

    @app.before_request
    def inject_context():
        g.storage = app.config["TWIN_STORAGE"]
        g.tenants = app.config["TWIN_TENANTS"]
        g.base_url = app.config["TWIN_BASE_URL"]
        g.admin_token = app.config["TWIN_ADMIN_TOKEN"]
        g.is_cloud = app.config["TWIN_IS_CLOUD"]

    # Generate / load the channel keypair eagerly so the JWKS document
    # is non-empty on the very first request (avoids a race where a
    # parallel bot validation hits an unpopulated JWKS).
    ensure_keypair(storage)

    app.register_blueprint(well_known_bp)
    app.register_blueprint(oauth_token_bp)
    app.register_blueprint(channel_bp)
    app.register_blueprint(bot_bp)
    app.register_blueprint(twin_plane_bp)
    app.register_blueprint(explainer_bp)
    # Catch-all for unimplemented /api/<rest> and /v3/<rest> paths —
    # registered LAST so specific routes take precedence. Closes
    # twins-la/twins-la#2.
    app.register_blueprint(api_data_bp)

    logger.info(
        "Microsoft Bot Framework twin created — base_url=%s cloud=%s",
        base_url,
        is_cloud,
    )
    return app
