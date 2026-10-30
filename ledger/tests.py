from datetime import date

from django.urls import reverse

from core.models import ChurchProfile
from core.testing import ChurchTestCase, D

from . import services
from .models import Account, Budget, JournalEntry, Reconciliation
from .services import LedgerError


class PostingRulesTests(ChurchTestCase):
    def test_balanced_entry_posts_and_updates_balances(self):
        entry = self.deposit(250)
        self.assertEqual(entry.status, JournalEntry.POSTED)
        self.assertEqual(self.checking.balance(), D("250.00"))
        self.assertEqual(self.tithes.balance(), D("250.00"))
        self.assertEqual(self.gen.balance(), D("250.00"))

    def test_unbalanced_entry_is_rejected(self):
        with self.assertRaisesMessage(LedgerError, "must be equal"):
            services.create_entry(date=date(2026, 1, 5), memo="bad", lines=[
                self.line(self.checking, self.gen, debit=100), self.line(self.tithes, self.gen, credit=90),
            ])
        self.assertFalse(JournalEntry.objects.exists())

    def test_each_fund_must_balance(self):
        with self.assertRaisesMessage(LedgerError, "Each fund must balance"):
            services.create_entry(date=date(2026, 1, 5), memo="cross-fund", lines=[
                self.line(self.checking, self.gen, debit=100), self.line(self.tithes, self.bld, credit=100),
            ])

    def test_line_cannot_have_debit_and_credit(self):
        with self.assertRaises(LedgerError):
            services.validate_lines([self.line(self.checking, self.gen, debit=5, credit=5), self.line(self.tithes, self.gen, credit=5)])

    def test_negative_amounts_rejected(self):
        with self.assertRaises(LedgerError):
            services.validate_lines([self.line(self.checking, self.gen, debit=-5), self.line(self.tithes, self.gen, debit=5)])

    def test_rounds_to_cents(self):
        entry = self.deposit("10.005")
        self.assertEqual(entry.total, D("10.01"))

    def test_lock_date_blocks_new_and_void(self):
        entry = self.deposit(100, when=date(2026, 1, 10))
        profile = ChurchProfile.get()
        profile.lock_date = date(2026, 1, 31)
        profile.save()
        with self.assertRaisesMessage(LedgerError, "closed through"):
            self.deposit(100, when=date(2026, 1, 15))
        with self.assertRaisesMessage(LedgerError, "closed through"):
            services.void_entry(entry, self.treasurer, "test")
        self.deposit(100, when=date(2026, 2, 1))  # open period still works

    def test_void_removes_entry_from_balances(self):
        entry = self.deposit(100)
        services.void_entry(entry, self.treasurer, "duplicate")
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.VOID)
        self.assertEqual(entry.void_reason, "duplicate")
        self.assertEqual(self.checking.balance(), D("0.00"))

    def test_drafts_do_not_affect_balances_until_posted(self):
        entry = services.create_entry(date=date(2026, 2, 1), memo="draft", status=JournalEntry.DRAFT, lines=[
            self.line(self.checking, self.gen, debit=40), self.line(self.tithes, self.gen, credit=40),
        ])
        self.assertEqual(self.checking.balance(), 0)
        services.post_entry(entry, self.treasurer)
        self.assertEqual(self.checking.balance(), D("40.00"))


class TransferTests(ChurchTestCase):
    def test_fund_transfer_keeps_each_fund_balanced(self):
        self.deposit(1000)
        services.record_fund_transfer(date=date(2026, 3, 2), from_fund=self.gen, to_fund=self.mis, amount=D("300"),
                                      cash_account=self.checking, user=self.treasurer)
        self.assertEqual(self.gen.balance(), D("700.00"))
        self.assertEqual(self.mis.balance(), D("300.00"))
        self.assertEqual(self.checking.balance(), D("1000.00"))
        self.assertEqual(self.checking.balance(fund=self.mis), D("300.00"))

    def test_bank_transfer_moves_cash_not_fund_balance(self):
        self.deposit(500, fund=self.bld, income=self.building_income)
        services.record_bank_transfer(date=date(2026, 3, 3), from_account=self.checking, to_account=self.savings,
                                      amount=D("500"), fund=self.bld, user=self.treasurer)
        self.assertEqual(self.checking.balance(), D("0.00"))
        self.assertEqual(self.savings.balance(fund=self.bld), D("500.00"))
        self.assertEqual(self.bld.balance(), D("500.00"))

    def test_opening_balances_use_restricted_net_assets_for_restricted_funds(self):
        services.record_opening_balances(date=date(2025, 12, 31), user=self.treasurer, rows=[
            (self.checking, self.gen, D("1000")), (self.savings, self.bld, D("5000")),
            (Account.objects.get(number="2500"), self.gen, D("400")),
        ])
        self.assertEqual(Account.system(Account.SYS_NET_ASSETS).balance(), D("600.00"))
        self.assertEqual(Account.system(Account.SYS_NET_ASSETS_RESTRICTED).balance(), D("5000.00"))


