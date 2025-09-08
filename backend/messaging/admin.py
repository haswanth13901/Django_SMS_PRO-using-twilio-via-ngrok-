# messaging/admin.py
from django.contrib import admin

# Required model (if this is missing, your app isn't usable anyway)
from .models import Message

# Optional models — import safely
try:
    from .models import AuditLog
except Exception:
    AuditLog = None

try:
    from .models import Campaign
except Exception:
    Campaign = None


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "to_user", "direction", "status", "twilio_sid", "created_at")
    list_filter = ("direction", "status", "created_at")
    search_fields = ("to_user__username", "to_user__email", "twilio_sid", "body")


# Register AuditLog only if the model exists
if AuditLog:
    @admin.register(AuditLog)
    class AuditLogAdmin(admin.ModelAdmin):
        # safe defaults
        list_display = ("action", "actor", "target_user", "message", "created_at")
        list_filter = ("action", "created_at")
        search_fields = ("actor__username", "target_user__username", "message__twilio_sid")

    # If AuditLog has a 'campaign' FK, extend the columns/search at runtime
    try:
        if hasattr(AuditLog, "campaign"):
            AuditLogAdmin.list_display = ("action", "actor", "target_user", "message", "campaign", "created_at")
            AuditLogAdmin.search_fields = (
                "actor__username", "target_user__username", "message__twilio_sid", "campaign__name"
            )
    except Exception:
        pass


# Register Campaign only if the model exists
if Campaign:
    @admin.register(Campaign)
    class CampaignAdmin(admin.ModelAdmin):
        list_display = (
            "name", "created_by", "is_active", "scheduled_for",
            "total_sent", "total_delivered", "total_failed",
        )
        list_filter = ("is_active",)
        search_fields = ("name",)
        filter_horizontal = ("targets",)
