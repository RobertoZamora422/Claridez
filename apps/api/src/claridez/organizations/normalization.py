"""Normalización canónica de organizaciones."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

MAX_ORGANIZATION_NAME_LENGTH = 150
MAX_ORGANIZATION_SLUG_LENGTH = 63
MAX_TIMEZONE_LENGTH = 64
MAX_BUSINESS_LABEL_LENGTH = 150
MAX_LOCATION_REFERENCE_LENGTH = 300
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class PostgreSQLTimezoneIsValid(models.Func):
    """Expresión PostgreSQL que falla cerrada para zonas IANA desconocidas."""

    arity = 1
    output_field = models.BooleanField()
    template = "public.claridez_is_iana_timezone(%(expressions)s)"


def canonicalize_organization_name(name: str | None) -> str:
    """Eliminar espacios exteriores y exigir un nombre no vacío."""
    if name is None:
        raise ValueError("El nombre de la organización es obligatorio.")
    canonical_name = name.strip()
    if not canonical_name:
        raise ValueError("El nombre de la organización es obligatorio.")
    if len(canonical_name) > MAX_ORGANIZATION_NAME_LENGTH:
        raise ValueError("El nombre de la organización excede la longitud máxima.")
    return canonical_name


def canonicalize_business_label(value: str | None, *, field: str) -> str:
    """Normalizar nombres visibles de sedes y espacios sin inventar identificadores."""
    if value is None:
        raise ValueError(f"{field} es obligatorio.")
    canonical = " ".join(value.split())
    if not canonical or len(canonical) > MAX_BUSINESS_LABEL_LENGTH:
        raise ValueError(f"{field} no es válido.")
    return canonical


def canonicalize_location_reference(value: str | None) -> str:
    """Conservar una referencia humana mínima de ubicación."""
    if value is None or not value.strip():
        return ""
    canonical = " ".join(value.split())
    if len(canonical) > MAX_LOCATION_REFERENCE_LENGTH:
        raise ValueError("La referencia de ubicación no es válida.")
    return canonical


def canonicalize_organization_slug(value: str | None) -> str:
    """Crear el slug ASCII canónico sin truncarlo ni resolver colisiones."""
    if value is None:
        raise ValueError("El slug de la organización es obligatorio.")
    canonical_slug = slugify(value, allow_unicode=False)
    if not canonical_slug:
        raise ValueError("El slug de la organización es obligatorio.")
    if len(canonical_slug) > MAX_ORGANIZATION_SLUG_LENGTH:
        raise ValueError("El slug de la organización excede la longitud máxima.")
    return canonical_slug


def canonicalize_currency(value: str | None) -> str:
    """Normalizar una moneda ISO de tres letras sin inferir equivalencias."""
    if value is None:
        raise ValueError("La moneda es obligatoria.")
    canonical_currency = value.strip().upper()
    if CURRENCY_PATTERN.fullmatch(canonical_currency) is None:
        raise ValueError("La moneda debe contener exactamente tres letras ASCII.")
    return canonical_currency


def validate_iana_timezone(value: str) -> None:
    """Aceptar únicamente nombres presentes en la base IANA disponible."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValidationError("La zona horaria no es un identificador IANA válido.") from error
    if value not in available_timezones():
        raise ValidationError("La zona horaria no es un identificador IANA válido.")


def canonicalize_timezone(value: str | None) -> str:
    """Eliminar espacios exteriores y comprobar el identificador IANA."""
    if value is None:
        raise ValueError("La zona horaria es obligatoria.")
    canonical_timezone = value.strip()
    if not canonical_timezone or len(canonical_timezone) > MAX_TIMEZONE_LENGTH:
        raise ValueError("La zona horaria no es válida.")
    validate_iana_timezone(canonical_timezone)
    return canonical_timezone
