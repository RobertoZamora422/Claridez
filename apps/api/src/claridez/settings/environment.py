"""Carga y validación tipada de la configuración local de Claridez."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
LOCAL_ENV_FILE = REPOSITORY_ROOT / ".env"
LocalSecret = Annotated[SecretStr, Field(min_length=32, max_length=512)]


class _LocalConnectionSettings(BaseSettings):
    """Valores no secretos comunes a las conexiones del entorno local."""

    model_config = SettingsConfigDict(
        env_file=LOCAL_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="CLARIDEZ_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["local"]
    db_host: str
    db_port: int = Field(ge=1, le=65535)
    db_connect_timeout: int = Field(ge=1, le=10)
    db_statement_timeout_ms: int = Field(ge=100, le=30_000)
    db_sslmode: Literal["disable"]

    @field_validator("db_host")
    @classmethod
    def validate_loopback_host(cls, value: str) -> str:
        if value.lower() == "localhost":
            return value
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError("debe ser un host de loopback") from error
        if not address.is_loopback:
            raise ValueError("debe ser un host de loopback")
        return value


class RuntimeSettings(_LocalConnectionSettings):
    """Configuración que puede conocer el proceso normal de Django."""

    secret_key: LocalSecret
    allowed_hosts: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    db_name: Literal["claridez_local"]
    db_user: Literal["claridez_app"]
    db_password: LocalSecret
    auth_link_base_url: str = "http://127.0.0.1:5173"
    communications_provider: Literal["deterministic", "resend"] = "deterministic"
    communications_resend_api_key: SecretStr = SecretStr("")
    communications_resend_api_url: str = "https://api.resend.com/emails"
    communications_webhook_secret: SecretStr = SecretStr("")
    communications_worker_lease_seconds: int = Field(default=120, ge=30, le=900)
    communications_webhook_replay_seconds: int = Field(default=300, ge=60, le=900)
    portal_antiabuse_provider: Literal["deterministic", "turnstile"] = "deterministic"
    portal_turnstile_secret_key: SecretStr = SecretStr("")
    portal_turnstile_site_key: str = ""
    portal_turnstile_expected_hostnames: str = ""
    portal_challenge_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    portal_session_idle_ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    portal_session_absolute_ttl_seconds: int = Field(default=28800, ge=900, le=604800)
    portal_ephemeral_locator_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    @model_validator(mode="after")
    def validate_portal_session_ttls(self) -> RuntimeSettings:
        if self.portal_session_idle_ttl_seconds > self.portal_session_absolute_ttl_seconds:
            raise ValueError("la expiración idle de Portal no puede superar la absoluta")
        return self

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: str) -> str:
        hosts = [host.strip() for host in value.split(",") if host.strip()]
        if not hosts:
            raise ValueError("debe contener al menos un host")
        allowed = {"127.0.0.1", "localhost", "[::1]"}
        if any(host not in allowed for host in hosts):
            raise ValueError("solo admite hosts locales conocidos")
        return ",".join(hosts)

    def allowed_hosts_list(self) -> list[str]:
        return self.allowed_hosts.split(",")

    @field_validator("auth_link_base_url")
    @classmethod
    def validate_auth_link_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("debe ser una URL HTTP local sin credenciales, query ni fragmento")
        return value.rstrip("/")


class DocumentWorkerSettings(BaseSettings):
    """Configuración acotada del worker canónico dentro de Compose local."""

    model_config = SettingsConfigDict(
        env_file=LOCAL_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="CLARIDEZ_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["local"]
    secret_key: LocalSecret
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    db_host: Literal["postgres"]
    db_port: int = Field(ge=1, le=65535)
    db_connect_timeout: int = Field(ge=1, le=10)
    db_statement_timeout_ms: int = Field(ge=100, le=30_000)
    db_sslmode: Literal["disable"]
    db_name: Literal["claridez_local"]
    db_user: Literal["claridez_app"]
    db_password: LocalSecret

    @field_validator("db_port")
    @classmethod
    def validate_internal_postgres_port(cls, value: int) -> int:
        if value != 5432:
            raise ValueError("el worker solo admite el puerto interno 5432")
        return value


class AnalyticsWorkerSettings(BaseSettings):
    """Worker P15 local: conexión limitada propia, sin configuración ni estado documental."""

    model_config = SettingsConfigDict(
        env_file=LOCAL_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="CLARIDEZ_",
        case_sensitive=False,
        extra="ignore",
    )
    environment: Literal["local"]
    secret_key: LocalSecret
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    db_host: Literal["postgres"]
    db_port: Literal[5432]
    db_connect_timeout: int = Field(ge=1, le=10)
    db_statement_timeout_ms: int = Field(ge=100, le=30_000)
    db_sslmode: Literal["disable"]
    db_name: Literal["claridez_local"]
    db_user: Literal["claridez_app"]
    db_password: LocalSecret


class MigrationSettings(_LocalConnectionSettings):
    """Configuración exclusiva de comandos de migración."""

    secret_key: LocalSecret
    db_name: Literal["claridez_local"]
    migration_db_user: Literal["claridez_migrator"]
    migration_db_password: LocalSecret


class TestSettings(_LocalConnectionSettings):
    """Configuración exclusiva del ejecutor de pruebas."""

    secret_key: LocalSecret
    postgres_admin_db: Literal["postgres"]
    test_db_name: Literal["claridez_test"]
    test_db_user: Literal["claridez_test_runner"]
    test_db_password: LocalSecret


class BootstrapSettings(_LocalConnectionSettings):
    """Credenciales que solo puede cargar la herramienta bootstrap local."""

    db_name: Literal["claridez_local"]
    db_user: Literal["claridez_app"]
    db_password: LocalSecret
    migration_db_user: Literal["claridez_migrator"]
    migration_db_password: LocalSecret
    test_db_name: Literal["claridez_test"]
    test_db_user: Literal["claridez_test_runner"]
    test_db_password: LocalSecret
    postgres_admin_db: Literal["postgres"]
    postgres_admin_user: Literal["postgres"]
    postgres_admin_password: LocalSecret


def _load[SettingsType: BaseSettings](settings_type: type[SettingsType]) -> SettingsType:
    try:
        return settings_type()
    except ValidationError as error:
        issues = sorted(
            {
                f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
                for item in error.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            }
        )
        detail = ", ".join(issues) if issues else "error de validación"
        raise ImproperlyConfigured(f"Configuración local inválida ({detail}).") from None


def load_runtime_settings() -> RuntimeSettings:
    return _load(RuntimeSettings)


def load_document_worker_settings() -> DocumentWorkerSettings:
    return _load(DocumentWorkerSettings)


def load_analytics_worker_settings() -> AnalyticsWorkerSettings:
    return _load(AnalyticsWorkerSettings)


def load_migration_settings() -> MigrationSettings:
    return _load(MigrationSettings)


def load_test_settings() -> TestSettings:
    return _load(TestSettings)


def load_bootstrap_settings() -> BootstrapSettings:
    return _load(BootstrapSettings)
