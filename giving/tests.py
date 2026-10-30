from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.testing import ChurchTestCase, D
from ledger.models import JournalEntry
from ledger.services import LedgerError

from .models import Campaign, Contribution, ContributionBatch, Donor, Pledge
from .services import post_batch, unpost_batch
from .views import statement_data


class BatchTests(ChurchTestCase):
    def setUp(self):
        self.donor = Donor.objects.create(first_name="Ann", last_name="Lee", envelope_number="101")
        self.batch = ContributionBatch.objects.create(date=date(2026, 3, 1), description="Sunday", deposit_account=self.checking)

    def give(self, amount, fund=None, account=None, donor="default", **kw):
        return Contribution.objects.create(
            batch=self.batch, donor=self.donor if donor == "default" else donor, date=self.batch.date,
            fund=fund or self.gen, account=account or self.tithes, amount=D(str(amount)), **kw,
        )

    def test_posting_creates_fund_balanced_deposit(self):
        self.give(100)
        self.give(40, fund=self.bld, account=self.building_income)
        self.give(12.5, donor=None, method="cash")
        batch = post_batch(self.batch, self.bookkeeper)
        self.assertEqual(batch.status, ContributionBatch.POSTED)
        self.assertEqual(self.checking.balance(), D("152.50"))
        self.assertEqual(self.checking.balance(fund=self.bld), D("40.00"))
        self.assertEqual(self.bld.balance(), D("40.00"))
        self.assertEqual(batch.journal_entry.source_type, JournalEntry.SOURCE_GIVING)

    def test_control_total_must_match(self):
        self.give(100)
        self.batch.control_total = D("110")
        self.batch.save()
        with self.assertRaisesMessage(LedgerError, "do not match"):
            post_batch(self.batch, self.bookkeeper)

    def test_empty_batch_cannot_post(self):
        with self.assertRaises(LedgerError):
            post_batch(self.batch, self.bookkeeper)

    def test_reopen_voids_entry_and_allows_edits(self):
        self.give(100)
        batch = post_batch(self.batch, self.bookkeeper)
        entry = batch.journal_entry
        unpost_batch(batch, self.bookkeeper)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.VOID)
        self.assertEqual(batch.status, ContributionBatch.OPEN)
        self.assertEqual(self.checking.balance(), 0)

    def test_statements_include_posted_gifts_only(self):
        self.give(100)
        self.give(25, is_deductible=False, memo="Dinner ticket")
        self.assertEqual(statement_data(date(2026, 1, 1), date(2026, 12, 31)), [])
        post_batch(self.batch, self.bookkeeper)
        [s] = statement_data(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(s["total"], D("125.00"))
        self.assertEqual(s["deductible"], D("100.00"))

    def test_pledge_progress(self):
        campaign = Campaign.objects.create(name="Build", fund=self.bld, start_date=date(2026, 1, 1), goal=D("1000"))
        pledge = Pledge.objects.create(donor=self.donor, campaign=campaign, amount=D("500"), pledge_date=date(2026, 1, 1))
        self.give(200, fund=self.bld, account=self.building_income)
        self.give(50)  # general fund gift doesn't count
        post_batch(self.batch, self.bookkeeper)
        self.assertEqual(pledge.fulfilled, D("200.00"))
        self.assertEqual(pledge.remaining, D("300.00"))
        self.assertEqual(campaign.percent_of_goal, D("20"))

    def test_counter_can_enter_gifts_but_not_post(self):
        self.client.force_login(self.counter)
        url = reverse("giving:batch_detail", args=[self.batch.pk])
        response = self.client.post(url, {
            "donor": self.donor.pk, "fund": self.gen.pk, "account": self.tithes.pk, "amount": "75.00", "method": "check",
            "check_number": "123", "is_deductible": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.batch.total, D("75.00"))
        self.assertEqual(self.client.post(reverse("giving:batch_post", args=[self.batch.pk])).status_code, 403)
        self.client.force_login(self.bookkeeper)
        self.client.post(reverse("giving:batch_post", args=[self.batch.pk]))
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ContributionBatch.POSTED)

    def test_posted_batch_cannot_be_edited(self):
        c = self.give(100)
        post_batch(self.batch, self.bookkeeper)
        self.client.force_login(self.bookkeeper)
        self.client.post(reverse("giving:contribution_delete", args=[c.pk]))
        self.assertTrue(Contribution.objects.filter(pk=c.pk).exists())


class DonorTests(ChurchTestCase):
    def test_display_and_sort_names(self):
        org = Donor.objects.create(donor_type=Donor.ORGANIZATION, organization_name="Acme Foundation")
        person = Donor.objects.create(first_name="John & Mary", last_name="Banda", envelope_number="")
        self.assertEqual(org.display_name, "Acme Foundation")
        self.assertEqual(person.sort_name, "banda, john & mary")
        self.assertIsNone(person.envelope_number)

    def test_csv_import_skips_duplicates(self):
        self.client.force_login(self.bookkeeper)
        csv = b"First Name,Last Name,Email,Envelope,City\nAnn,Lee,ann@example.com,201,Lusaka\nBen,Moyo,,202,Ndola\n"
        for _ in range(2):
            self.client.post(reverse("giving:donor_import"), {"file": SimpleUploadedFile("donors.csv", csv, "text/csv")})
        self.assertEqual(Donor.objects.count(), 2)
        self.assertEqual(Donor.objects.get(envelope_number="201").city, "Lusaka")
