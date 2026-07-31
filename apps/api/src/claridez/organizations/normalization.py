"""Normalización canónica de organizaciones."""

from django.utils.text import slugify

MAX_ORGANIZATION_NAME_LENGTH = 150
MAX_ORGANIZATION_SLUG_LENGTH = 63


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
