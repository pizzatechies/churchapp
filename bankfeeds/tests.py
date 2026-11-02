"""Linking bank and M-Pesa accounts: statements, matching, recording and live M-Pesa payments."""

import json
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from core.testing import ChurchTestCase
from giving.models import Contribution, ContributionBatch, Donor
from ledger.models import Account, JournalEntry

from . import daraja, services
from .models import BankConnection, BankTransaction
from .parsers import StatementError, parse_csv, parse_ofx, parse_statement

D = Decimal

EQUITY_CSV = """Equity Bank Limited
Account Statement
Account Name:,LIFESOURCE CHURCH
Account Number:,0123456789
Period:,01/03/2026 - 31/03/2026

Transaction Date,Value Date,Narrative,Debit,Credit,Running Balance
02/03/2026,02/03/2026,CASH DEPOSIT SUNDAY OFFERING,,"5,000.00","105,000.00"
05/03/2026,05/03/2026,LEDGER FEE,150.00,,"104,850.00"
05/03/2026,05/03/2026,LEDGER FEE,150.00,,"104,700.00"
,,Closing balance,,,"104,700.00"
"""

MPESA_CSV = """Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance,Other Party Info
SC12ABC345,2026-03-08 10:15:02,Pay Bill from 2547******678 - JANE WANJIKU Acc. 101,Completed,2500.00,,12500.00,2547******678 - JANE WANJIKU
SC12ABC346,2026-03-08 10:20:00,Pay Bill Online,Failed,999.00,,12500.00,
"""

OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260302120000<TRNAMT>5000.00<FITID>FT2603021<NAME>CASH DEPOSIT
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260305<TRNAMT>-150.00<FITID>FT2603052<NAME>LEDGER FEE<MEMO>Monthly fee
</BANKTRANLIST><LEDGERBAL><BALAMT>104850.00<DTASOF>20260331</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


class ParserTests(ChurchTestCase):
    def test_bank_csv_with_preamble_and_money_in_out_columns(self):
        lines = parse_csv(EQUITY_CSV)
        self.assertEqual([(l.date, l.amount) for l in lines],
                         [(date(2026, 3, 2), D("5000.00")), (date(2026, 3, 5), D("-150.00")), (date(2026, 3, 5), D("-150.00"))])
        self.assertEqual(lines[0].balance, D("105000.00"))
        # Two identical fees on one day are two lines, each with its own fingerprint.
        self.assertNotEqual(lines[1].external_id, lines[2].external_id)
        self.assertEqual(parse_csv(EQUITY_CSV)[2].external_id, lines[2].external_id)

    def test_mpesa_portal_statement(self):
        lines = parse_csv(MPESA_CSV)
        self.assertEqual(len(lines), 1)  # the failed payment is skipped
        self.assertEqual(lines[0].reference, "SC12ABC345")
        self.assertEqual(lines[0].payer_name, "JANE WANJIKU")
        self.assertEqual(lines[0].date, date(2026, 3, 8))

    def test_ofx(self):
        lines = parse_ofx(OFX)
        self.assertEqual([l.amount for l in lines], [D("5000.00"), D("-150.00")])
        self.assertEqual(lines[1].description, "LEDGER FEE · Monthly fee")
        self.assertEqual(lines[-1].raw["closing_balance"], "104850.00")

    def test_unreadable_files_explain_themselves(self):
        with self.assertRaisesMessage(StatementError, "CSV"):
            parse_statement("statement.xlsx", b"PK...")
        with self.assertRaisesMessage(StatementError, "column headings"):
            parse_statement("statement.csv", b"hello,world\n1,2\n")


