from datetime import date

from django.urls import reverse

from core.models import ChurchProfile
from core.testing import ChurchTestCase, D
from ledger.models import JournalEntry
from ledger.services import LedgerError

from . import services
from .models import Expense, ExpenseLine, Vendor


class ExpenseWorkflowTests(ChurchTestCase):
    def setUp(self):
        self.vendor = Vendor.objects.create(name="Power Co")
        self.deposit(5000)
        self.deposit(5000, fund=self.bld, income=self.building_income)

    def make(self, *lines, user=None):
        expense = Expense.objects.create(vendor=self.vendor, date=date(2026, 3, 5), description="Test", requested_by=user or self.bookkeeper)
        for account, fund, amount in lines:
            ExpenseLine.objects.create(expense=expense, account=account, fund=fund, amount=D(str(amount)))
        return expense

    def test_small_expense_is_auto_approved_and_posted_to_payables(self):
        expense = services.submit_expense(self.make((self.utilities, self.gen, 120)), self.bookkeeper)
        self.assertEqual(expense.status, Expense.APPROVED)
        self.assertEqual(self.ap.balance(), D("120.00"))
        self.assertEqual(self.utilities.balance(), D("120.00"))

    def test_large_expense_waits_for_approval(self):
        expense = services.submit_expense(self.make((self.repairs, self.gen, 2500)), self.bookkeeper)
        self.assertEqual(expense.status, Expense.PENDING)
        self.assertEqual(self.ap.balance(), 0)
        services.approve_expense(expense, self.treasurer, "ok")
        self.assertEqual(expense.status, Expense.APPROVED)
        self.assertEqual(expense.reviewed_by, self.treasurer)

    def test_requester_cannot_approve_own_expense(self):
        expense = services.submit_expense(self.make((self.repairs, self.gen, 2500), user=self.treasurer), self.treasurer)
        with self.assertRaisesMessage(LedgerError, "someone else"):
            services.approve_expense(expense, self.treasurer)
        profile = ChurchProfile.get()
        profile.require_separate_approver = False
        profile.save()
        services.approve_expense(expense, self.treasurer)

    def test_reject_requires_reason_and_allows_resubmit(self):
        expense = services.submit_expense(self.make((self.repairs, self.gen, 2500)), self.bookkeeper)
        with self.assertRaises(LedgerError):
            services.reject_expense(expense, self.treasurer, "")
        services.reject_expense(expense, self.treasurer, "Get a second quote")
        self.assertEqual(expense.status, Expense.REJECTED)
        services.submit_expense(expense, self.bookkeeper)
        self.assertEqual(expense.status, Expense.PENDING)

    def test_partial_payments_split_across_funds_exactly(self):
        expense = self.make((self.utilities, self.gen, "100.01"), (self.repairs, self.bld, "200.02"))
        services.submit_expense(expense, self.bookkeeper)
        services.record_payment(expense, self.bookkeeper, date=date(2026, 3, 10), amount=D("100"), pay_from=self.checking)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.PARTIAL)
        services.record_payment(expense, self.bookkeeper, date=date(2026, 3, 20), amount=D("200.03"), pay_from=self.checking)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.PAID)
        self.assertEqual(self.ap.balance(), D("0.00"))
        self.assertEqual(self.ap.balance(fund=self.gen), D("0.00"))
        self.assertEqual(self.ap.balance(fund=self.bld), D("0.00"))
        self.assertEqual(self.checking.balance(fund=self.bld), D("4799.98"))

    def test_cannot_overpay(self):
        expense = services.submit_expense(self.make((self.utilities, self.gen, 50)), self.bookkeeper)
        with self.assertRaisesMessage(LedgerError, "more than the balance due"):
            services.record_payment(expense, self.bookkeeper, date=date(2026, 3, 10), amount=D("50.01"), pay_from=self.checking)

    def test_void_payment_then_expense(self):
        expense = services.submit_expense(self.make((self.utilities, self.gen, 50)), self.bookkeeper)
        payment = services.record_payment(expense, self.bookkeeper, date=date(2026, 3, 10), amount=D("50"), pay_from=self.checking)
        with self.assertRaisesMessage(LedgerError, "Void the payments"):
            services.void_expense(expense, self.treasurer)
        services.void_payment(payment, self.treasurer)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.APPROVED)
        services.void_expense(expense, self.treasurer, "duplicate bill")
        self.assertEqual(expense.status, Expense.VOID)
        self.assertEqual(self.utilities.balance(), D("0.00"))
        self.assertEqual(JournalEntry.objects.filter(status=JournalEntry.VOID).count(), 2)

    def test_create_and_pay_now_from_form(self):
        self.client.force_login(self.bookkeeper)
        response = self.client.post(reverse("expenses:expense_create"), {
            "vendor": self.vendor.pk, "expense_type": "bill", "date": "2026-03-05", "description": "Light bulbs",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "1", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": self.repairs.pk, "lines-0-fund": self.gen.pk, "lines-0-amount": "42.50",
            "pay-paid": "on", "pay-pay_from": self.checking.pk, "pay-method": "card", "submit": "1",
        })
        expense = Expense.objects.get()
        self.assertRedirects(response, expense.get_absolute_url())
        self.assertEqual(expense.status, Expense.PAID)
        self.assertEqual(self.checking.balance(fund=self.gen), D("4957.50"))

    def test_viewer_cannot_open_expenses(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("expenses:expense_list")).status_code, 403)
