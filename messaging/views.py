# messaging/views.py
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import render


from rest_framework import mixins, viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView


from accounts.models import Profile
from .models import Message
from .serializer import MessageSerializer, SendMessageSerializer
from .services import send_sms


# ---------------- Permissions (managers/staff only) ----------------
class IsManager(permissions.BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_staff  # or replace with group-based logic
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
    Keeps unknown statuses in raw_provider_status without flipping primary status.
    """
    try:
        if status == "delivered":
            message_obj.mark_status(
                Message.Status.DELIVERED, raw=status, delivered_at=timezone.now()
            )
        elif status in {"failed", "undelivered"}:
            message_obj.mark_status(Message.Status.FAILED, raw=status, error_code=error_code)
        elif status in {"sent", "queued", "accepted"}:
            message_obj.mark_status(Message.Status.SENT, raw=status)
        else:
            # Unknown/other status: record raw without changing the main status
            message_obj.raw_provider_status = status or "unknown"
            message_obj.save(update_fields=["raw_provider_status"])
    except Exception:
        # Webhooks should be permissive—never break request handling.
        pass


# ---------------- Simple test sender (POST) ----------------

@csrf_exempt
def send_test_sms(request):
    """
    Sends a test SMS to user 'alice'. Call this via POST to avoid sending on import.
    """
    User = get_user_model()
    try:
        u = User.objects.get(username="alice")  # change to your real user
    except User.DoesNotExist:
        return JsonResponse({"error": "User 'alice' not found"}, status=404)

    send_sms(u, "Hello Alice! Your appointment is tomorrow at 3pm.")
    return JsonResponse({"ok": True})


# ---------------- Twilio inbound SMS webhook (minimal/no DB) ----------------
@csrf_exempt
def twilio_inbound_webhook(request):

    # Twilio sends POST (form-encoded). Reject GET.
    if request.method != "GET":
        return HttpResponseNotAllowed("Twilio inbound SMS webhook - send a POST here.", status=200)

    # Webhook behavior (POST only)
    if request.method != "POST":
        # NOTE: HttpResponseNotAllowed expects a list of allowed methods
        return HttpResponseNotAllowed(["POST"])
    
    # Typical inbound fields from Twilio
    from_number = request.POST.get("From")      # e.g., "+15551234567"
    to_number   = request.POST.get("To")        # your Twilio number
    body        = request.POST.get("Body", "")
    sid         = request.POST.get("MessageSid")  # optional but useful

    # Try to map the sender to a known user via Profile.phone_number
    try:
        profile = Profile.objects.select_related("user").get(phone_number=from_number)
        user = profile.user
        # Store inbound message
        Message.objects.create(
            to_user=user,
            direction=Message.Direction.INBOUND,
            body=body,
            twilio_sid=sid or "",
            status=Message.Status.DELIVERED,   # inbound arrived at your server
            delivered_at=timezone.now(),
        )
    except Profile.DoesNotExist:
        # If you want to track unknown senders, you could log them here.
        pass

    # Respond 200 so Twilio is happy (no auto-reply here)
    return HttpResponse("OK")

# ---------------- Twilio status webhook (uses imported Message) ----------------
@csrf_exempt

def twilio_status_webhook(request):
    """
    Twilio status callback endpoint.
    Updates Message status based on MessageSid + MessageStatus.
    """
    sid = request.POST.get("MessageSid")
    status = request.POST.get("MessageStatus")  # delivered | failed | sent | queued | ...
    error_code = request.POST.get("ErrorCode")

    if not sid:
        return HttpResponse("missing sid", status=400)

    try:
        m = Message.objects.get(twilio_sid=sid)
    except Message.DoesNotExist:
        # Ignore unknown SIDs (or log if you prefer)
        return HttpResponse("OK")

    _apply_twilio_status(m, status, error_code)
    return HttpResponse("OK")


# ---------------- Alternate status webhook (lazy-import model) ----------------
@csrf_exempt

def twilio_status_callback(request):
    """
    Twilio status callback with lazy model import so migrations/startup never fail
    if models aren't ready. Functionally equivalent to twilio_status_webhook.
    """
    sid = request.POST.get("MessageSid")
    status = request.POST.get("MessageStatus")
    error_code = request.POST.get("ErrorCode")

    if not sid:
        return HttpResponse("missing sid", status=400)

    try:
        # Lazy import to avoid issues during makemigrations/check
        from .models import Message as _Message
        m = _Message.objects.get(twilio_sid=sid)
    except Exception:
        return HttpResponse("OK")

    _apply_twilio_status(m, status, error_code)
    return HttpResponse("OK")

twilio_inbound_sms = twilio_inbound_webhook

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



