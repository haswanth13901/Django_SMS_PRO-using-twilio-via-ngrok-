from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Message
from .services import send_sms  # the helper that actually sends via Twilio

User = get_user_model()

class MessageSerializer(serializers.ModelSerializer):
    """Read-only representation for listing/history."""
    class Meta:
        model = Message
        fields = ["id", "to_user", "direction", "body", "status", "twilio_sid", "created_at"]
        read_only_fields = ["direction", "status", "twilio_sid", "created_at"]

class SendMessageSerializer(serializers.Serializer):
    """Write-only payload for composing a new SMS."""
    to_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    body = serializers.CharField(min_length=1, max_length=1000)

    def validate_to_user(self, user):
        # ensure phone + opt-in
        profile = getattr(user, "profile", None)
        if not profile or not profile.phone_number:
            raise serializers.ValidationError("User has no phone number.")
        if not profile.sms_opt_in:
            raise serializers.ValidationError("User is not opted in to SMS.")
        return user

    def create(self, validated):
        # call your Twilio wrapper; returns a Message instance
        msg = send_sms(validated["to_user"], validated["body"], campaign=None)
        return msg
