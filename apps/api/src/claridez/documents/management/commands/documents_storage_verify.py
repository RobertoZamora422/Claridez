from __future__ import annotations

import hashlib
import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from claridez.organizations.tenant_scope import infrastructure_tenant_scope

from ...models import ExternalFile, GeneratedArtifact
from ...storage import private_storage


class Command(BaseCommand):
    help = "Verifica coherencia DB–objetos para backup, restauración y evidencia documental."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", type=uuid.UUID, required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        failures: list[str] = []
        checked = 0
        with infrastructure_tenant_scope(options["organization"], purpose="document_worker"):
            objects = [
                *(GeneratedArtifact.objects.values_list("storage_key", "sha256", "size_bytes")),
                *(ExternalFile.objects.values_list("storage_key", "sha256", "size_bytes")),
            ]
            storage = private_storage()
            for key, expected_hash, expected_size in objects:
                try:
                    with storage.open(key) as stream:
                        content = stream.read()
                except Exception:
                    failures.append(f"missing:{key}")
                    continue
                checked += 1
                if (
                    len(content) != expected_size
                    or hashlib.sha256(content).hexdigest() != expected_hash
                ):
                    failures.append(f"mismatch:{key}")
        if failures:
            raise CommandError(f"storage verification failed: {','.join(failures)}")
        self.stdout.write(self.style.SUCCESS(f"storage verification passed checked={checked}"))
