# messaging/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone


class Campaign(models.Model):
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_campaigns",
    )
    is_active = models.BooleanField(default=False)
    scheduled_for = models.DateTimeField(null=True, blank=True)

    # Optional: a set of users to target for this campaign
    targets = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="campaign_targets",
    )

    # Optional counters (can be updated from status callbacks)
    total_sent = models.PositiveIntegerField(default=0)
    total_delivered = models.PositiveIntegerField(default=0)
    total_failed = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"Campaign #{self.pk}"


class Message(models.Model):
    class Direction(models.TextChoices):
        OUTBOUND = "OUTBOUND", "Outbound"
        INBOUND = "INBOUND", "Inbound"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SENT = "SENT", "Sent"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"

    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="Recipient user (for inbound, this is the user who sent it to us).",
    )
    direction = models.CharField(max_length=8, choices=Direction.choices)
    body = models.TextField()

    # Twilio-related fields
    twilio_sid = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Twilio Message SID (if applicable)",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    error_code = models.CharField(
        max_length=32,
        blank=True,
        help_text="Twilio error code (if any)",
    )
    raw_provider_status = models.CharField(
        max_length=32,
        blank=True,
        help_text="Exact provider status (e.g., 'sent', 'delivered', 'undelivered')",
    )

    # Optional linkage to a campaign (part of a broadcast)
    campaign = models.ForeignKey(
        "Campaign",  # or "messaging.Campaign"
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    def mark_status(self, status, raw=None, error_code=None, delivered_at=None):
        self.status = status
        if raw is not None:
            self.raw_provider_status = raw
        if error_code is not None:
            self.error_code = error_code
        if delivered_at is not None:
            self.delivered_at = delivered_at
        self.save(update_fields=["status", "raw_provider_status", "error_code", "delivered_at"])

    def __str__(self):
        return f"{self.direction} to {self.to_user} [{self.status}]"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["direction"]),
            models.Index(fields=["twilio_sid"]),
            models.Index(fields=["created_at"]),
        ]


# Optional: include AuditLog so admin/services can work without conditional guards
class AuditLog(models.Model):
    class Action(models.TextChoices):
        SEND_SMS = "SEND_SMS", "Send SMS"
        STATUS_UPDATE = "STATUS_UPDATE", "Status Update"
        INBOUND_RECEIVED = "INBOUND_RECEIVED", "Inbound Received"

    action = models.CharField(max_length=32, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_actions",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_targets",
    )
    message = models.ForeignKey(
        Message,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    campaign = models.ForeignKey(
        Campaign,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )

    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.actor or "system"
        return f"[{self.action}] by {who} at {timezone.localtime(self.created_at).isoformat()}"
