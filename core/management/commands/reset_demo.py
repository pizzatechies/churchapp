from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Wipe the database and reload the sample church. Only runs on a demo server (ECCLESIA_DEMO_MODE=1)."

    def handle(self, *args, **opts):
        if not settings.DEMO_MODE:
            raise CommandError("Refusing to wipe the database: this server is not in demo mode (set ECCLESIA_DEMO_MODE=1).")
        call_command("flush", interactive=False, verbosity=0)
        call_command("load_demo_data", password=settings.DEMO_PASSWORD, stdout=self.stdout)
