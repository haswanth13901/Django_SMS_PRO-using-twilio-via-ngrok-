# accounts/views.py
from __future__ import annotations

from django.utils import timezone
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Profile
from .serializer import ProfileSerializer


class IsStaffOrOwner(permissions.BasePermission):
    """
    - Staff: full access.
    - Non-staff: can only retrieve/update their own profile.
    - Create (POST): staff only (profiles are auto-created on user creation).
    """

    def has_permission(self, request, view):
        if request.method == "POST":
            return request.user and request.user.is_staff
        # must be authenticated for all other actions
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj: Profile):
        if request.user.is_staff:
            return True
        # Only the owner can view/update their own profile
        return obj.user_id == request.user.id


class ProfileViewSet(viewsets.ModelViewSet):
    """
    Profiles API:
      - Staff:
          * list/search all profiles
          * retrieve/update any profile
          * create profiles (rare; usually created by signal)
          * verify profiles via action
      - Regular users:
          * retrieve/update ONLY their own profile
          * convenient /me endpoint for self profile
    """
    serializer_class = ProfileSerializer
    permission_classes = [IsStaffOrOwner]

    # Enable search & ordering in the admin/manager list view
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["user__username", "user__email", "phone_number", "timezone_name"]
    ordering_fields = ["created_at", "updated_at", "verified_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Profile.objects.select_related("user")
        user = self.request.user
        if user.is_staff:
            return qs
        # Non-staff: only their own profile
        return qs.filter(user=user)

    def perform_create(self, serializer):
        """
        Staff can create a profile and set user via serializer's user_id.
        (For normal flow, profiles are created by the post_save signal.)
        """
        serializer.save()

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        """
        GET  /profiles/me/     -> your profile details
        PATCH /profiles/me/    -> partial update of your profile
        """
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"detail": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.method.lower() == "get":
            data = self.get_serializer(profile).data
            return Response(data)

        # PATCH
        serializer = self.get_serializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAdminUser],
        url_path="verify",
    )
    def verify(self, request, pk=None):
        """
        Staff-only: mark a profile's phone as verified (sets verified_at=now).
        POST /profiles/{id}/verify/
        """
        profile = self.get_object()
        profile.verified_at = timezone.now()
        profile.save(update_fields=["verified_at"])
        return Response(self.get_serializer(profile).data, status=status.HTTP_200_OK)
