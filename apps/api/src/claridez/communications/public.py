"""Puerto público estrecho de intención, preferencias y transporte P14."""

from enum import StrEnum

from .errors import CommunicationsError
from .models import Channel, Purpose
from .services import (
    append_preference,
    cancel_intent,
    published_template_channel_if_compatible,
    published_template_for_purpose,
    reconcile_provider_event,
    request_intent,
    sender_identity_for_webhook,
    template_version_is_published_for,
)


class PreferenceAction(StrEnum):
    CLIENT_ALLOW = "client_allow"
    CLIENT_UNSUBSCRIBE = "client_unsubscribe"
    ADMIN_SUPPRESS = "admin_suppress"
    ADMIN_RELEASE = "admin_release"
    HARD_BOUNCE = "hard_bounce"
    TECHNICAL_RELEASE = "technical_release"


__all__ = (
    "Channel",
    "CommunicationsError",
    "PreferenceAction",
    "Purpose",
    "append_preference",
    "cancel_intent",
    "request_intent",
    "published_template_for_purpose",
    "published_template_channel_if_compatible",
    "reconcile_provider_event",
    "sender_identity_for_webhook",
    "template_version_is_published_for",
)
