from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from tenants.commands import use_church


class Command(BaseCommand):
    help = "Rebuild the demo church from scratch. Only runs on a demo server (ECCLESIA_DEMO_MODE=1)."

    def handle(self, *args, **opts):
        if not settings.DEMO_MODE:
            raise CommandError("Refusing to wipe anything: this server is not in demo mode (set ECCLESIA_DEMO_MODE=1).")
        church = use_church()
        # Only the demo church's own schema is rebuilt; the platform's shared tables are untouched.
        connection.set_schema_to_public()
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{church.schema_name}" CASCADE')
        church.create_schema(check_if_exists=False, verbosity=0)
        connection.set_tenant(church)
        call_command("load_demo_data", password=settings.DEMO_PASSWORD, church=church.slug, stdout=self.stdout)