class FeedTests(ChurchTestCase):
    def setUp(self):
        self.connection = BankConnection.objects.create(account=self.checking, method=BankConnection.STATEMENT)
        self.fees = Account.objects.get(number="8040")

    def test_import_matches_entries_already_in_the_books(self):
        entry = self.deposit(5000, when=date(2026, 3, 1))  # the Sunday offering, recorded the day before it was banked
        imp = services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode(), self.treasurer)
        self.assertEqual((imp.added, imp.matched), (3, 1))
        self.assertEqual(imp.closing_balance, D("104700.00"))
        line = BankTransaction.objects.get(amount=D("5000.00"))
        self.assertEqual((line.status, line.journal_entry, line.auto_matched), (BankTransaction.MATCHED, entry, True))
        again = services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode(), self.treasurer)
        self.assertEqual((again.added, again.skipped), (0, 3))

    def test_ambiguous_lines_wait_for_a_person(self):
        first = self.deposit(5000, when=date(2026, 3, 1))
        self.deposit(5000, when=date(2026, 3, 3))
        services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode())
        line = BankTransaction.objects.get(amount=D("5000.00"))
        self.assertEqual(line.status, BankTransaction.NEW)
        self.assertEqual(len(services.match_candidates(line)), 2)
        services.match(line, first, self.bookkeeper)
        other = BankTransaction.objects.create(connection=self.connection, account=self.checking, external_id="x",
                                               date=date(2026, 3, 2), amount=D("5000.00"))
        with self.assertRaisesMessage(services.FeedError, "already matched"):
            services.match(other, first)

    def test_record_bank_charges_and_undo(self):
        services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode())
        fee = BankTransaction.objects.filter(amount=D("-150.00")).first()
        entry = services.record_entry(fee, self.fees, self.gen, self.bookkeeper)
        self.assertEqual(entry.source_type, JournalEntry.SOURCE_BANK_FEED)
        self.assertEqual(self.checking.balance(), D("-150.00"))
        self.assertEqual(self.fees.balance(), D("150.00"))
        with self.assertRaisesMessage(services.FeedError, "spending category"):
            services.record_entry(BankTransaction.objects.filter(amount=D("-150.00"), status="new").first(), self.tithes, self.gen)
        services.undo(fee, self.bookkeeper)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.VOID)
        self.assertEqual(self.checking.balance(), D("0.00"))

    def test_money_in_can_be_added_to_the_days_gift_batch(self):
        donor = Donor.objects.create(first_name="Jane", last_name="Wanjiku", envelope_number="101")
        services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode())
        line = BankTransaction.objects.get(amount=D("5000.00"))
        gift = services.record_gift(line, self.bld, self.building_income, donor=donor, user=self.bookkeeper)
        self.assertEqual((gift.batch.status, gift.batch.deposit_account, gift.amount), (ContributionBatch.OPEN, self.checking, D("5000.00")))
        services.undo(line)
        self.assertFalse(Contribution.objects.exists())

    def test_screens_and_permissions(self):
        self.client.force_login(self.counter)
        self.assertEqual(self.client.get(reverse("bankfeeds:feed", args=[self.checking.pk])).status_code, 403)
        self.client.force_login(self.bookkeeper)
        services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode())
        page = self.client.get(reverse("bankfeeds:feed", args=[self.checking.pk]))
        self.assertContains(page, "LEDGER FEE")
        self.assertEqual(self.client.get(reverse("bankfeeds:link", args=[self.checking.pk])).status_code, 403)
        fee = BankTransaction.objects.filter(amount=D("-150.00")).first()
        self.client.post(reverse("bankfeeds:line_action", args=[fee.pk]),
                         {"action": "record", "category": self.fees.pk, "fund": self.gen.pk})
        fee.refresh_from_db()
        self.assertEqual(fee.status, BankTransaction.MATCHED)
        self.assertContains(self.client.get(reverse("ledger:banking")), "2 to review")

    def test_upload_through_the_screen(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.bookkeeper)
        response = self.client.post(reverse("bankfeeds:import", args=[self.checking.pk]),
                                    {"file": SimpleUploadedFile("march.ofx", OFX.encode(), "application/x-ofx")}, follow=True)
        self.assertContains(response, "Imported 2 lines")
        self.assertEqual(BankTransaction.objects.count(), 2)

    def test_reconciliation_can_tick_what_the_feed_confirms(self):
        from ledger.services import start_reconciliation

        self.deposit(5000, when=date(2026, 3, 1))
        services.import_statement(self.connection, "march.csv", EQUITY_CSV.encode())
        rec = start_reconciliation(account=self.checking, statement_date=date(2026, 3, 31), statement_balance=D("5000"), user=self.treasurer)
        self.client.force_login(self.treasurer)
        page = self.client.get(rec.get_absolute_url())
        self.assertContains(page, "Tick items the bank feed confirms")
        self.assertContains(page, "data-feed")

    def test_treasurer_links_an_account(self):
        BankConnection.objects.all().delete()
        self.client.force_login(self.treasurer)
        self.assertContains(self.client.get(reverse("ledger:banking")), "Link account")
        self.client.post(reverse("bankfeeds:link", args=[self.savings.pk]), {"method": "mpesa", "shortcode": "12ab"})
        self.assertFalse(BankConnection.objects.exists())
        self.client.post(reverse("bankfeeds:link", args=[self.savings.pk]),
                         {"method": "mpesa", "shortcode": "247247", "auto_record_gifts": "on", "default_fund": self.gen.pk, "default_income_account": self.tithes.pk})
        connection = BankConnection.objects.get()
        page = self.client.get(reverse("bankfeeds:link", args=[self.savings.pk]))
        self.assertContains(page, f"/bank-feed/c2b/{connection.token}/confirm/")


