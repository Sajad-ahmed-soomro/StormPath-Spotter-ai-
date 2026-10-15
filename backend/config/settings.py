"""Django settings for the weather-aware truck routing service.

Everything deploy-specific is read from environment variables so the same
settings work locally, in Docker and on a PaaS.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Local development reads backend/.env (see .env.example). In production the
# host's environment variables take precedence over the file.
load_dotenv(BASE_DIR / ".env", override=False)


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(
            f"Missing environment variable {name}. Copy backend/.env.example to backend/.env."
        )
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


REPO_DIR = BASE_DIR.parent
# Built React app (``npm run build``). Served by WhiteNoise in production.
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", REPO_DIR / "frontend" / "dist"))

SECRET_KEY = env_required("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
def _hostname(value: str) -> str:
    """Accept pasted URLs too: 'https://app.example.com/' -> 'app.example.com'."""
    value = value.strip().strip("'\"")
    value = value.split("://", 1)[-1]
    return value.split("/", 1)[0]


ALLOWED_HOSTS = [_hostname(h) for h in env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")]
# Render sets this automatically for every web service.
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The app is stateless: no models, no sessions, no auth.
DATABASES = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-routing",
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Serve the Vite build output (index.html, /assets/*) from the site root.
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_MAX_AGE = 3600

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

# Origins of a separately hosted frontend (e.g. Vercel). Trailing slashes are
# dropped because an origin is scheme + host only.
CORS_ALLOWED_ORIGINS = [o.rstrip("/") for o in env_list("CORS_ALLOWED_ORIGINS")]
# Optional patterns, e.g. ^https://stormpath-.*\.vercel\.app$ for preview deploys.
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES")

USE_TZ = True
TIME_ZONE = "UTC"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# --- Third-party services -------------------------------------------------
# Endpoints and keys come from the environment only (see .env.example).
OSRM_URLS = env_list("OSRM_URLS")
if not OSRM_URLS:
    raise ImproperlyConfigured("Missing environment variable OSRM_URLS.")
OPEN_METEO_URL = env_required("OPEN_METEO_URL")
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
PHOTON_URL = env_required("PHOTON_URL")
BASEMAP_URL = env_required("BASEMAP_URL")
BASEMAP_LABELS_URL = os.environ.get("BASEMAP_LABELS_URL", "")
HTTP_USER_AGENT = env_required("HTTP_USER_AGENT")

# --- Domain tuning ----------------------------------------------------------
# OSRM's public server only offers a car profile. Heavy trucks are governed
# well below car speeds on interstates, so every road segment is slowed to at
# most this speed when computing ETAs.
TRUCK_MAX_SPEED_MPH = float(os.environ.get("TRUCK_MAX_SPEED_MPH", "65"))
ROUTE_CACHE_SECONDS = 30 * 60
WEATHER_CACHE_SECONDS = 20 * 60
