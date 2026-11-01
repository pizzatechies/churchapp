"""
Linking the church's bank and M-Pesa accounts to Ecclesia.

A bank or cash account in the chart of accounts can be *linked* in one of two ways:

* **Statement upload**: download a statement from online banking (CSV or OFX) and
  upload it. Works with every bank.
* **M-Pesa Paybill or Till (live)**: Safaricom sends each payment to Ecclesia the
  moment it is received (the Daraja C2B API).

Either way the money in and out arrives as `BankTransaction`s. Each one is matched
to what is already in the books, recorded (as a gift, other income or spending), or
ignored, so the books and the bank always agree.
"""

import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse

from ledger.models import Account, Fund, JournalEntry, money_field


def new_token():
    return secrets.token_urlsafe(24)


class BankConnection(models.Model):
    STATEMENT = "statement"
    MPESA = "mpesa"
    METHOD_CHOICES = [
        (STATEMENT, "Upload statements from online banking (any bank)"),
        (MPESA, "M-Pesa Paybill or Till, live from Safaricom"),
    ]

    account = models.OneToOneField(
        Account, on_delete=models.CASCADE, related_name="bank_connection",
        limit_choices_to={"subtype__in": ["bank", "cash"]},
    )
    method = models.CharField(max_length=12, choices=METHOD_CHOICES, default=STATEMENT)
    shortcode = models.CharField(
        "Paybill or Till number", max_length=12, blank=True,
        help_text="The business short code payments are made to, e.g. 247247.",
    )
    token = models.CharField(max_length=64, unique=True, default=new_token, editable=False)
    auto_record_gifts = models.BooleanField(
        "Record payments as gifts automatically", default=True,
        help_text="Each payment is added to an open offering batch for the day, matched to a giver by "
                  "envelope number or phone. The batch is still checked and posted by the finance team.",
    )
    default_fund = models.ForeignKey(
        Fund, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Used when the account number a giver typed doesn't name a fund.",
    )
    default_income_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        limit_choices_to={"type": Account.INCOME}, verbose_name="Default category",
    )
    registered_at = models.DateTimeField(null=True, blank=True, help_text="When the address was registered with Safaricom.")
    last_received_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account.name} ({self.get_method_display()})"

    def get_absolute_url(self):
        return reverse("bankfeeds:feed", args=[self.account_id])

    @property
    def is_live(self):
        return self.method == self.MPESA


class StatementImport(models.Model):
    connection = models.ForeignKey(BankConnection, on_delete=models.CASCADE, related_name="imports")
    file_name = models.CharField(max_length=255)
    added = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0, help_text="Lines already imported before.")
    first_date = models.DateField(null=True, blank=True)
    last_date = models.DateField(null=True, blank=True)
    closing_balance = money_field(null=True, blank=True, default=None)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]


class BankTransaction(models.Model):
    NEW = "new"
    MATCHED = "matched"
    RECORDED = "recorded"
    IGNORED = "ignored"
    STATUS_CHOICES = [(NEW, "To review"), (MATCHED, "Matched"), (RECORDED, "Recorded as a gift"), (IGNORED, "Ignored")]

    IMPORT = "import"
    LIVE = "live"
    SOURCE_CHOICES = [(IMPORT, "Statement"), (LIVE, "Live")]

    connection = models.ForeignKey(BankConnection, on_delete=models.CASCADE, related_name="transactions")
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="bank_transactions")
    statement_import = models.ForeignKey(StatementImport, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions")
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=IMPORT)
    external_id = models.CharField(max_length=80, help_text="Bank reference, M-Pesa receipt or a fingerprint of the line.")
    date = models.DateField(db_index=True)
    amount = money_field(help_text="Money in is positive, money out negative.")
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=60, blank=True)
    payer_name = models.CharField(max_length=150, blank=True)
    payer_phone = models.CharField(max_length=40, blank=True)
    account_reference = models.CharField(max_length=60, blank=True, help_text="What the payer typed as the account number.")
    balance = money_field(null=True, blank=True, default=None)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=NEW, db_index=True)
    journal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="bank_transactions")
    contribution = models.OneToOneField(
        "giving.Contribution", null=True, blank=True, on_delete=models.SET_NULL, related_name="bank_transaction",
    )
    auto_matched = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["account", "external_id"], name="bank_txn_unique_per_account"),
            # One bank line per journal entry on each account; a transfer can match a line on each side.
            models.UniqueConstraint(fields=["account", "journal_entry"], condition=Q(journal_entry__isnull=False),
                                    name="bank_txn_one_entry_per_account"),
        ]

    def __str__(self):
        return f"{self.date} {self.amount} {self.description}"

    @property
    def money_in(self):
        return self.amount > 0
