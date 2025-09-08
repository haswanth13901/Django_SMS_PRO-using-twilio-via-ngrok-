from django.conf import settings
from django.db import models
from django.utils import timezone

class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    phone_number = models.CharField(
        max_length=32,
        blank=True,
        help_text="E.164 preferred (e.g., +15551234567)"
    )
    sms_opt_in = models.BooleanField(default=False)
    timezone_name = models.CharField(
        max_length=64,
        default="UTC",
        help_text="IANA timezone name (e.g., America/Chicago)"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    # Optional convenience fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def mark_verified(self):
        self.verified_at = timezone.now()
        self.save(update_fields=["verified_at"])

    def __str__(self):
        return f"Profile<{self.user.username}>"

    class Meta:
        indexes = [
            models.Index(fields=["sms_opt_in"]),
            models.Index(fields=["phone_number"]),
        ]
