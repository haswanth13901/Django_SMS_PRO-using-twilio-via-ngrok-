from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),  # <— adds login/logout/password urls
    path("", include("messaging.urls")),  # webhooks & any messaging routes live here
]
