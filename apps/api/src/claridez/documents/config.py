from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
LOCAL_ENV_FILE = REPOSITORY_ROOT / ".env"


class DocumentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=LOCAL_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="CLARIDEZ_DOCUMENT_",
        case_sensitive=False,
        extra="ignore",
    )

    storage_backend: Literal["filesystem", "s3"] = "filesystem"
    storage_root: Path = Path(".runtime/documents")
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_sse: Literal["AES256", "aws:kms"] = "AES256"
    s3_kms_key_id: str | None = None
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)
    scanner_host: str = "127.0.0.1"
    scanner_port: int = Field(default=3310, ge=1, le=65535)
    scanner_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    job_lease_seconds: int = Field(default=120, ge=10, le=1800)
    renderer_required_environment: str = "claridez-render-weasyprint-69.0-debian12-v1"
    renderer_environment: str = "host-not-approved"
    token_hmac_key: SecretStr | None = Field(default=None, min_length=32, max_length=512)

    @field_validator("storage_root", mode="after")
    @classmethod
    def resolve_storage_root(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (REPOSITORY_ROOT / value).resolve()

    @model_validator(mode="after")
    def validate_storage(self) -> DocumentSettings:
        if self.storage_backend == "s3" and not all(
            (self.s3_bucket, self.s3_access_key_id, self.s3_secret_access_key)
        ):
            raise ValueError("el adaptador S3 requiere bucket y credenciales")
        if self.s3_sse == "aws:kms" and not self.s3_kms_key_id:
            raise ValueError("SSE-KMS requiere s3_kms_key_id")
        return self


@lru_cache(maxsize=1)
def document_settings() -> DocumentSettings:
    return DocumentSettings()
