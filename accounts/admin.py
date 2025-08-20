from django.contrib import admin
from .models import Profile

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone_number", "sms_opt_in", "timezone_name", "verified_at")
    list_filter = ("sms_opt_in", "timezone_name")
    search_fields = ("user__username", "user__email", "phone_number")
