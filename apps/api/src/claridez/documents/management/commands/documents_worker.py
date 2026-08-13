from __future__ import annotations

import socket
import uuid
from time import monotonic, sleep
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from claridez.organizations.public import active_organization_ids_for_document_worker

from ...jobs import work_once


class Command(BaseCommand):
    help = "Procesa el ledger durable de jobs documentales con ejecución at-least-once."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--organization", type=uuid.UUID)
        parser.add_argument("--max-seconds", type=int, default=50)

    def handle(self, *args: Any, **options: Any) -> None:
        worker_id = f"{socket.gethostname()}:{uuid.uuid4()}"
        deadline = monotonic() + max(1, options["max_seconds"])
        processed = 0
        while True:
            organization_ids = (
                [options["organization"]]
                if options["organization"]
                else active_organization_ids_for_document_worker()
            )
            progressed = False
            for organization_id in organization_ids:
                if work_once(organization_id, worker_id=worker_id):
                    progressed = True
                    processed += 1
            if options["once"] or monotonic() >= deadline:
                break
            if not progressed:
                sleep(1)
        self.stdout.write(
            self.style.SUCCESS(f"document jobs processed={processed} worker={worker_id}")
        )
