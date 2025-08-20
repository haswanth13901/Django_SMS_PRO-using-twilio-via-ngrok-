# accounts/serializers.py
from __future__ import annotations
import re
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Profile

User = get_user_model()

# Require '+' and 8–15 digits total (E.164 max length 15)
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")

class UserPublicSerializer(serializers.ModelSerializer):
    """Lightweight user details for embedding in a Profile response."""
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email", "is_active", "date_joined")
        read_only_fields = fields  # expose but don't let profile updates change user core fields

class ProfileSerializer(serializers.ModelSerializer):
    # Read-only nested user info for GETs
    user = UserPublicSerializer(read_only=True)
    # Write-only foreign key for POST/PATCH when assigning a user
    user_id = serializers.PrimaryKeyRelatedField(
        source="user", queryset=User.objects.all(), write_only=True, required=False
    )

    class Meta:
        model = Profile
        fields = (
            "id",
            "user",         # nested (read-only)
            "user_id",      # FK setter (write-only)
            "phone_number",
            "sms_opt_in",
            "timezone_name",
            "verified_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "verified_at", "created_at", "updated_at")

    # --------- Field-level validation ----------
    def validate_phone_number(self, value: str) -> str:
        # Allow blank because model has blank=True
        if value == "":
            return value
        if not E164_RE.match(value or ""):
            raise serializers.ValidationError("Use E.164 format, e.g., +15551234567")
        return value

    def validate_timezone_name(self, value: str) -> str:
        # Validate against IANA names using stdlib zoneinfo
        try:
            ZoneInfo(value)
        except Exception:
            raise serializers.ValidationError("Invalid IANA timezone name")
        return value

    # --------- Object-level validation ----------
    def validate(self, attrs):
        sms_opt_in = attrs.get("sms_opt_in", getattr(self.instance, "sms_opt_in", False))
        phone = attrs.get("phone_number", getattr(self.instance, "phone_number", ""))
        if sms_opt_in and not phone:
            raise serializers.ValidationError(
                {"sms_opt_in": "A phone_number is required to opt in to SMS."}
            )
        return attrs

    # --------- Create / Update ----------
    def create(self, validated_data):
        """
        Admins may create a Profile explicitly (signal also auto-creates on user creation).
        If a profile already exists for the user, update it instead of crashing.
        """
        user = validated_data.pop("user", None)
        if user is None:
            raise serializers.ValidationError({"user_id": "This field is required."})

        profile, created = Profile.objects.get_or_create(user=user, defaults=validated_data)
        if not created:
            for k, v in validated_data.items():
                setattr(profile, k, v)
            profile.save()
        return profile

    def update(self, instance: Profile, validated_data):
        # Normal partial/full update
        for k, v in validated_data.items():
            # prevent switching user on existing profile via update
            if k == "user":
                continue
            setattr(instance, k, v)
        instance.save()
        return instance
