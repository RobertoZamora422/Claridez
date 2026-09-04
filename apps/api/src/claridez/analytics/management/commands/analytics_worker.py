from __future__ import annotations

from time import monotonic, sleep
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from claridez.analytics.jobs import work_round


class Command(BaseCommand):
    help = "Procesa una ronda tenant-aware de exports Analytics (un claim por organización activa)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--max-seconds", type=int, default=50)

    def handle(self, *args: Any, **options: Any) -> None:
        deadline = monotonic() + max(1, min(options["max_seconds"], 86400))
        handled = 0
        while True:
            current = work_round()
            handled += current
            if options["once"] or monotonic() >= deadline:
                break
            if not current:
                sleep(1)
        self.stdout.write(f"Analytics: {handled} trabajos procesados en la ronda.")
