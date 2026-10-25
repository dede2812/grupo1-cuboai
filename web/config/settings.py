import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LANGUAGE_CODE = "es-sv"
FORMAT_MODULE_PATH = "config.formats"
TIME_ZONE = os.environ.get("REINO_TIME_ZONE", "America/El_Salvador")
USE_TZ = True


def _load_dotenv():
    """Carga mínima de variables desde web/.env (auditoría §9.2).

    Formato: CLAVE=valor por línea, comentarios con #. Las variables de
    entorno reales tienen precedencia. Copiar `.env.example` a `.env` sí
    funciona porque ESTE cargador lo lee al arrancar manage.py.
    """
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Entorno: dev (por defecto) | staging | prod. En prod/staging JAMÁS hay
# valores inseguros por defecto: faltan => error al arrancar (fail-closed).
REINO_ENV = os.environ.get("REINO_ENV", "dev")
_IS_PROD = REINO_ENV in ("staging", "prod")

# Contrato de entorno UNIFICADO (F01): los nombres canónicos son DJANGO_*;
# se aceptan los alias SECRET_KEY/ALLOWED_HOSTS por compatibilidad, pero CI,
# .env.example y docs usan siempre la forma DJANGO_*.
SECRET_KEY = (os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY")
              or ("" if _IS_PROD else "dev-only-weiner-kingdom"))
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY es obligatoria en staging/prod.")
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if _IS_PROD else "1") == "1"
_allowed = os.environ.get("DJANGO_ALLOWED_HOSTS") or os.environ.get("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]
if _IS_PROD and not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS es obligatorio en staging/prod.")
if not _IS_PROD and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["*"]  # solo desarrollo local
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "tienda",  # flujos históricos preservados (Smart Fit, Smart Quote, panel)
    "reino",   # plataforma multi-tienda (Reino Commerce P0)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.StoreLocaleMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Panel privado del personal (login con usuarios de Django, is_staff).
LOGIN_URL = "panel_login"
LOGIN_REDIRECT_URL = "panel_orders"
LOGOUT_REDIRECT_URL = "panel_login"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "tienda.context.cart_summary",
                "tienda.context.asset_version",
                "reino.context.reino_context",
            ]
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Archivos estáticos para producción
STATIC_ROOT = BASE_DIR / "staticfiles"

# Medios subidos por comerciantes (editor de tienda, §13): archivos reales,
# validados por tipo/tamaño; en dev los sirve Django, en prod el servidor.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
REINO_MEDIA_MAX_BYTES = int(os.environ.get("REINO_MEDIA_MAX_BYTES", str(3 * 1024 * 1024)))

# Base de datos: SQLite local en dev; PostgreSQL cuando hay DATABASE_URL
# o POSTGRES_* (staging/prod, auditoría §9.3).
_DB_URL = os.environ.get("DATABASE_URL", "")
if _DB_URL.startswith("postgres"):
    from urllib.parse import urlparse
    _u = urlparse(_DB_URL)
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _u.path.lstrip("/"),
        "USER": _u.username or "",
        "PASSWORD": _u.password or "",
        "HOST": _u.hostname or "localhost",
        "PORT": str(_u.port or 5432),
        "CONN_MAX_AGE": 60,
    }}
elif os.environ.get("POSTGRES_DB"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", ""),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # REINO_SQLITE_PATH permite ubicar la base en disco local cuando el
            # sistema de archivos del proyecto no soporta locks POSIX fiables
            # (p. ej. FUSE de red en algunos sandboxes).
            "NAME": os.environ.get("REINO_SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
            # Las escrituras simultáneas (p. ej. doble clic en checkout) esperan su
            # turno en vez de fallar con "database is locked".
            "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
        }
    }

# Cabeceras de seguridad activas solo en staging/prod (auditoría §9.1).
if _IS_PROD:
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    X_FRAME_OPTIONS = "DENY"

# --- Reino Commerce ----------------------------------------------------------
# Proveedor de IA (Royal Stylist). Sin clave: el asesor informa su modo real
# (reglas) y la tienda sigue funcionando. Nunca claves en el repositorio.
REINO_AI = {
    "PROVIDER": os.environ.get("REINO_AI_PROVIDER", "openai"),
    "API_KEY": os.environ.get("REINO_AI_API_KEY", ""),
    "BASE_URL": os.environ.get("REINO_AI_BASE_URL", "https://api.openai.com/v1"),
    "MODEL": os.environ.get("REINO_AI_MODEL", "gpt-4o-mini"),
    "TIMEOUT_SECONDS": float(os.environ.get("REINO_AI_TIMEOUT", "12")),
    "MAX_TOOL_ROUNDS": 4,
    "MAX_COMPLETION_TOKENS": int(os.environ.get("REINO_AI_MAX_COMPLETION_TOKENS", "600")),
    "MAX_CONTEXT_CHARS": int(os.environ.get("REINO_AI_MAX_CONTEXT_CHARS", "32000")),
    "MAX_INPUT_CHARS": int(os.environ.get("REINO_AI_MAX_INPUT_CHARS", "8000")),
    "MAX_TOOL_CALLS": int(os.environ.get("REINO_AI_MAX_TOOL_CALLS", "12")),
    "SESSION_HOURLY_LIMIT": int(os.environ.get("REINO_AI_SESSION_HOURLY_LIMIT", "120")),
    "STORE_DAILY_LIMIT": int(os.environ.get("REINO_AI_STORE_DAILY_LIMIT", "2000")),
}
# Shared database cache in deployed environments; provision with createcachetable.
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.db.DatabaseCache" if _IS_PROD else "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "reino_cache" if _IS_PROD else "reino-development",
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Reserva de stock durante el checkout (minutos).
REINO_RESERVATION_MINUTES = int(os.environ.get("REINO_RESERVATION_MINUTES", "10"))

# Correo transaccional (§18): backend configurable. Sin configuración real
# habilitada, los eventos de correo quedan BLOQUEADOS con estado preciso —
# nunca se marcan como enviados.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "Reino Commerce <no-reply@reino-commerce.local>")
REINO_EMAIL_ENABLED = os.environ.get("REINO_EMAIL_ENABLED", "0") == "1"

# Servicio real de estáticos en producción (§18): WhiteNoise sirve y comprime
# lo recolectado por collectstatic. En dev/test sirven los finders de Django.
if _IS_PROD:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
