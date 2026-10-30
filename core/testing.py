"""Shared fixtures for the test suite."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.permissions import ROLES
from core.setup import setup_church

D = Decimal


class ChurchTestCase(TestCase):
    """A church with the default chart of accounts, funds and one user per role."""

    @classmethod
    def setUpTestData(cls):
        from ledger.models import Account, Fund

        setup_church()
        cls.users = {}
        for role in ROLES:
            username = role.split()[0].lower().strip("/")
            user = User.objects.create_user(username, f"{username}@example.com", "test-pass-123")
            user.groups.add(Group.objects.get(name=role))
            cls.users[role] = user
        cls.admin = User.objects.create_superuser("root", "root@example.com", "test-pass-123")
        cls.treasurer = cls.users["Treasurer"]
        cls.bookkeeper = cls.users["Bookkeeper"]
        cls.counter = cls.users["Offering Counter"]
        cls.viewer = cls.users["Pastor / Viewer"]
        cls.committee = cls.users["Finance Committee"]

        A = lambda n: Account.objects.get(number=n)  # noqa: E731
        cls.checking, cls.savings, cls.tithes, cls.building_income = A("1010"), A("1020"), A("4000"), A("4030")
        cls.utilities, cls.repairs, cls.ap = A("6010"), A("6020"), A("2000")
        cls.gen, cls.bld, cls.mis = Fund.objects.get(code="GEN"), Fund.objects.get(code="BLD"), Fund.objects.get(code="MIS")

    def line(self, account, fund, debit=0, credit=0, description=""):
        from ledger.services import Line

        return Line(account, fund, D(str(debit)), D(str(credit)), description)

    def deposit(self, amount, fund=None, when=date(2026, 3, 1), income=None):
        from ledger.services import create_entry

        fund = fund or self.gen
        return create_entry(date=when, memo="Test deposit", user=self.treasurer, lines=[
            self.line(self.checking, fund, debit=amount),
            self.line(income or self.tithes, fund, credit=amount),
        ])
