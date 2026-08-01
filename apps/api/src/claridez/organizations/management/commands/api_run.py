"""Run the local API without querying Django's migration recorder as the app role."""

from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    """Run the development server with the deliberately limited application role."""

    help = "Run the local API without granting the application role migration metadata access."

    def check_migrations(self) -> None:
        """Keep migration verification in the explicit migrator-owned commands."""
