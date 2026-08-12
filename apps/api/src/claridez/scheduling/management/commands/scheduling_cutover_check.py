from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from claridez.scheduling.cutover import CutoverIntegrityError, verify_scheduling_cutover


class Command(BaseCommand):
    help = "Verifica la integridad obligatoria antes de abrir tráfico tras el cutover P8."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            result = verify_scheduling_cutover()
        except CutoverIntegrityError as caught:
            raise CommandError(str(caught)) from caught
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
