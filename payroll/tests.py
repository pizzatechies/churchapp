from datetime import date

from core.testing import ChurchTestCase, D
from ledger.models import Account
from ledger.services import LedgerError

from . import services
from .models import Employee, EmployeePayrollItem, PayrollItem, PayrollRun


class PayrollTests(ChurchTestCase):
    def setUp(self):
        self.deposit(20000)
        items = {i.name: i for i in PayrollItem.objects.all()}
        self.pastor = Employee.objects.create(
            first_name="Pat", last_name="Pastor", employee_type=Employee.CLERGY, pay_frequency="monthly",
            annual_salary=D("48000"), annual_housing_allowance=D("24000"),
            wage_account=Account.objects.get(number="5000"), fund=self.gen,
        )
        EmployeePayrollItem.objects.create(employee=self.pastor, item=items["Income Tax Withholding"], amount=D("10"))
        self.janitor = Employee.objects.create(
            first_name="Jo", last_name="Clean", pay_type=Employee.HOURLY, pay_frequency="biweekly",
            hourly_rate=D("15"), default_hours=D("40"), wage_account=Account.objects.get(number="5010"), fund=self.gen,
        )
        EmployeePayrollItem.objects.create(employee=self.janitor, item=items["Social Security – Employee"], amount=D("7.65"))
        EmployeePayrollItem.objects.create(employee=self.janitor, item=items["Social Security – Employer"], amount=D("7.65"))

    def make_run(self):
        return services.create_run(period_start=date(2026, 3, 1), period_end=date(2026, 3, 31), pay_date=date(2026, 3, 31),
                                   bank_account=self.checking, user=self.treasurer)

    def test_housing_allowance_is_excluded_from_percentage_wage_base(self):
        pc = self.make_run().paychecks.get(employee=self.pastor)
        self.assertEqual(pc.gross, D("6000.00"))  # 4000 salary + 2000 housing
        self.assertEqual(pc.deductions, D("400.00"))  # 10% of 4000 only
        self.assertEqual(pc.net, D("5600.00"))

    def test_hourly_pay_and_employer_taxes(self):
        pc = self.make_run().paychecks.get(employee=self.janitor)
        self.assertEqual(pc.gross, D("600.00"))
        self.assertEqual(pc.deductions, D("45.90"))
        self.assertEqual(pc.employer_cost, D("45.90"))

    def test_posting_records_expenses_liabilities_and_net_pay(self):
        run = services.post_run(self.make_run(), self.treasurer)
        self.assertEqual(run.status, PayrollRun.POSTED)
        self.assertEqual(Account.objects.get(number="5000").balance(), D("4000.00"))
        self.assertEqual(Account.objects.get(number="5020").balance(), D("2000.00"))
        self.assertEqual(Account.objects.get(number="5030").balance(), D("45.90"))
        self.assertEqual(Account.objects.get(number="2110").balance(), D("400.00"))
        self.assertEqual(Account.objects.get(number="2100").balance(), D("91.80"))
        self.assertEqual(self.checking.balance(), D("20000") - D("5600") - D("554.10"))
        with self.assertRaises(LedgerError):
            services.post_run(run, self.treasurer)

    def test_manual_adjustment_and_void(self):
        run = self.make_run()
        pc = run.paychecks.get(employee=self.janitor)
        amounts = {l.item: l.amount for l in pc.lines.select_related("item")}
        bonus = PayrollItem.objects.get(name="Bonus / Other Pay")
        amounts[bonus] = D("100")
        services.save_paycheck_amounts(pc, amounts, hours=D("40"), check_number="5001")
        self.assertEqual(pc.gross, D("700.00"))
        run = services.post_run(run, self.treasurer)
        services.void_run(run, self.treasurer)
        self.assertEqual(self.checking.balance(), D("20000.00"))

    def test_deductions_cannot_exceed_gross(self):
        pc = self.make_run().paychecks.get(employee=self.janitor)
        amounts = {l.item: l.amount for l in pc.lines.select_related("item")}
        amounts[PayrollItem.objects.get(name="Income Tax Withholding")] = D("1000")
        with self.assertRaises(LedgerError):
            services.save_paycheck_amounts(pc, amounts)
