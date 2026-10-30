from datetime import date

from core.testing import ChurchTestCase, D
from ledger.models import Account
from ledger.services import LedgerError

from . import services
from .forms import BandsField
from .models import Employee, EmployeePayrollItem, PayrollItem, PayrollRun

KENYA_STATUTORY = ["NSSF – Employee", "SHIF", "Housing Levy – Employee", "PAYE", "NSSF – Employer", "Housing Levy – Employer"]


class KenyanPayrollTests(ChurchTestCase):
    """The default (Kenya) preset: PAYE bands with personal relief, NSSF cap, SHIF minimum, Housing Levy."""

    def setUp(self):
        self.deposit(1_000_000)
        self.items = {i.name: i for i in PayrollItem.objects.all()}

    def employee(self, monthly, **kw):
        e = Employee.objects.create(
            first_name="Jane", last_name="Wanjiru", pay_frequency=kw.pop("pay_frequency", "monthly"),
            annual_salary=D(monthly) * 12, wage_account=Account.objects.get(number="5010"), fund=self.gen, **kw,
        )
        for name in KENYA_STATUTORY:
            EmployeePayrollItem.objects.create(employee=e, item=self.items[name], amount=self.items[name].default_amount)
        return e

    def make_run(self, start=date(2026, 3, 1), end=date(2026, 3, 31)):
        return services.create_run(period_start=start, period_end=end, pay_date=end, bank_account=self.checking, user=self.treasurer)

    def amounts(self, paycheck):
        return {l.item.name: l.amount for l in paycheck.lines.select_related("item")}

    def test_monthly_salary_of_100k(self):
        e = self.employee("100000")
        pc = self.make_run().paychecks.get(employee=e)
        a = self.amounts(pc)
        self.assertEqual(a["NSSF – Employee"], D("4320.00"))  # 6% capped at 4,320
        self.assertEqual(a["SHIF"], D("2750.00"))  # 2.75%
        self.assertEqual(a["Housing Levy – Employee"], D("1500.00"))  # 1.5%
        # Taxable 91,430: 2,400 + 2,083.25 + 17,729.10 - 2,400 relief
        self.assertEqual(a["PAYE"], D("19812.35"))
        self.assertEqual(pc.net, D("71617.65"))
        self.assertEqual(pc.employer_cost, D("5820.00"))

    def test_low_earner_gets_shif_minimum_and_no_paye(self):
        e = self.employee("10000")
        a = self.amounts(self.make_run().paychecks.get(employee=e))
        self.assertEqual(a["SHIF"], D("300.00"))
        self.assertEqual(a["NSSF – Employee"], D("600.00"))
        self.assertEqual(a["PAYE"], D("0.00"))

    def test_bands_and_caps_prorate_for_twice_monthly_pay(self):
        e = self.employee("100000", pay_frequency="semimonthly")
        pc = self.make_run(end=date(2026, 3, 15)).paychecks.get(employee=e)
        a = self.amounts(pc)
        self.assertEqual(pc.gross, D("50000.00"))
        self.assertEqual(a["NSSF – Employee"], D("2160.00"))
        self.assertEqual(a["PAYE"], D("9906.18"))  # half of the monthly figure, rounded

    def test_posting_records_wages_liabilities_and_net_pay(self):
        e = self.employee("100000")
        run = services.post_run(self.make_run(), self.treasurer)
        self.assertEqual(run.status, PayrollRun.POSTED)
        self.assertEqual(Account.objects.get(number="5010").balance(), D("100000.00"))
        self.assertEqual(Account.objects.get(number="5030").balance(), D("5820.00"))
        self.assertEqual(Account.objects.get(number="2110").balance(), D("19812.35"))  # PAYE
        self.assertEqual(Account.objects.get(number="2100").balance(), D("8640.00"))  # NSSF both shares
        self.assertEqual(Account.objects.get(number="2130").balance(), D("3000.00"))  # Housing Levy both shares
        self.assertEqual(self.checking.balance(), D("1000000") - D("71617.65"))
        with self.assertRaises(LedgerError):
            services.post_run(run, self.treasurer)
        self.assertTrue(e.paychecks.exists())

    def test_manual_adjustment_and_void(self):
        e = self.employee("50000")
        run = self.make_run()
        pc = run.paychecks.get(employee=e)
        amounts = {l.item: l.amount for l in pc.lines.select_related("item")}
        amounts[self.items["Other Allowances"]] = D("5000")
        services.save_paycheck_amounts(pc, amounts, check_number="MPESA123")
        self.assertEqual(pc.gross, D("55000.00"))
        run = services.post_run(run, self.treasurer)
        services.void_run(run, self.treasurer)
        self.assertEqual(self.checking.balance(), D("1000000.00"))

    def test_deductions_cannot_exceed_gross(self):
        e = self.employee("20000")
        pc = self.make_run().paychecks.get(employee=e)
        amounts = {l.item: l.amount for l in pc.lines.select_related("item")}
        amounts[self.items["SACCO / Welfare Deduction"]] = D("50000")
        with self.assertRaises(LedgerError):
            services.save_paycheck_amounts(pc, amounts)

    def test_untaxed_earnings_are_left_out_of_the_wage_base(self):
        housing = self.items["Housing Allowance"]
        housing.in_wage_base = False  # e.g. a US clergy housing allowance
        housing.save()
        e = self.employee("40000", annual_housing_allowance=D("120000"))
        a = self.amounts(self.make_run().paychecks.get(employee=e))
        self.assertEqual(a["Housing Allowance"], D("10000.00"))
        self.assertEqual(a["SHIF"], D("1100.00"))  # 2.75% of 40,000 only


class BandsFieldTests(ChurchTestCase):
    def test_parses_text_bands(self):
        field = BandsField()
        self.assertEqual(field.clean("24000, 10\n32,333, 25\n, 35"), [[24000.0, 10.0], [32333.0, 25.0], [None, 35.0]])
        self.assertEqual(field.prepare_value([[24000, 10], [None, 35]]), "24000, 10\n, 35")

    def test_rejects_out_of_order_bands(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            BandsField().clean("50000, 30\n24000, 10")
