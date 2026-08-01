from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from claridez.operations.cutover import CutoverIntegrityError, verify_operations_cutover


class Command(BaseCommand):
    help = "Verifica la integridad obligatoria antes de abrir tráfico tras el cutover 5.2."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            result = verify_operations_cutover()
        except CutoverIntegrityError as caught:
            raise CommandError(str(caught)) from caught
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
