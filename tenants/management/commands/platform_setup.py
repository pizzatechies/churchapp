"""
Run on every start of the admin app (docker-entrypoint.sh). Safe to repeat.

1. A database from before churches had their own schemas keeps everything in the
   "public" schema. Its tables are moved, in one transaction, into a schema of their
   own and registered as the first church, served at the apps' main addresses, so
   existing logins, apps and bookmarks keep working.
2. The shared platform tables are created or updated, then every church's schema.
3. The platform super admin is created from PLATFORM_ADMIN_USERNAME / _PASSWORD /
   _EMAIL (or, if those are unset, the ADMIN_* values) if it doesn't exist yet.
4. On a brand-new install with no churches, a first church is created when
   ECCLESIA_DEFAULT_CHURCH is set (self-hosted single-church servers, the demo).
"""

import os

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils.text import slugify
from django_tenants.utils import tenant_context

from tenants.models import Church, Plan, PlatformProfile
from tenants.services import create_church


def _public_tables():
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
        return [r[0] for r in cursor.fetchall()]


def _schemas_with_church_tables():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = 'core_churchprofile' AND table_schema <> 'public'"
        )
        return [r[0] for r in cursor.fetchall()]


def _church_name(schema):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT name, country FROM "{schema}".core_churchprofile ORDER BY id LIMIT 1')
        row = cursor.fetchone()
    return (row[0], row[1]) if row else ("Our church", "KE")


class Command(BaseCommand):
    help = "Prepare the Ecclesia platform: move a single-church database into its own schema, migrate, create the super admin."

    def handle(self, *args, **opts):
        connection.set_schema_to_public()
        adopted = self.adopt_single_church()
        call_command("migrate_schemas", shared=True, interactive=False, verbosity=0)
        self.register_orphan_schemas(default_schema=adopted)
        call_command("migrate_schemas", tenant=True, interactive=False, verbosity=0)
        self.ensure_super_admin()
        self.ensure_first_church()
        self.stdout.write(self.style.SUCCESS(f"Platform ready: {Church.objects.count()} church(es)."))

    # -------------------------------------------------------------- adoption

    def adopt_single_church(self):
        tables = _public_tables()
        if "core_churchprofile" not in tables or "tenants_church" in tables:
            return None
        name, _ = _church_name("public")
        slug = (os.environ.get("ECCLESIA_DEFAULT_CHURCH") or slugify(name).replace("-church", "") or "main")[:40].strip("-") or "main"
        schema = Church.schema_for(slug)
        self.stdout.write(f"Moving the existing church “{name}” into its own schema {schema}…")
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA "{schema}"')
                for table in tables:
                    cursor.execute(f'ALTER TABLE public."{table}" SET SCHEMA "{schema}"')
        return schema

    def register_orphan_schemas(self, default_schema=None):
        """A schema with church tables but no Church row: register it (finishes an interrupted adoption)."""
        known = set(Church.objects.values_list("schema_name", flat=True))
        for schema in _schemas_with_church_tables():
            if schema in known:
                continue
            name, country = _church_name(schema)
            slug = schema.removeprefix("church_").replace("_", "-")
            plan = Plan.objects.filter(code="kingdom").first() or Plan.objects.order_by("-monthly_price").first()
            church = Church(schema_name=schema, slug=slug, name=name, plan=plan, country=country or "KE", status=Church.ACTIVE,
                            is_default=not Church.objects.filter(is_default=True).exists() or schema == default_schema,
                            notes="Moved from the single-church database.")
            church.save(verbosity=0)  # the schema exists, so nothing is re-created
            self.stdout.write(self.style.SUCCESS(f"Registered {name} at /church/{slug}/ (also at the main addresses)."))

    # ----------------------------------------------------------- super admin

    def ensure_super_admin(self):
        username = os.environ.get("PLATFORM_ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("PLATFORM_ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
        email = os.environ.get("PLATFORM_ADMIN_EMAIL") or os.environ.get("ADMIN_EMAIL") or ""
        if not username or not password:
            if not User.objects.filter(is_superuser=True).exists():
                self.stdout.write("No platform super admin yet: set PLATFORM_ADMIN_USERNAME and PLATFORM_ADMIN_PASSWORD, "
                                  "or run: python manage.py createsuperuser")
            return
        if User.objects.filter(username=username).exists():
            return
        user = User.objects.create_superuser(username, email, password)
        PlatformProfile.objects.get_or_create(user=user)
        self.stdout.write(self.style.SUCCESS(f"Platform super admin “{username}” created. Sign in at /platform/."))

    # ---------------------------------------------------------- first church

    def ensure_first_church(self):
        from django.conf import settings

        slug = os.environ.get("ECCLESIA_DEFAULT_CHURCH", "").strip() or ("demo" if settings.DEMO_MODE else "")
        if not slug or Church.objects.exists():
            return
        username, password = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
        if settings.DEMO_MODE:
            username = password = None  # the demo loader creates its own sample logins
        elif not username or not password:
            self.stdout.write("ECCLESIA_DEFAULT_CHURCH is set but ADMIN_USERNAME / ADMIN_PASSWORD aren't; no church created.")
            return
        plan = Plan.objects.filter(code="kingdom").first()
        church, user, _ = create_church(
            name=os.environ.get("CHURCH_NAME", "LifeSource Church" if settings.DEMO_MODE else "Our Church"), slug=slugify(slug)[:40], plan=plan, admin_username=username,
            admin_email=os.environ.get("ADMIN_EMAIL", ""), admin_password=password, country=os.environ.get("CHURCH_COUNTRY", "KE"),
            paid_until=None, is_default=True,
        )
        Church.objects.filter(pk=church.pk).update(status=Church.ACTIVE, trial_ends=None)
        if user is not None:
            with tenant_context(church):
                from core.models import AccountProfile

                # The server owner chose this password: no need to change it at first sign-in.
                AccountProfile.password_set_by_someone_else(user, False)
        self.stdout.write(self.style.SUCCESS(f"First church created at /church/{church.slug}/ (also at the main addresses)."))
