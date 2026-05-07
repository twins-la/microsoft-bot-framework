"""Abstract storage interface for the Microsoft Bot Framework twin.

Hosts (local SQLite, cloud Postgres) implement this contract. The twin
package never imports a specific database driver.

Resources are split between the two halves of the twin:

* ``bots`` — channel-half view of a bot the channel knows how to deliver to
  (appId, appPassword, messaging_endpoint, service_url_prefix).
* ``bot_instances`` — bot-half configuration (which channel's OpenID URL the
  bot trusts, the appId the bot accepts as ``aud`` on inbound JWTs).
* ``conversations`` and ``activities`` — message history shared by both halves.
* ``inbox_messages`` — bot-half receive queue, populated when ``/api/messages``
  validates a channel JWT successfully.
* ``signing_keys`` — channel's RSA keypair (PEM); persistent so the JWKS is
  stable across restarts.
"""

from abc import ABC, abstractmethod
from typing import Optional


class TwinStorage(ABC):
    """Storage backend contract that hosts must implement."""

    # -- Channel-side bots --

    @abstractmethod
    def create_bot(
        self,
        *,
        tenant_id: str,
        app_id: str,
        app_password_hash: str,
        messaging_endpoint: str,
        friendly_name: str,
    ) -> dict:
        """Persist a channel-side bot record. Returns the stored row."""

    @abstractmethod
    def get_bot(self, app_id: str) -> Optional[dict]:
        """Fetch a bot by appId. Returns ``None`` if not found."""

    @abstractmethod
    def list_bots(self, tenant_id: Optional[str] = None) -> list[dict]:
        """List bots; ``tenant_id=None`` returns all (admin only)."""

    # -- Bot-side instances --

    @abstractmethod
    def create_bot_instance(
        self,
        *,
        tenant_id: str,
        bot_id: str,
        app_id: str,
        trusted_openid_url: str,
        friendly_name: str,
    ) -> dict:
        """Persist a bot-half instance. Returns the stored row."""

    @abstractmethod
    def get_bot_instance(self, bot_id: str) -> Optional[dict]:
        """Fetch a bot instance by id."""

    @abstractmethod
    def get_bot_instance_by_app_id(self, app_id: str) -> Optional[dict]:
        """Fetch a bot instance by its appId (the JWT ``aud`` value)."""

    @abstractmethod
    def list_bot_instances(self, tenant_id: Optional[str] = None) -> list[dict]:
        """List bot instances; ``tenant_id=None`` for admin."""

    # -- Conversations + activities --

    @abstractmethod
    def upsert_conversation(self, data: dict) -> dict:
        """Create-or-update a conversation. ``data`` carries id, bot, channel, tenant, service_url."""

    @abstractmethod
    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """Fetch a conversation by id."""

    @abstractmethod
    def create_activity(self, data: dict) -> dict:
        """Persist an activity record. Returns the stored dict (with ``id``)."""

    @abstractmethod
    def list_activities(
        self,
        *,
        conversation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """List activities, optionally filtered by conversation and/or tenant."""

    # -- Bot-side inbox --

    @abstractmethod
    def append_inbox(self, bot_id: str, activity: dict) -> dict:
        """Append an activity to a bot instance's inbox. Returns the stored entry."""

    @abstractmethod
    def list_inbox(self, bot_id: str, *, limit: int = 100) -> list[dict]:
        """List inbox entries for a bot instance, newest first."""

    # -- Signing keys (channel side) --

    @abstractmethod
    def get_signing_key(self) -> Optional[dict]:
        """Fetch the channel's signing keypair. Returns dict with kid+private_pem+public_pem or None."""

    @abstractmethod
    def put_signing_key(self, *, kid: str, private_pem: str, public_pem: str) -> dict:
        """Persist the channel's signing keypair."""

    # -- Feedback --

    @abstractmethod
    def create_feedback(self, data: dict) -> dict:
        """Persist a feedback record."""

    @abstractmethod
    def get_feedback(self, feedback_id: str) -> Optional[dict]:
        """Fetch a feedback record by id."""

    @abstractmethod
    def list_feedback(
        self,
        *,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """List feedback, optionally filtered."""

    @abstractmethod
    def update_feedback(self, feedback_id: str, updates: dict) -> Optional[dict]:
        """Mutate a feedback record. Returns the updated dict or None."""

    # -- Logs --

    @abstractmethod
    def append_log(self, entry: dict) -> None:
        """Append an operation log entry. ``entry`` carries ``tenant_id``."""

    @abstractmethod
    def list_logs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """Retrieve operation logs, optionally scoped to a tenant."""
