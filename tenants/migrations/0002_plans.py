from decimal import Decimal

from django.db import migrations

PLANS = [
    # code, name, tagline, monthly KSh, members, staff logins, storage GB, own domains, support, order
    ("seed", "Seed", "For a growing local church", "10000", 300, 5, 20, False, "Email support", 1),
    ("harvest", "Harvest", "For established congregations", "20000", 1000, 15, 100, False,
     "Phone and WhatsApp support; we import your members and opening balances", 2),
    ("kingdom", "Kingdom", "For large and multi-service churches", "30000", None, None, 500, True,
     "Priority support, a dedicated account manager, setup, import and training", 3),
]


def add_plans(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    for code, name, tagline, price, members, staff, gb, domains, support, order in PLANS:
        Plan.objects.update_or_create(code=code, defaults={
            "name": name, "tagline": tagline, "monthly_price": Decimal(price), "yearly_months": 10,
            "max_members": members, "max_staff": staff, "storage_gb": gb, "custom_domains": domains,
            "support": support, "sort_order": order,
        })


class Migration(migrations.Migration):
    dependencies = [("tenants", "0001_initial")]
    operations = [migrations.RunPython(add_plans, migrations.RunPython.noop)]
