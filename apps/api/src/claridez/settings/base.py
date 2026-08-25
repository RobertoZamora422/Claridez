"""Configuración común de Django independiente de credenciales."""

from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parents[3]

DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.sessions",
    "axes",
    "claridez.identity.apps.IdentityConfig",
    "claridez.organizations.apps.OrganizationsConfig",
    "claridez.catalog.apps.CatalogConfig",
    "claridez.people.apps.PeopleConfig",
    "claridez.commercial.apps.CommercialConfig",
    "claridez.scheduling.apps.SchedulingConfig",
    "claridez.crm.apps.CrmConfig",
    "claridez.operations.apps.OperationsConfig",
    "claridez.documents.apps.DocumentsConfig",
    "claridez.receivables.apps.ReceivablesConfig",
    "claridez.resources.apps.ResourcesConfig",
    "claridez.finance.apps.FinanceConfig",
    "rest_framework",
    "drf_spectacular",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "claridez.identity.middleware.AuthenticationNoStoreMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "claridez.identity.middleware.AbsoluteSessionExpiryMiddleware",
    "axes.middleware.AxesMiddleware",
]
ROOT_URLCONF = "claridez.urls"
TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "claridez.wsgi.application"
ASGI_APPLICATION = "claridez.asgi.application"

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

AUTH_USER_MODEL = "identity.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

SESSION_ABSOLUTE_AGE_SECONDS = 8 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_FAILURE_VIEW = "claridez.identity.views.csrf_failure"

PASSWORD_RESET_TIMEOUT = 60 * 60
EMAIL_VERIFICATION_TIMEOUT = 24 * 60 * 60
AUTH_LINK_BASE_URL = "http://testserver"
DEFAULT_FROM_EMAIL = "Claridez <no-reply@claridez.local>"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

AXES_HANDLER = "axes.handlers.database.AxesDatabaseHandler"
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_USE_ATTEMPT_EXPIRATION = True
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_HTTP_RESPONSE_CODE = 429
AXES_USERNAME_FORM_FIELD = "email"
AXES_CLIENT_IP_CALLABLE = "claridez.identity.axes.client_ip_from_remote_addr"
AXES_LOCKOUT_CALLABLE = "claridez.identity.axes.json_lockout_response"
AXES_ENABLE_ADMIN = False
AXES_SENSITIVE_PARAMETERS = ["username", "email", "ip_address", "password"]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "claridez.identity.errors.api_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Claridez API",
    "DESCRIPTION": "API de Claridez con autenticación local mediante sesiones de servidor.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "OperationPreparationStatus": ("claridez.operations.models.EventPreparation.Status"),
        "OperationItemStatus": "claridez.operations.models.PreparationItem.Status",
        "OperationalVerificationResolutionStatus": (
            "claridez.operations.advanced_serializers.VERIFICATION_RESOLUTION_STATUS_CHOICES"
        ),
        "OperationalIncidentTransitionStatus": (
            "claridez.operations.advanced_serializers.INCIDENT_TRANSITION_STATUS_CHOICES"
        ),
        "SchedulingReservationStatus": "claridez.scheduling.models.Reservation.Status",
        "SchedulingBlockStatus": "claridez.scheduling.models.ScheduleBlock.Status",
        "SchedulingBlockScope": "claridez.scheduling.models.ScheduleBlock.Scope",
        "DocumentTemplateVersionStatus": (
            "claridez.documents.models.DocumentTemplateVersion.Status"
        ),
        "IssuedInstrumentVersionState": ("claridez.documents.models.IssuedInstrumentVersion.State"),
        "ExternalDocumentFileState": "claridez.documents.models.ExternalFile.State",
        "ReceivablesPaymentMethod": "claridez.receivables.models.ReceivedPayment.Method",
        "ReceivablesAdjustmentDirection": (
            "claridez.receivables.models.ReceivableAdjustment.Direction"
        ),
        "FinanceCategoryKind": "claridez.finance.models.FinanceCategory.Kind",
        "FinanceExpenseType": "claridez.finance.models.ExpenseOccurrence.ExpenseType",
        "FinanceCorrectionDirection": ("claridez.finance.models.DirectCostCorrection.Direction"),
        "FinanceCashDirection": "claridez.finance.models.OperatingCashMovement.Direction",
        "FinanceExpenseAllocationScope": "claridez.finance.models.ExpenseAllocation.Scope",
        "ResourcesNature": "claridez.resources.models.Resource.Nature",
        "ResourcesMovementKind": "claridez.resources.models.StockMovement.Kind",
    },
}


def build_database_configuration(
    *,
    name: str,
    user: str,
    password: SecretStr,
    host: str,
    port: int,
    connect_timeout: int,
    statement_timeout_ms: int,
    sslmode: str,
    test_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Construir una conexión PostgreSQL sin alternativas silenciosas."""
    database: dict[str, Any] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password.get_secret_value(),
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {
            "connect_timeout": connect_timeout,
            "options": f"-c timezone=UTC -c statement_timeout={statement_timeout_ms}",
            "sslmode": sslmode,
        },
    }
    if test_name is not None:
        database["TEST"] = {"NAME": test_name}
    return {"default": database}


def build_logging_configuration(level: str) -> dict[str, Any]:
    """Enviar logs técnicos estructurados a la salida estándar."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": "claridez.logging.SafeJsonFormatter"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
            }
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            }
        },
        "root": {"handlers": ["console"], "level": level},
    }
