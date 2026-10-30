from datetime import date

from django.urls import reverse

from core.testing import ChurchTestCase, D
from expenses import services as ex
from expenses.models import Expense, ExpenseLine, Vendor
from ledger import services
from ledger.models import Account, Budget, BudgetLine

from . import builders


def row(report, label):
    return next(r.cells for r in report.rows if r.cells and r.cells[0] == label)


class ReportTests(ChurchTestCase):
    def setUp(self):
        services.record_opening_balances(date=date(2025, 12, 31), user=self.treasurer, rows=[
            (self.checking, self.gen, D("10000")), (self.savings, self.bld, D("50000")),
        ])
        self.deposit(3000, when=date(2026, 2, 1))
        self.deposit(1000, fund=self.bld, income=self.building_income, when=date(2026, 2, 1))
        vendor = Vendor.objects.create(name="Utility")
        expense = Expense.objects.create(vendor=vendor, date=date(2026, 2, 10), due_date=date(2026, 2, 20), description="Power",
                                         requested_by=self.bookkeeper)
        ExpenseLine.objects.create(expense=expense, account=self.utilities, fund=self.gen, amount=D("400"))
        ex.submit_expense(expense, self.bookkeeper)

    def test_balance_sheet_balances_in_every_layout(self):
        for mode in ("total", "restriction", "fund"):
            report = builders.balance_sheet(date(2026, 3, 1), mode)
            self.assertEqual(report.warnings, [])
            self.assertEqual(row(report, "Total assets")[-1], D("64000.00"))
            self.assertEqual(row(report, "Total liabilities")[-1], D("400.00"))
            self.assertEqual(row(report, "Total liabilities and net assets")[-1], D("64000.00"))

    def test_activities_ties_to_net_assets(self):
        report = builders.activities(date(2026, 1, 1), date(2026, 3, 31))
        self.assertEqual(row(report, "Total revenue")[-1], D("4000.00"))
        self.assertEqual(row(report, "Total expenses")[-1], D("400.00"))
        self.assertEqual(row(report, "Net assets, beginning of period")[-1], D("60000.00"))
        self.assertEqual(row(report, "Net assets, end of period")[-1], D("63600.00"))

    def test_trial_balance_balances(self):
        report = builders.trial_balance(date(2026, 3, 31))
        total = report.rows[-1].cells
        self.assertEqual(total[1], total[2])
        self.assertEqual(report.warnings, [])

    def test_budget_vs_actual(self):
        budget = Budget.objects.create(fiscal_year=2026, fund=self.gen)
        BudgetLine.objects.create(budget=budget, account=self.tithes, months=["1000"] * 12)
        BudgetLine.objects.create(budget=budget, account=self.utilities, months=["300"] * 12)
        report, idx = builders.budget_vs_actual(2026, self.gen, through_index=2)
        self.assertEqual(row(report, "Tithes")[1:4], [D("3000.00"), D("3000"), D("0.00")])
        self.assertEqual(row(report, "Utilities")[1:4], [D("400.00"), D("900"), D("500.00")])

    def test_ap_aging_matches_ledger(self):
        report = builders.ap_aging(date(2026, 4, 1))
        self.assertEqual(report.rows[-1].cells[-1], D("400.00"))
        self.assertEqual(report.rows[-1].cells[3], D("400.00"))  # due Feb 20: 31-60 days overdue
        self.assertEqual(Account.system(Account.SYS_AP).balance(), D("400.00"))

    def test_every_report_renders_and_exports(self):
        self.client.force_login(self.admin)
        names = ["balance_sheet", "activities", "budget_vs_actual", "trial_balance", "general_ledger", "fund_activity",
                 "functional_expenses", "monthly_trend", "cash_summary", "giving_summary", "donor_giving", "lapsed_donors",
                 "ap_aging", "payments_by_payee", "tax_form_payees", "payroll_summary", "payroll_liabilities"]
        for name in names:
            url = reverse(f"reports:{name}")
            self.assertEqual(self.client.get(url).status_code, 200, name)
            csv = self.client.get(url, {"export": "csv"})
            self.assertEqual(csv["Content-Type"], "text/csv", name)
