# messaging/urls.py
from django.urls import path
from .views import HomePageView, twilio_inbound_webhook, twilio_status_webhook, send_test_sms
from .views import twilio_inbound_webhook, twilio_status_webhook, send_test_sms

urlpatterns = [
    path("", HomePageView.as_view(), name="home"),                 # <— homepage
    path("webhooks/twilio/sms/", twilio_inbound_webhook, name="twilio-inbound"),
    path("webhooks/twilio/status/", twilio_status_webhook, name="twilio-status"),
    path("send-test/", send_test_sms, name="send-test"),
]
