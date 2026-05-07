"""Local-host configuration. Values come from the environment so the
container deployment can override them without code changes."""

import os

DB_PATH = os.environ.get("TWIN_DB_PATH", "data/microsoft_bot_framework_twin.db")
HOST = os.environ.get("TWIN_HOST", "127.0.0.1")
PORT = int(os.environ.get("TWIN_PORT", "8080"))
BASE_URL = os.environ.get("TWIN_BASE_URL", f"http://{HOST}:{PORT}")
ADMIN_TOKEN = os.environ.get("TWIN_ADMIN_TOKEN", "")
