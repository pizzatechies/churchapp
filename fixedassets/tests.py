from datetime import date

from core.testing import ChurchTestCase, D
from ledger.models import Account
from ledger.services import LedgerError

from . import services
from .models import FixedAsset


class DepreciationTests(ChurchTestCase):
    def setUp(self):
        self.vehicles = Account.objects.get(number="1540")
        self.accum = Account.system(Account.SYS_ACCUM_DEPRECIATION)
        self.expense = Account.system(Account.SYS_DEPRECIATION)

    def asset(self, **kw):
        defaults = dict(name="Van", category="vehicle", acquisition_date=date(2026, 1, 10), in_service_date=date(2026, 1, 10),
                        cost=D("30000"), salvage_value=D("6000"), useful_life_months=60, asset_account=self.vehicles,
                        accumulated_account=self.accum, expense_account=self.expense, fund=self.gen)
        defaults.update(kw)
        return FixedAsset.objects.create(**defaults)

    def test_straight_line_monthly(self):
        a = self.asset()
        self.assertEqual(a.monthly_depreciation, D("400.00"))
        run = services.run_depreciation(date(2026, 3, 31), self.treasurer)
        self.assertEqual(run.total, D("1200.00"))
        self.assertEqual(self.expense.balance(), D("1200.00"))
        a.refresh_from_db()
        self.assertEqual(a.book_value, D("28800.00"))
        with self.assertRaises(LedgerError):
            services.run_depreciation(date(2026, 3, 31), self.treasurer)  # nothing left for those months

    def test_never_exceeds_depreciable_base(self):
        a = self.asset(useful_life_months=3, cost=D("1000"), salvage_value=D("100"))
        services.run_depreciation(date(2026, 12, 31), self.treasurer)
        a.refresh_from_db()
        self.assertEqual(a.accumulated_depreciation, D("900.00"))

    def test_land_is_not_depreciated(self):
        self.asset(name="Land", category="land", useful_life_months=0)
        self.assertEqual(services.preview(date(2026, 12, 31)), [])

    def test_prior_depreciation_is_respected(self):
        a = self.asset(in_service_date=date(2020, 1, 1), prior_depreciation=D("10000"), prior_depreciation_through=date(2025, 12, 31))
        [(asset, months, amount, start)] = services.preview(date(2026, 2, 28))
        self.assertEqual((months, amount, start), (2, D("800.00"), date(2026, 1, 1)))
        self.assertEqual(a.book_value, D("20000.00"))

    def test_void_latest_run_restores_schedule(self):
        a = self.asset()
        services.run_depreciation(date(2026, 1, 31), self.treasurer)
        run2 = services.run_depreciation(date(2026, 2, 28), self.treasurer)
        services.void_depreciation_run(run2, self.treasurer)
        a.refresh_from_db()
        self.assertEqual(a.depreciated_through, date(2026, 1, 31))
        self.assertEqual(a.accumulated_depreciation, D("400.00"))

    def test_disposal_records_gain(self):
        from ledger.services import record_opening_balances

        record_opening_balances(date=date(2025, 12, 31), rows=[(self.vehicles, self.gen, D("30000"))], user=self.treasurer)
        a = self.asset()
        services.run_depreciation(date(2026, 6, 30), self.treasurer)
        a.refresh_from_db()
        services.dispose_asset(a, date=date(2026, 6, 30), proceeds=D("29000"), deposit_account=self.checking, user=self.treasurer)
        # cost 30000, accumulated 2400, book 27600 -> gain 1400
        self.assertEqual(Account.system(Account.SYS_DISPOSAL).balance(), D("1400.00"))
        self.assertEqual(self.vehicles.balance(), D("0.00"))
        self.assertEqual(self.accum.balance(), D("0.00"))

    def test_disposal_requires_depreciation_to_be_current(self):
        a = self.asset()
        with self.assertRaisesMessage(LedgerError, "Record depreciation"):
            services.dispose_asset(a, date=date(2026, 6, 30), proceeds=0, deposit_account=None, user=self.treasurer)
