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
from .services import send_sms

# Support either serializer.py or serializers.py
try:
    from .serializer import MessageSerializer, SendMessageSerializer
except ModuleNotFoundError:
    from .serializers import MessageSerializer, SendMessageSerializer  # type: ignore


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
        return Response(Message.objects.stats_for_date(today))


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
        return HttpResponse("Twilio SMS webhook is up. Send a POST here.", content_type="text/plain", status=200)

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    from_number = request.POST.get("From")
    body = request.POST.get("Body", "")
    sid = request.POST.get("MessageSid")

    Message.objects.handle_inbound(from_number=from_number, body=body, sid=sid)
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

    Message.objects.handle_status_callback(sid=sid, status=status, error_code=error_code)
    return HttpResponse("OK", status=200)


# ---------------- Alternate status webhook (same domain call) ----------------
@csrf_exempt
def twilio_status_callback(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    sid = request.POST.get("MessageSid")
    status = request.POST.get("MessageStatus")
    error_code = request.POST.get("ErrorCode")

    if not sid:
        return HttpResponse("missing sid", status=400)

    Message.objects.handle_status_callback(sid=sid, status=status, error_code=error_code)
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
        ctx["counts"] = Message.objects.stats_for_date(today)
        return ctx
