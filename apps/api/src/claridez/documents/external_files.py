from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO
from warnings import catch_warnings, simplefilter

from PIL import Image
from pypdf import PdfReader

from .errors import DocumentsError


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    display_name: str
    extension: str
    media_type: str


ALLOWED_UPLOADS = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}


def inspect_upload(
    *, display_name: str, declared_media_type: str, stream: BinaryIO
) -> ValidatedUpload:
    if (
        not display_name
        or len(display_name) > 240
        or any(c in display_name for c in "/\\\0")
        or any(ord(c) < 32 or ord(c) == 127 for c in display_name)
    ):
        raise DocumentsError("invalid_filename", "El nombre de archivo no es válido.")
    extension = PurePath(display_name).suffix.lower()
    expected = ALLOWED_UPLOADS.get(extension)
    if expected is None or declared_media_type != expected[0]:
        raise DocumentsError("unsupported_file", "El tipo de archivo no está permitido.")
    signature = stream.read(max(len(item[1]) for item in ALLOWED_UPLOADS.values()))
    stream.seek(0)
    if not signature.startswith(expected[1]):
        raise DocumentsError("mime_mismatch", "La extensión y el contenido no coinciden.")
    return ValidatedUpload(display_name, extension, expected[0])


def validate_upload(
    *, display_name: str, declared_media_type: str, stream: BinaryIO
) -> ValidatedUpload:
    inspected = inspect_upload(
        display_name=display_name,
        declared_media_type=declared_media_type,
        stream=stream,
    )
    try:
        if inspected.media_type == "application/pdf":
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted or not reader.pages:
                raise ValueError("encrypted or empty PDF")
            root = reader.trailer.get("/Root", {})
            if any(key in root for key in ("/OpenAction", "/AA", "/Names")):
                raise ValueError("active PDF content")
        else:
            with catch_warnings():
                simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(stream)
                if image.width * image.height > 40_000_000:
                    raise ValueError("image dimensions exceed policy")
                image.verify()
                if image.format not in {"JPEG", "PNG"}:
                    raise ValueError("decoded image format mismatch")
    except Exception as error:
        raise DocumentsError(
            "invalid_file", "El archivo no supera la validación estructural."
        ) from error
    finally:
        stream.seek(0)
    return inspected


def buffered_upload(source: BinaryIO, *, max_bytes: int) -> io.BytesIO:
    output = io.BytesIO()
    size = 0
    while chunk := source.read(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise DocumentsError("file_too_large", "El archivo excede el límite permitido.")
        output.write(chunk)
    if size == 0:
        raise DocumentsError("empty_file", "El archivo está vacío.")
    output.seek(0)
    return output
