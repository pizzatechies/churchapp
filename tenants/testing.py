"""Test runner: every existing test runs inside one church's schema, like a real request does."""

from django.db import connection
from django.test.runner import DiscoverRunner


class ChurchTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        config = super().setup_databases(**kwargs)
        from tenants.models import Church, Plan

        connection.set_schema_to_public()
        church = Church(schema_name="church_test", slug="test", name="Test Church", status=Church.ACTIVE,
                        plan=Plan.objects.get(code="kingdom"), is_default=True)
        church.save(verbosity=0)
        connection.set_tenant(church)
        return config
