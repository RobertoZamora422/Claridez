from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
from dataclasses import dataclass

from pypdf import PdfReader

from .config import document_settings
from .errors import DocumentsError

RENDERER_NAME = "WeasyPrint"
RENDERER_VERSION = "69.0"
RENDER_TIMEOUT_SECONDS = 30
MAX_RENDER_OUTPUT_BYTES = 25 * 1024 * 1024
MAX_RENDER_PAGES = 250


@dataclass(frozen=True, slots=True)
class RenderedPDF:
    content: bytes
    sha256: str
    size_bytes: int
    renderer_name: str
    renderer_version: str
    environment: str


def validate_rendered_pdf(content: bytes) -> int:
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        page_count = len(reader.pages)
        if reader.is_encrypted or page_count < 1:
            raise ValueError("encrypted or empty generated PDF")
        if page_count > MAX_RENDER_PAGES:
            raise DocumentsError(
                "render_page_limit_exceeded",
                f"El PDF excedió el límite de {MAX_RENDER_PAGES} páginas.",
            )
    except DocumentsError:
        raise
    except Exception as error:
        raise DocumentsError(
            "invalid_rendered_pdf", "El renderer no produjo un PDF estructuralmente válido."
        ) from error
    return page_count


def render_pdf(html: str) -> RenderedPDF:
    config = document_settings()
    if config.renderer_environment != config.renderer_required_environment:
        raise DocumentsError(
            "renderer_environment_not_approved",
            "La emisión solo puede ejecutarse en el entorno canónico aprobado.",
            status_code=503,
        )
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    environment["SOURCE_DATE_EPOCH"] = "0"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "claridez.documents.renderer_process"],
            input=html.encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=RENDER_TIMEOUT_SECONDS,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise DocumentsError("render_timeout", "El render excedió el tiempo permitido.") from error
    if completed.returncode != 0 or not completed.stdout.startswith(b"%PDF-"):
        detail = completed.stderr.decode("utf-8", "replace")[-500:]
        raise DocumentsError("render_failed", detail or "El render no produjo un PDF válido.")
    if len(completed.stdout) > MAX_RENDER_OUTPUT_BYTES:
        raise DocumentsError("render_output_too_large", "El PDF excedió el límite de emisión.")
    validate_rendered_pdf(completed.stdout)
    digest = hashlib.sha256(completed.stdout).hexdigest()
    return RenderedPDF(
        content=completed.stdout,
        sha256=digest,
        size_bytes=len(completed.stdout),
        renderer_name=RENDERER_NAME,
        renderer_version=RENDERER_VERSION,
        environment=config.renderer_environment,
    )
