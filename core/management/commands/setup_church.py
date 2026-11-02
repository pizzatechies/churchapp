from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from core.permissions import ADMINISTRATOR
from core.setup import setup_church
from tenants.commands import add_church_argument, use_church


class Command(BaseCommand):
    help = "Create roles, the default church chart of accounts, funds and payroll items (safe to re-run)."

    def add_arguments(self, parser):
        parser.add_argument("--name", help="Church name, e.g. 'LifeSource Church'")
        parser.add_argument("--country", help="Two-letter country code for local defaults (currency, payroll) on first setup. Default KE (Kenya).")
        parser.add_argument("--currency-symbol", help="Override the country's symbol, e.g. KSh, USh, ₦, $")
        parser.add_argument("--currency-code", help="e.g. USD, ZMW, GBP")
        parser.add_argument("--fiscal-start-month", type=int, choices=range(1, 13), help="1 = January")
        parser.add_argument("--admin-username", help="Also create an administrator account with this username")
        parser.add_argument("--admin-email", default="")
        parser.add_argument("--admin-password", help="Password for the administrator account")
        add_church_argument(parser)

    def handle(self, *args, **opts):
        use_church(opts["church"])
        profile = setup_church(
            church_name=opts["name"], currency_symbol=opts["currency_symbol"],
            currency_code=opts["currency_code"], fiscal_start_month=opts["fiscal_start_month"],
            country=opts["country"],
        )
        self.stdout.write(self.style.SUCCESS(f"Default accounts, funds, roles and payroll items are ready for {profile.name}."))
        username = opts["admin_username"]
        if username:
            if User.objects.filter(username=username).exists():
                self.stdout.write(f"User {username!r} already exists; left unchanged.")
            else:
                if not opts["admin_password"]:
                    self.stderr.write("--admin-password is required when creating an administrator.")
                    return
                user = User.objects.create_user(username, opts["admin_email"], opts["admin_password"], is_staff=True)
                user.groups.add(Group.objects.get(name=ADMINISTRATOR))
                self.stdout.write(self.style.SUCCESS(f"Administrator {username!r} created."))
