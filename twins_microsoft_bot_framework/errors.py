"""HTTP error helpers — match Bot Framework's JSON error shape.

Bot Framework REST errors are a flat ``{"error": {"code": <str>, "message": <str>}}``
object. The Twin Plane uses a flatter ``{"error": <str>}`` per the platform
contract; the helpers below cover both surfaces and log nothing themselves
(callers emit the normative log record).

Reference:
  - https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-api-reference
    (retrieved 2026-05-07)
"""

from flask import jsonify


def bf_error(code: str, message: str, status: int):
    """Bot Framework REST error shape, as documented on /v3/* endpoints."""
    resp = jsonify({"error": {"code": code, "message": message}})
    resp.status_code = status
    return resp


def bf_unauthorized(message: str = "Authorization required"):
    return bf_error("BotNotAuthorized", message, 401)


def bf_forbidden(message: str):
    return bf_error("BotNotAuthorized", message, 403)


def bf_not_found(message: str = "Resource not found"):
    return bf_error("ResourceNotFound", message, 404)


def bf_bad_request(message: str):
    return bf_error("BadArgument", message, 400)


def plane_error(message: str, status: int = 400):
    """Twin Plane error shape — ``{"error": "<msg>"}`` per TWIN_PLANE.md."""
    resp = jsonify({"error": message})
    resp.status_code = status
    return resp
