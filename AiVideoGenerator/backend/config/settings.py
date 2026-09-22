import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BASE_DIR.parent
load_dotenv(REPOSITORY_ROOT / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"true", "1", "yes"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only-replace-before-deployment")
if not DEBUG and (len(SECRET_KEY) < 50 or SECRET_KEY.startswith("local-development")):
    raise ImproperlyConfigured("Set a unique DJANGO_SECRET_KEY of at least 50 characters.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "studio",
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
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
RUNTIME_ROOT = BASE_DIR / ".runtime"
RUNTIME_ROOT.mkdir(exist_ok=True)
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")
if DB_BACKEND == "oracle":
    required = ["ORACLE_DB_DSN", "ORACLE_DB_USER", "ORACLE_DB_PASSWORD"]
    if any(not os.getenv(key) for key in required):
        raise ImproperlyConfigured("Set ORACLE_DB_DSN, ORACLE_DB_USER and ORACLE_DB_PASSWORD.")
    options = {}
    for key, name in {
        "config_dir": "ORACLE_CONFIG_DIR",
        "wallet_location": "ORACLE_WALLET_LOCATION",
        "wallet_password": "ORACLE_WALLET_PASSWORD",
    }.items():
        if os.getenv(name):
            options[key] = os.environ[name]
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.oracle",
            "NAME": os.environ["ORACLE_DB_DSN"],
            "USER": os.environ["ORACLE_DB_USER"],
            "PASSWORD": os.environ["ORACLE_DB_PASSWORD"],
            "OPTIONS": options,
        }
    }
elif DB_BACKEND == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": RUNTIME_ROOT / "development.sqlite3",
            "OPTIONS": {"timeout": 30},
        }
    }
else:
    raise ImproperlyConfigured("DB_BACKEND must be sqlite or oracle.")

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "studio:home"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 1
PRIVATE_STORAGE_ROOT = RUNTIME_ROOT / "private"
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
if STORAGE_BACKEND not in {"local", "oci"}:
    raise ImproperlyConfigured("STORAGE_BACKEND must be local or oci.")
COMFY_URL = os.getenv("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_WORKFLOW_PATH = BASE_DIR / os.getenv("COMFY_WORKFLOW_PATH", "workflows/local.json")
COMFY_IMAGE_NODE_ID = os.getenv("COMFY_IMAGE_NODE_ID", "")
COMFY_IMAGE_INPUT = os.getenv("COMFY_IMAGE_INPUT", "image")
COMFY_PROMPT_NODE_ID = os.getenv("COMFY_PROMPT_NODE_ID", "")
COMFY_PROMPT_INPUT = os.getenv("COMFY_PROMPT_INPUT", "text")
COMFY_OUTPUT_NODE_ID = os.getenv("COMFY_OUTPUT_NODE_ID", "")
COMFY_VIDEO_OUTPUT_KEY = os.getenv("COMFY_VIDEO_OUTPUT_KEY", "")
COMFY_POLL_SECONDS = max(1, int(os.getenv("COMFY_POLL_SECONDS", "3")))
COMFY_JOB_TIMEOUT_SECONDS = int(os.getenv("COMFY_JOB_TIMEOUT_SECONDS", "1800"))
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_MB", "10")) * 1024 * 1024
MAX_VIDEO_BYTES = int(os.getenv("MAX_VIDEO_MB", "512")) * 1024 * 1024
