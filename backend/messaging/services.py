# messaging/services.py
from django.conf import settings
from django.utils import timezone

try:
    from twilio.rest import Client
except Exception:
    Client = None  # allows migrations/tests to run without twilio installed


def send_sms(to_user, body, campaign=None):
    # Lazy imports avoid migration-time import errors
    from .models import Message
    try:
        from .models import AuditLog
    except Exception:
        AuditLog = None

    # Create the message row first
    msg = Message.objects.create(
        to_user=to_user,
        direction=Message.Direction.OUTBOUND,
        body=body,
        status=Message.Status.QUEUED,
        campaign=campaign,
    )

    try:
        if Client is None:
            raise RuntimeError("Twilio client unavailable")

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        kwargs = {
            "to": to_user.profile.phone_number,
            "body": body,
        }
        # Prefer Messaging Service SID; fallback to from_ number
        if getattr(settings, "TWILIO_MESSAGING_SERVICE_SID", ""):
            kwargs["messaging_service_sid"] = settings.TWILIO_MESSAGING_SERVICE_SID
        else:
            kwargs["from_"] = settings.TWILIO_FROM_NUMBER

        if getattr(settings, "TWILIO_STATUS_CALLBACK_URL", ""):
            kwargs["status_callback"] = settings.TWILIO_STATUS_CALLBACK_URL

        tw = client.messages.create(**kwargs)

        msg.twilio_sid = tw.sid
        msg.status = Message.Status.SENT
        msg.raw_provider_status = "sent"
        msg.save(update_fields=["twilio_sid", "status", "raw_provider_status"])

        if AuditLog:
            AuditLog.objects.create(
                actor=None,
                action=getattr(AuditLog.Action, "SEND_SMS", "SEND_SMS"),
                target_user=to_user,
                message=msg,
            )
        return msg

    except Exception as e:
        msg.status = Message.Status.FAILED
        msg.error_code = getattr(e, "code", "") or type(e).__name__
        msg.save(update_fields=["status", "error_code"])
        raise
