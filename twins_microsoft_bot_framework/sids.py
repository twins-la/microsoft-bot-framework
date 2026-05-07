"""Identifier generators for the Microsoft Bot Framework twin.

The real Bot Framework uses GUIDs for ``conversationId`` and
``activityId``; ``appId`` is also a GUID; ``appPassword`` is a high-entropy
secret string. The twin matches the format so consumer code that parses
or compares these does not need to special-case the twin.
"""

import secrets
import uuid


def generate_app_id() -> str:
    """Bot Framework appId — a UUID v4."""
    return str(uuid.uuid4())


def generate_app_password() -> str:
    """Bot Framework app password — URL-safe random token."""
    return secrets.token_urlsafe(32)


def generate_bot_instance_id() -> str:
    """Twin-side bot-instance id (bot-half resource)."""
    return f"bi_{secrets.token_urlsafe(12)}"


def generate_conversation_id() -> str:
    """Bot Framework conversationId — UUID v4 (Teams uses opaque strings)."""
    return str(uuid.uuid4())


def generate_activity_id() -> str:
    """Activity id — opaque string, unique within a conversation."""
    return secrets.token_urlsafe(12)


def generate_feedback_id() -> str:
    return f"fb_{secrets.token_urlsafe(12)}"
