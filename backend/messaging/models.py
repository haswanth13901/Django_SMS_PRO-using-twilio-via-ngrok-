# backend/messaging/models.py
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


# ---------------- Custom QuerySet / Manager to host domain logic ----------------
class MessageQuerySet(models.QuerySet):
    def outbound(self):
        return self.filter(direction=self.model.Direction.OUTBOUND)

    def delivered(self):
        return self.filter(status=self.model.Status.DELIVERED)


class MessageManager(models.Manager.from_queryset(MessageQuerySet)):
    def handle_inbound(self, from_number: str | None, body: str, sid: str | None = None):
        """
        Domain logic for inbound SMS:
        - Map 'From' phone number to a user via accounts.Profile.phone_number
        - Create an INBOUND Message and mark delivered_at
        Returns the created Message or None if sender unknown.
        """
        if not from_number:
            return None

        # Lazy import to avoid circulars
        from accounts.models import Profile

        try:
            profile = Profile.objects.select_related("user").get(phone_number=from_number)
        except Profile.DoesNotExist:
            return None

        return self.create(
            to_user=profile.user,
            direction=self.model.Direction.INBOUND,
            body=body or "",
            twilio_sid=sid or "",
            status=self.model.Status.DELIVERED,
            delivered_at=timezone.now(),
        )

    def handle_status_callback(self, sid: str | None, status: str | None, error_code: str | None = None):
        """
        Domain logic for Twilio status webhook.
        Finds message by SID and applies provider status mapping.
        Returns the Message or None if not found / invalid input.
        """
        if not sid:
            return None
        try:
            m = self.get(twilio_sid=sid)
        except self.model.DoesNotExist:
            return None
        m.set_status_from_twilio(status=status, error_code=error_code)
        return m

    def stats_for_date(self, date):
        """
        Aggregate counts used by StatsView/HomePageView.
        """
        # Lazy import to avoid coupling
        from accounts.models import Profile

        return {
            "opted_in_users": Profile.objects.filter(sms_opt_in=True).count(),
            "messages_sent_today": self.filter(
                direction=self.model.Direction.OUTBOUND, created_at__date=date
            ).count(),
            "delivered_today": self.filter(
                status=self.model.Status.DELIVERED, delivered_at__date=date
            ).count(),
        }


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
        "Campaign",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    objects = MessageManager()

    # ---------- Domain helpers ----------
    def mark_status(self, status, raw=None, error_code=None, delivered_at=None):
        self.status = status
        if raw is not None:
            self.raw_provider_status = raw
        if error_code is not None:
            self.error_code = error_code
        if delivered_at is not None:
            self.delivered_at = delivered_at
        self.save(update_fields=["status", "raw_provider_status", "error_code", "delivered_at"])

    def set_status_from_twilio(self, status: str | None, error_code: str | None = None):
        """
        Maps Twilio MessageStatus -> internal Message.Status and persists.
        Safe to call from webhooks; never raises.
        """
        try:
            if status == "delivered":
                self.mark_status(
                    self.Status.DELIVERED,
                    raw=status,
                    delivered_at=timezone.now(),
                )
            elif status in {"failed", "undelivered"}:
                self.mark_status(self.Status.FAILED, raw=status, error_code=error_code)
            elif status in {"sent", "queued", "accepted"}:
                self.mark_status(self.Status.SENT, raw=status)
            else:
                # Unknown/other status: record raw without changing main status
                self.raw_provider_status = status or "unknown"
                self.save(update_fields=["raw_provider_status"])
        except Exception:
            # Webhooks should never crash
            pass

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
