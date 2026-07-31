"""Crear localmente una organización y su primer propietario."""

from __future__ import annotations

import getpass
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from claridez.identity.managers import canonicalize_email
from claridez.identity.models import User
from claridez.organizations.exceptions import OrganizationDomainError
from claridez.organizations.normalization import (
    canonicalize_organization_name,
    canonicalize_organization_slug,
)
from claridez.organizations.services import bootstrap_organization


class Command(BaseCommand):
    help = "Crea localmente una organización y su primer propietario."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email")
        parser.add_argument("--display-name")
        parser.add_argument("--organization-name")
        parser.add_argument("--organization-slug")

    @staticmethod
    def _required_value(value: str | None, prompt: str) -> str:
        resolved = value if value is not None else input(prompt)
        if not resolved.strip():
            raise CommandError("Falta un valor obligatorio.")
        return resolved

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        try:
            email = canonicalize_email(
                self._required_value(options.get("email"), "Correo del propietario: ")
            )
            organization_name = canonicalize_organization_name(
                self._required_value(
                    options.get("organization_name"),
                    "Nombre de la organización: ",
                )
            )
            slug_option = options.get("organization_slug")
            organization_slug = canonicalize_organization_slug(
                slug_option if slug_option is not None else organization_name
            )

            display_name: str | None = None
            password: str | None = None
            if not User.objects.filter(email=email).exists():
                display_name = self._required_value(
                    options.get("display_name"),
                    "Nombre visible del propietario: ",
                )
                password = getpass.getpass("Contraseña: ")
                confirmation = getpass.getpass("Confirmar contraseña: ")
                if password != confirmation:
                    raise CommandError("Las contraseñas no coinciden.")

            result = bootstrap_organization(
                email=email,
                organization_name=organization_name,
                organization_slug=organization_slug,
                display_name=display_name,
                password=password,
            )
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        except (OrganizationDomainError, ValueError) as error:
            raise CommandError(str(error)) from error

        status = "created" if result.created else "already_configured"
        self.stdout.write(
            self.style.SUCCESS(
                f"status={status} organization_id={result.organization.pk} "
                f"owner_membership_id={result.owner_membership.pk}"
            )
        )
