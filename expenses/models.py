from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.models import Document
from core.utils import MoneySum, today
from ledger.models import Account, Fund, JournalEntry, money_field

ZERO = Decimal("0.00")


class Vendor(models.Model):
    """Anyone the church pays: suppliers, utilities, contractors, or a member being reimbursed."""

    name = models.CharField(max_length=150, unique=True)
    contact_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    tax_id = models.CharField("Tax ID", max_length=40, blank=True)
    is_1099 = models.BooleanField(
        "Requires year-end tax form", default=False,
        help_text="e.g. US Form 1099-NEC for contractors and guest speakers paid $600 or more.",
    )
    default_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Pre-filled on new expenses for this vendor.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("expenses:vendor_detail", args=[self.pk])

    def total_paid(self, start=None, end=None):
        qs = ExpensePayment.objects.filter(expense__vendor=self, is_void=False)
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        return qs.aggregate(t=MoneySum("amount"))["t"] or ZERO


class Expense(models.Model):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    PARTIAL = "partial"
    PAID = "paid"
    REJECTED = "rejected"
    VOID = "void"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (PENDING, "Awaiting approval"),
        (APPROVED, "Approved – unpaid"),
        (PARTIAL, "Partially paid"),
        (PAID, "Paid"),
        (REJECTED, "Rejected"),
        (VOID, "Void"),
    ]
    EDITABLE = {DRAFT, PENDING, REJECTED}
    OPEN_BALANCE = {APPROVED, PARTIAL}

    BILL = "bill"
    REIMBURSEMENT = "reimbursement"
    CHECK_REQUEST = "check_request"
    TYPE_CHOICES = [
        (BILL, "Bill / invoice"),
        (REIMBURSEMENT, "Reimbursement request"),
        (CHECK_REQUEST, "Cheque / payment request"),
    ]

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="expenses", verbose_name="Payee")
    expense_type = models.CharField("Type", max_length=15, choices=TYPE_CHOICES, default=BILL)
    date = models.DateField(default=today, help_text="Invoice or purchase date.")
    due_date = models.DateField(null=True, blank=True)
    reference = models.CharField("Invoice / receipt #", max_length=60, blank=True)
    description = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    total = money_field(editable=False)
    amount_paid = money_field(editable=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    journal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    documents = GenericRelation(Document)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.number} {self.vendor} – {self.description}"

    @property
    def number(self):
        return f"EX-{self.pk:05d}" if self.pk else "EX-new"

    def get_absolute_url(self):
        return reverse("expenses:expense_detail", args=[self.pk])

    @property
    def balance_due(self):
        if self.status not in self.OPEN_BALANCE:
            return ZERO
        return self.total - self.amount_paid

    @property
    def is_editable(self):
        return self.status in self.EDITABLE

    @property
    def is_overdue(self):
        return self.status in self.OPEN_BALANCE and self.due_date and self.due_date < today()

    def recalculate_total(self):
        self.total = self.lines.aggregate(t=MoneySum("amount"))["t"] or ZERO

    def refresh_payment_status(self):
        self.amount_paid = self.payments.filter(is_void=False).aggregate(t=MoneySum("amount"))["t"] or ZERO
        if self.status in (self.APPROVED, self.PARTIAL, self.PAID):
            if self.amount_paid <= 0:
                self.status = self.APPROVED
            elif self.amount_paid < self.total:
                self.status = self.PARTIAL
            else:
                self.status = self.PAID

    def fund_totals(self):
        totals = {}
        for line in self.lines.select_related("fund"):
            totals[line.fund] = totals.get(line.fund, ZERO) + line.amount
        return totals


class ExpenseLine(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="expense_lines")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="expense_lines")
    description = models.CharField(max_length=255, blank=True)
    amount = money_field(validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.account} {self.amount}"


class ExpensePayment(models.Model):
    CHECK = "check"
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"
    CASH = "cash"
    MOBILE_MONEY = "mobile_money"
    OTHER = "other"
    METHOD_CHOICES = [
        (CHECK, "Cheque"), (BANK_TRANSFER, "Bank transfer / EFT"), (CARD, "Debit / credit card"),
        (CASH, "Cash"), (MOBILE_MONEY, "M-Pesa / mobile money"), (OTHER, "Other"),
    ]

    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField(default=today)
    amount = money_field(validators=[MinValueValidator(Decimal("0.01"))])
    pay_from = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+", verbose_name="Paid from")
    method = models.CharField(max_length=15, choices=METHOD_CHOICES, default=CHECK)
    reference = models.CharField("Cheque / M-Pesa ref", max_length=60, blank=True)
    memo = models.CharField(max_length=255, blank=True)
    journal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_void = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]

    def __str__(self):
        return f"Payment {self.amount} for {self.expense.number}"