class ReconciliationTests(ChurchTestCase):
    def test_reconcile_and_protect_cleared_entries(self):
        e1 = self.deposit(100, when=date(2026, 1, 5))
        self.deposit(50, when=date(2026, 1, 20))
        rec = services.start_reconciliation(account=self.checking, statement_date=date(2026, 1, 31),
                                            statement_balance=D("100"), user=self.bookkeeper)
        services.set_cleared(rec, [e1.lines.get(account=self.checking).pk])
        self.assertEqual(rec.difference, D("0.00"))
        services.complete_reconciliation(rec, self.bookkeeper)
        with self.assertRaisesMessage(LedgerError, "reconciliation"):
            services.void_entry(e1, self.treasurer, "oops")
        nxt = services.start_reconciliation(account=self.checking, statement_date=date(2026, 2, 28),
                                            statement_balance=D("150"), user=self.bookkeeper)
        self.assertEqual(nxt.beginning_balance, D("100.00"))
        self.assertEqual(services.reconciliation_candidates(nxt).count(), 1)

    def test_cannot_finish_out_of_balance(self):
        self.deposit(100, when=date(2026, 1, 5))
        rec = services.start_reconciliation(account=self.checking, statement_date=date(2026, 1, 31),
                                            statement_balance=D("90"), user=self.bookkeeper)
        with self.assertRaisesMessage(LedgerError, "out of balance"):
            services.complete_reconciliation(rec, self.bookkeeper)
        self.assertEqual(rec.status, Reconciliation.IN_PROGRESS)


class LedgerViewTests(ChurchTestCase):
    def test_manual_journal_entry_form(self):
        self.client.force_login(self.bookkeeper)
        data = {
            "date": "2026-04-01", "memo": "Reclass", "reference": "ADJ-1",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "2", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": self.repairs.pk, "lines-0-fund": self.gen.pk, "lines-0-debit": "75.00",
            "lines-1-account": self.utilities.pk, "lines-1-fund": self.gen.pk, "lines-1-credit": "75.00",
            "post": "1",
        }
        response = self.client.post(reverse("ledger:entry_create"), data)
        entry = JournalEntry.objects.get()
        self.assertRedirects(response, entry.get_absolute_url())
        self.assertEqual(entry.status, JournalEntry.POSTED)
        self.assertEqual(self.repairs.balance(), D("75.00"))

    def test_unbalanced_form_shows_error(self):
        self.client.force_login(self.bookkeeper)
        data = {
            "date": "2026-04-01", "memo": "Bad",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "2", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": self.repairs.pk, "lines-0-fund": self.gen.pk, "lines-0-debit": "75.00",
            "lines-1-account": self.utilities.pk, "lines-1-fund": self.gen.pk, "lines-1-credit": "70.00",
        }
        response = self.client.post(reverse("ledger:entry_create"), data)
        self.assertContains(response, "must be equal")
        self.assertFalse(JournalEntry.objects.exists())

    def test_budget_grid_save(self):
        self.client.force_login(self.treasurer)
        budget = Budget.objects.create(fiscal_year=2026, fund=self.gen)
        data = {f"a{self.tithes.pk}_m{i}": "1000" for i in range(12)}
        data[f"a{self.utilities.pk}_m0"] = "250.50"
        self.client.post(reverse("ledger:budget_detail", args=[budget.pk]), data)
        totals = budget.totals()
        self.assertEqual(totals["income"], D("12000"))
        self.assertEqual(totals["expense"], D("250.50"))
