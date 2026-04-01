"""Proactive notification service for dossier status changes."""

from app.services.notification.service import (
    NotificationService,
    get_notification_service,
)

__all__ = ["NotificationService", "get_notification_service"]
