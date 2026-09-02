from __future__ import annotations

import socket
from typing import Any

from django.core.management.base import BaseCommand

from claridez.organizations.public import active_organization_ids_for_communications_worker

from ...services import process_one


class Command(BaseCommand):
    help = "Procesa una pasada tenant-scoped del outbox de Communications."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--max-jobs", type=int, default=100)

    def handle(self, *args: object, **options: object) -> None:
        maximum = max(1, int(str(options["max_jobs"])))
        worker_id = f"{socket.gethostname()}:{id(self)}"
        processed = 0
        for organization_id in active_organization_ids_for_communications_worker():
            while processed < maximum and process_one(organization_id, worker_id=worker_id):
                processed += 1
            if processed >= maximum:
                break
        self.stdout.write(f"communications worker: {processed} job(s)")