@override_settings(MPESA_CONSUMER_KEY="key", MPESA_CONSUMER_SECRET="secret", MPESA_ENVIRONMENT="sandbox")
class MpesaTests(ChurchTestCase):
    def setUp(self):
        self.mpesa = Account.objects.create(number="1030", name="M-Pesa Paybill 247247", type=Account.ASSET, subtype="bank")
        self.connection = BankConnection.objects.create(
            account=self.mpesa, method=BankConnection.MPESA, shortcode="247247", default_fund=self.gen, default_income_account=self.tithes,
        )
        self.donor = Donor.objects.create(first_name="Jane", last_name="Wanjiku", envelope_number="101")
        self.url = reverse("c2b_confirm", args=[self.connection.token])

    def payment(self, **kw):
        data = {"TransactionType": "Pay Bill", "TransID": "SC12ABC345", "TransTime": "20260308101502", "TransAmount": "2500.00",
                "BusinessShortCode": "247247", "BillRefNumber": "101 BLD", "MSISDN": "2547 ***** 678",
                "FirstName": "JANE", "MiddleName": "", "LastName": "WANJIKU"}
        data.update(kw)
        return self.client.post(self.url, json.dumps(data), content_type="application/json")

    def test_payment_arrives_as_a_gift_from_the_right_person_to_the_right_fund(self):
        response = self.payment()
        self.assertEqual(response.json(), {"ResultCode": 0, "ResultDesc": "Accepted"})
        line = BankTransaction.objects.get()
        self.assertEqual((line.amount, line.date, line.payer_name, line.status), (D("2500.00"), date(2026, 3, 8), "Jane Wanjiku", BankTransaction.RECORDED))
        gift = line.contribution
        self.assertEqual((gift.donor, gift.fund, gift.account, gift.method, gift.check_number),
                         (self.donor, self.bld, self.building_income, Contribution.MOBILE_MONEY, "SC12ABC345"))
        self.assertEqual(gift.batch.description, "M-Pesa gifts · 08 Mar 2026")
        self.payment()  # Safaricom sometimes repeats a notice
        self.assertEqual(BankTransaction.objects.count(), 1)
        self.payment(TransID="SC12ABC999", BillRefNumber="tithe", TransAmount="100")
        second = BankTransaction.objects.get(reference="SC12ABC999").contribution
        self.assertEqual((second.donor, second.fund, second.batch), (None, self.gen, gift.batch))

    def test_portal_statement_does_not_repeat_live_payments(self):
        self.payment()
        imp = services.import_statement(self.connection, "portal.csv", MPESA_CSV.encode())
        self.assertEqual((imp.added, imp.skipped), (0, 1))
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_callbacks_reject_strangers(self):
        bad = self.client.post(reverse("c2b_confirm", args=["not-the-token"]), "{}", content_type="application/json")
        self.assertEqual(bad.status_code, 404)
        self.assertEqual(self.client.post(reverse("c2b_validate", args=[self.connection.token]), "{}", content_type="application/json").json()["ResultCode"], 0)
        with override_settings(MPESA_ALLOWED_IPS=["196.201.214.200"]):
            self.assertEqual(self.payment().status_code, 404)
            self.assertEqual(self.client.post(self.url, "{}", content_type="application/json", HTTP_X_FORWARDED_FOR="196.201.214.200").status_code, 200)

    def test_payments_are_left_for_review_when_auto_recording_is_off(self):
        self.connection.auto_record_gifts = False
        self.connection.save()
        self.payment()
        self.assertEqual(BankTransaction.objects.get().status, BankTransaction.NEW)

    def test_register_with_safaricom(self):
        calls = []

        def fake(url, data=None, headers=None):
            calls.append((url, data))
            return {"access_token": "t"} if "oauth" in url else {"ResponseCode": "0", "ResponseDescription": "Success"}

        self.client.force_login(self.treasurer)
        with mock.patch.object(daraja, "_request", side_effect=fake):
            self.client.post(reverse("bankfeeds:register", args=[self.mpesa.pk]), {"environment": "sandbox"})
        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.registered_at)
        self.assertTrue(calls[1][0].startswith("https://sandbox.safaricom.co.ke/mpesa/c2b/"))
        self.assertEqual(calls[1][1]["ShortCode"], "247247")
        self.assertNotIn("mpesa", calls[1][1]["ConfirmationURL"].lower())
        with self.assertRaisesMessage(daraja.DarajaError, "must not contain"):
            daraja.register_urls("247247", "https://example.com/mpesa/confirm", "https://example.com/v")


    def test_till_payments_are_kept_even_though_safaricom_reports_the_store_number(self):
        self.payment(BusinessShortCode="5123456")
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_connection_test_notices_are_answered_but_not_recorded(self):
        response = self.client.post(self.url, json.dumps({"TransactionType": daraja.TEST_TRANSACTION_TYPE, "TransID": "ECCLESIA-TEST"}),
                                    content_type="application/json")
        self.assertEqual(response.json()["ResultCode"], 0)
        self.assertFalse(BankTransaction.objects.exists())

    @override_settings(MPESA_CONSUMER_KEY="", MPESA_CONSUMER_SECRET="")
    def test_each_church_registers_with_its_own_keys_and_older_apps_fall_back_to_v1(self):
        calls = []

        def fake(url, data=None, headers=None, timeout=25):
            calls.append(url)
            if "oauth" in url:
                return {"access_token": "t"}
            if "/v2/" in url:
                err = daraja.DarajaError("Not found")
                err.status = 404
                raise err
            return {"ResponseCode": "0", "ResponseDescription": "success"}

        self.client.force_login(self.treasurer)
        page = self.client.get(reverse("bankfeeds:link", args=[self.mpesa.pk]))
        self.assertContains(page, "never saved")
        with mock.patch.object(daraja, "_request", side_effect=fake):
            self.client.post(reverse("bankfeeds:register", args=[self.mpesa.pk]),
                             {"consumer_key": "church-key", "consumer_secret": "church-secret", "environment": "production"}, secure=True)
        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.registered_at)
        self.assertEqual([u.split(".co.ke")[1].split("?")[0] for u in calls],
                         ["/oauth/v1/generate", "/mpesa/c2b/v2/registerurl", "/mpesa/c2b/v1/registerurl"])
        self.assertFalse(BankConnection.objects.filter(pk=self.connection.pk, shortcode__contains="key").exists())

    def test_check_the_payment_address(self):
        self.client.force_login(self.treasurer)
        with mock.patch.object(daraja, "_request", return_value={"ResultCode": 0}):
            self.client.post(reverse("bankfeeds:check_address", args=[self.mpesa.pk]), secure=True)
        self.connection.refresh_from_db()
        self.assertTrue(self.connection.last_check_ok)
        with mock.patch.object(daraja, "_request", side_effect=daraja.DarajaError("timed out")):
            self.client.post(reverse("bankfeeds:check_address", args=[self.mpesa.pk]), secure=True)
        self.connection.refresh_from_db()
        self.assertFalse(self.connection.last_check_ok)
        self.assertIn("couldn't be reached", self.connection.last_check_note)

    def test_move_a_live_link_off_the_bank_current_account(self):
        BankConnection.objects.all().delete()
        conn = BankConnection.objects.create(account=self.checking, method=BankConnection.MPESA, shortcode="247247")
        self.client.force_login(self.treasurer)
        page = self.client.get(reverse("bankfeeds:link", args=[self.checking.pk]))
        self.assertContains(page, "Move the live link there")
        self.client.post(reverse("bankfeeds:move_link", args=[self.checking.pk]), {"target": "new"})
        conn.refresh_from_db()
        self.assertTrue(conn.account.name.startswith("M-Pesa Paybill 247247"))
        self.assertEqual((conn.account.subtype, conn.account.bank_name), ("bank", "Safaricom M-Pesa"))

    def test_add_mpesa_account_from_bank_accounts(self):
        self.mpesa.name = "Spare account"
        self.mpesa.save()
        self.client.force_login(self.treasurer)
        self.assertContains(self.client.get(reverse("ledger:banking")), "Add M-Pesa account")
        response = self.client.post(reverse("bankfeeds:add_mpesa_account"), {"shortcode": "123456"})
        account = Account.objects.get(name="M-Pesa Paybill 123456")
        self.assertRedirects(response, reverse("bankfeeds:link", args=[account.pk]) + "?method=mpesa")
