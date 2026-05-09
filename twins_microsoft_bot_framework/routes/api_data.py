"""Catch-all for unknown ``/api/<rest>`` and ``/v3/<rest>`` paths.

Closes twins-la/twins-la#2 (msbf half): without these catch-alls, Flask
returns its default HTML 404 on any unimplemented endpoint, which breaks
Bot Framework SDK consumers that decode `Content-Type: application/json`.
The canonical envelope (per Bot Framework REST docs) is
``{error: {code, message}}``.
"""

from flask import Blueprint

from ..errors import bf_not_found

api_data_bp = Blueprint("api_data", __name__)


@api_data_bp.route(
    "/api/<path:rest>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def unknown_api_path(rest: str):
    return bf_not_found(f"The endpoint /api/{rest} does not exist")


@api_data_bp.route(
    "/v3/<path:rest>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def unknown_v3_path(rest: str):
    return bf_not_found(f"The endpoint /v3/{rest} does not exist")
