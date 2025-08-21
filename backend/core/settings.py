# backend/core/settings.py
from pathlib import Path
import os
from urllib.parse import urlparse

# ---------------------------------------------------------------------
# Paths
#   - This file lives at backend/core/settings.py
#   - PROJECT_ROOT points to .../django-twilio-sms  (where manage.py/.env live)
#   - BACKEND_DIR points to .../django-twilio-sms/backend
# ---------------------------------------------------------------------
BACKEND_DIR   = Path(__file__).resolve().parents[1]
PROJECT_ROOT  = Path(__file__).resolve().parents[2]
BASE_DIR = BACKEND_DIR  # keep BASE_DIR for app-local paths, but use PROJECT_ROOT for repo-level files

# ---------------------------------------------------------------------
# Basic
# ---------------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-do-not-use-in-prod")
DEBUG = os.environ.get("DJANGO_DEBUG", "True").strip().lower() in {"1", "true", "yes", "on"}

_default_hosts = ["127.0.0.1", "localhost", ".ngrok.io", ".ngrok-free.app"]
_env_hosts = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = list(dict.fromkeys(_env_hosts + _default_hosts))  # de-dupe while preserving order

# For session/login forms and admin when tunneling via HTTPS
CSRF_TRUSTED_ORIGINS = [
    "https://*.ngrok.io",
    "https://*.ngrok-free.app",
]

# ---------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts.apps.AccountsConfig",
    "messaging",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Search in both repo-level and backend-level "templates" folders
        "DIRS": [PROJECT_ROOT / "templates", BACKEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "core.wsgi.application"

# ---------------------------------------------------------------------
# Database
#   Priority:
#     1) POSTGRES_* envs
#     2) DATABASE_URL
#     3) sqlite at PROJECT_ROOT/db.sqlite3
# ---------------------------------------------------------------------
dsn = os.environ.get("DATABASE_URL")  # e.g. postgresql://postgres:pwd@127.0.0.1:5432/twilio_sms

pg_db   = os.environ.get("POSTGRES_DB")
pg_user = os.environ.get("POSTGRES_USER")
pg_pass = os.environ.get("POSTGRES_PASSWORD")
pg_host = os.environ.get("POSTGRES_HOST")
pg_port = os.environ.get("POSTGRES_PORT")
conn_age = int(os.environ.get("CONN_MAX_AGE", "60"))

if any([pg_db, pg_user, pg_pass, pg_host, pg_port]):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": pg_db or "twilio_sms",
            "USER": pg_user or "postgres",
            "PASSWORD": pg_pass or "",   # don't hardcode secrets
            "HOST": pg_host or "127.0.0.1",
            "PORT": int(pg_port or "5432"),
            "CONN_MAX_AGE": conn_age,
        }
    }
elif dsn:
    u = urlparse(dsn)
    if u.scheme.startswith("postgres"):
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": (u.path or "").lstrip("/"),
                "USER": u.username or "",
                "PASSWORD": u.password or "",
                "HOST": u.hostname or "127.0.0.1",
                "PORT": int(u.port or 5432),
                "CONN_MAX_AGE": conn_age,
            }
        }
    elif u.scheme in {"sqlite", "sqlite3"}:
        name = (u.path or (PROJECT_ROOT / "db.sqlite3"))
        DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": name}}
    else:
        raise RuntimeError(f"Unsupported DATABASE_URL scheme: {u.scheme}")
else:
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": PROJECT_ROOT / "db.sqlite3"}
    }

# ---------------------------------------------------------------------
# I18N / Static
# ---------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = PROJECT_ROOT / "staticfiles"   # for collectstatic (optional)
# STATICFILES_DIRS = [PROJECT_ROOT / "frontend" / "static"]  # if you keep extra static assets

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------
# Twilio
#   If you set PUBLIC_BASE_URL (your ngrok https URL), we auto-build webhooks.
#   You can still override with explicit TWILIO_* envs.
# ---------------------------------------------------------------------
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

TWILIO_STATUS_CALLBACK_URL = os.environ.get(
    "TWILIO_STATUS_CALLBACK_URL",
    f"{PUBLIC_BASE_URL}/webhooks/twilio/status/" if PUBLIC_BASE_URL else "",
)
TWILIO_INBOUND_URL = os.environ.get(
    "TWILIO_INBOUND_URL",
    f"{PUBLIC_BASE_URL}/webhooks/twilio/sms/" if PUBLIC_BASE_URL else "",
)
