# backend/messaging/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    HomePageView,
    MessageViewSet,
    StatsView,
    twilio_inbound_webhook,
    twilio_status_webhook,
    twilio_status_callback,  # optional alt status endpoint
    send_test_sms,
)

app_name = "messaging"

router = DefaultRouter()
router.register(r"messages", MessageViewSet, basename="messages")

urlpatterns = [
    # UI
    path("", HomePageView.as_view(), name="home"),

    # Webhooks
    path("webhooks/twilio/sms/", twilio_inbound_webhook, name="twilio-sms"),
    path("webhooks/twilio/status/", twilio_status_webhook, name="twilio-status"),
    path("webhooks/twilio/status-alt/", twilio_status_callback, name="twilio-status-alt"),

    # Test helper
    path("send-test/", send_test_sms, name="send-test"),

    # API
    path("api/stats/", StatsView.as_view(), name="stats"),
    path("api/", include(router.urls)),  # /api/messages/, /api/messages/<id>/
]
