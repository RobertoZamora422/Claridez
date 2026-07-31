#!/usr/bin/env python
"""Utilidad de administración técnica de Django para Claridez."""

import os
import sys
from pathlib import Path


def main() -> None:
    """Ejecutar una orden administrativa de Django."""
    source_directory = Path(__file__).resolve().parent / "src"
    sys.path.insert(0, str(source_directory))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "claridez.settings.development")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
