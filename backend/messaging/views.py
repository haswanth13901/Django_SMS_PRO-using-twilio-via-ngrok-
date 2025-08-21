# backend/messaging/views.py
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt

from rest_framework import mixins, viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Profile
from .models import Message

# Support either serializer.py or serializers.py
try:
    from .serializer import MessageSerializer, SendMessageSerializer
except ModuleNotFoundError:  # if the file is serializers.py
    from .serializers import MessageSerializer, SendMessageSerializer  # type: ignore

from .services import send_sms


# ---------------- Permissions (managers/staff only) ----------------
class IsManager(permissions.BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )


# ---------------- DRF API: list/create messages ----------------
class MessageViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Message.objects.select_related("to_user").order_by("-created_at")
    permission_classes = [IsManager]

    def get_serializer_class(self):
        return SendMessageSerializer if self.action == "create" else MessageSerializer


# ---------------- DRF API: lightweight homepage stats ----------------
class StatsView(APIView):
    permission_classes = [IsManager]

    def get(self, request):
        today = timezone.localdate()
        return Response(
            {
                "opted_in_users": Profile.objects.filter(sms_opt_in=True).count(),
                "messages_sent_today": Message.objects.filter(
                    direction=Message.Direction.OUTBOUND, created_at__date=today
                ).count(),
                "delivered_today": Message.objects.filter(
                    status=Message.Status.DELIVERED, delivered_at__date=today
                ).count(),
            }
        )


# ---------------- Helper: normalize and apply Twilio status ----------------
def _apply_twilio_status(message_obj: Message, status: str | None, error_code: str | None):
    """
    Map Twilio MessageStatus into our Message.Status and persist.
    If the model doesn't define mark_status(...), fall back to direct field updates.
    """
    try:
        def _fallback_update(new_status, **extra):
            message_obj.status = new_status
            if "raw" in extra:
                message_obj.raw_provider_status = extra["raw"]
            if "error_code" in extra:
                message_obj.error_code = extra["error_code"]
            if "delivered_at" in extra:
                message_obj.delivered_at = extra["delivered_at"]
            message_obj.save()

        updater = getattr(message_obj, "mark_status", None) or _fallback_update

        if status == "delivered":
            updater(
                Message.Status.DELIVERED,
                raw=status,
                delivered_at=timezone.now(),
            )
        elif status in {"failed", "undelivered"}:
            updater(Message.Status.FAILED, raw=status, error_code=error_code)
        elif status in {"sent", "queued", "accepted"}:
            updater(Message.Status.SENT, raw=status)
        else:
            # Unknown/other status: record raw without changing main status
            message_obj.raw_provider_status = status or "unknown"
            message_obj.save(update_fields=["raw_provider_status"])
    except Exception:
        # Webhooks should never crash
        pass


# ---------------- Simple test sender (POST only) ----------------
@csrf_exempt
def send_test_sms(request):
    """
    Sends a test SMS to user 'alice'. Must be POST to avoid accidental sends.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    User = get_user_model()
    try:
        u = User.objects.get(username="alice")  # change to your real user
    except User.DoesNotExist:
        return JsonResponse({"error": "User 'alice' not found"}, status=404)

    send_sms(u, "Hello Alice! Your appointment is tomorrow at 3pm.")
    return JsonResponse({"ok": True})


# ---------------- Twilio inbound SMS webhook ----------------
@csrf_exempt
def twilio_inbound_webhook(request):
    """
    GET  -> simple health check (for browser)
    POST -> Twilio posts inbound SMS here (application/x-www-form-urlencoded)
    """
    if request.method == "GET":
        return HttpResponse(
            "Twilio SMS webhook is up. Send a POST here.",
            content_type="text/plain",
            status=200,
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    # Typical inbound fields from Twilio
    from_number = request.POST.get("From")      # e.g., "+15551234567"
    # to_number   = request.POST.get("To")      # your Twilio number (unused here)
    body        = request.POST.get("Body", "")
    sid         = request.POST.get("MessageSid")  # optional but useful

    # Try to map the sender to a known user via Profile.phone_number
    try:
        profile = Profile.objects.select_related("user").get(phone_number=from_number)
        user = profile.user
        Message.objects.create(
            to_user=user,
            direction=Message.Direction.INBOUND,
            body=body,
            twilio_sid=sid or "",
            status=Message.Status.DELIVERED,   # reached your server
            delivered_at=timezone.now(),
        )
    except Profile.DoesNotExist:
        pass  # Unknown sender; optionally log

    return HttpResponse("OK", status=200)


# ---------------- Twilio status webhooks (POST only) ----------------
@csrf_exempt
def twilio_status_webhook(request):
    """
    Twilio status callback endpoint.
    Updates Message status based on MessageSid + MessageStatus.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    sid = request.POST.get("MessageSid")
    status = request.POST.get("MessageStatus")  # delivered | failed | sent | queued | ...
    error_code = request.POST.get("ErrorCode")

    if not sid:
        return HttpResponse("missing sid", status=400)

    try:
        m = Message.objects.get(twilio_sid=sid)
    except Message.DoesNotExist:
        return HttpResponse("OK", status=200)

    _apply_twilio_status(m, status, error_code)
    return HttpResponse("OK", status=200)


# ---------------- Alternate status webhook (lazy-import model) ----------------
@csrf_exempt
def twilio_status_callback(request):
    """
    Same as twilio_status_webhook but lazy-imports the model.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    sid = request.POST.get("MessageSid")
    status = request.POST.get("MessageStatus")
    error_code = request.POST.get("ErrorCode")

    if not sid:
        return HttpResponse("missing sid", status=400)

    try:
        from .models import Message as _Message
        m = _Message.objects.get(twilio_sid=sid)
    except Exception:
        return HttpResponse("OK", status=200)

    _apply_twilio_status(m, status, error_code)
    return HttpResponse("OK", status=200)


twilio_inbound_sms = twilio_inbound_webhook


# ---------------- UI (optional) ----------------
class ManagerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff


class HomePageView(ManagerRequiredMixin, TemplateView):
    template_name = "messaging/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Message.objects.select_related("to_user").order_by("-created_at")
        today = timezone.localdate()
        ctx["messages"] = qs[:50]
        ctx["counts"] = {
            "opted_in_users": Profile.objects.filter(sms_opt_in=True).count(),
            "messages_sent_today": qs.filter(
                direction=Message.Direction.OUTBOUND, created_at__date=today
            ).count(),
            "delivered_today": qs.filter(
                status=Message.Status.DELIVERED, delivered_at__date=today
            ).count(),
        }
        return ctx
