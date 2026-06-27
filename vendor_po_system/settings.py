import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

load_dotenv(BASE_DIR / '.env')

# ---------------------------------------------------------------------------
# Secrets & environment  (set these in your OS environment or a .env loader)
# ---------------------------------------------------------------------------
DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"

_secret = os.environ.get("DJANGO_SECRET_KEY", "")
if not _secret:
    if DEBUG:
        _secret = "django-insecure-dev-only-not-for-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable is not set.")
SECRET_KEY = _secret



ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost 127.0.0.1").split()

CSRF_TRUSTED_ORIGINS = [
    "https://jeyarama.com",
    "https://*.jeyarama.com",
]





# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "widget_tweaks",
    "po_sheet.apps.PoSheetConfig",
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

ROOT_URLCONF = "vendor_po_system.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "vendor_po_system.wsgi.application"

# ---------------------------------------------------------------------------
# Databases
# CONN_MAX_AGE keeps connections alive across requests (connection pooling).
# 300 s is a safe default; MySQL wait_timeout must be higher (default 28800 s).
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DB"),
        "USER": os.environ.get("MYSQL_USER"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD"),
        "HOST": os.environ.get("MYSQL_HOST", "localhost"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 300,
        "OPTIONS": {
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    },
    "mssql": {
        "ENGINE": "mssql",
        "NAME": os.environ.get("MSSQL_DB"),
        "USER": os.environ.get("MSSQL_USER"),
        "PASSWORD": os.environ.get("MSSQL_PASSWORD"),
        "HOST": os.environ.get("MSSQL_HOST"),
        "PORT": os.environ.get("MSSQL_PORT", "1433"),
        "OPTIONS": {
            "driver": "ODBC Driver 17 for SQL Server",
            "connection_timeout": 10,
        },
    },
}

DATABASE_ROUTERS = ["vendor_po_system.db_routers.MSSQLRouter"]

# ---------------------------------------------------------------------------
# In-process cache (single-server deployments)
# Switch to Redis for multi-process / multi-server deployments:
#   CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
#                         "LOCATION": "redis://127.0.0.1:6379/1"}}
# ---------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "vendor-po-cache",
    }
}

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic target for production

# ---------------------------------------------------------------------------
# Auth redirects
# ---------------------------------------------------------------------------
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"


# ---------------------------------------------------------------------------
# Session security
# ---------------------------------------------------------------------------
SESSION_COOKIE_AGE = 28800          # 8 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ---------------------------------------------------------------------------
# Security hardening (enable when serving over HTTPS)
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Logging (Removed custom file logging config)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Default primary key
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
