"""
General ledger: chart of accounts, funds and double-entry journal entries.

Every module (giving, expenses, payroll, fixed assets...) records its money
movements here as balanced journal entries. Every journal line carries a fund,
and every entry must balance within each fund, so the books can always produce
a balance sheet and fund balances per fund (true fund accounting).
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse

from core.models import Document
from core.utils import MoneySum

ZERO = Decimal("0.00")


def money_field(**kwargs):
    kwargs.setdefault("max_digits", 14)
    kwargs.setdefault("decimal_places", 2)
    kwargs.setdefault("default", ZERO)
    return models.DecimalField(**kwargs)


class Account(models.Model):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"
    TYPE_CHOICES = [
        (ASSET, "Asset"),
        (LIABILITY, "Liability"),
        (EQUITY, "Net Assets"),
        (INCOME, "Income"),
        (EXPENSE, "Expense"),
    ]
    DEBIT_NORMAL = {ASSET, EXPENSE}

    SUBTYPES = {
        ASSET: [
            ("bank", "Bank account"),
            ("cash", "Cash on hand / petty cash"),
            ("receivable", "Receivable"),
            ("other_current_asset", "Other current asset"),
            ("investment", "Investment"),
            ("fixed_asset", "Property & equipment"),
            ("accumulated_depreciation", "Accumulated depreciation"),
            ("other_asset", "Other asset"),
        ],
        LIABILITY: [
            ("payable", "Accounts payable"),
            ("credit_card", "Credit card"),
            ("payroll_liability", "Payroll liability"),
            ("other_current_liability", "Other current liability"),
            ("long_term_liability", "Long-term debt"),
        ],
        EQUITY: [
            ("net_assets", "Net assets"),
            ("transfers", "Interfund transfers"),
        ],
        INCOME: [
            ("contributions", "Contributions"),
            ("program_income", "Program & ministry income"),
            ("other_income", "Other income"),
        ],
        EXPENSE: [
            ("personnel", "Personnel"),
            ("facilities", "Facilities"),
            ("ministry", "Ministries & programs"),
            ("missions", "Missions & benevolence"),
            ("administration", "Administration"),
            ("other_expense", "Other expense"),
        ],
    }
    SUBTYPE_CHOICES = [
        ("Asset", SUBTYPES[ASSET]),
        ("Liability", SUBTYPES[LIABILITY]),
        ("Net Assets", SUBTYPES[EQUITY]),
        ("Income", SUBTYPES[INCOME]),
        ("Expense", SUBTYPES[EXPENSE]),
    ]
    SUBTYPE_LABELS = dict(SUBTYPES[ASSET] + SUBTYPES[LIABILITY] + SUBTYPES[EQUITY] + SUBTYPES[INCOME] + SUBTYPES[EXPENSE])
    CASH_SUBTYPES = {"bank", "cash"}
    PAYMENT_SUBTYPES = {"bank", "cash", "credit_card"}

    PROGRAM = "program"
    MANAGEMENT = "management"
    FUNDRAISING = "fundraising"
    FUNCTION_CHOICES = [
        (PROGRAM, "Program services (ministry)"),
        (MANAGEMENT, "Management & general"),
        (FUNDRAISING, "Fundraising"),
    ]

    # System accounts the application posts to automatically.
    SYS_AP = "accounts_payable"
    SYS_NET_ASSETS = "net_assets_unrestricted"
    SYS_NET_ASSETS_RESTRICTED = "net_assets_restricted"
    SYS_INTERFUND = "interfund_transfers"
    SYS_DEPRECIATION = "depreciation_expense"
    SYS_ACCUM_DEPRECIATION = "accumulated_depreciation"
    SYS_DISPOSAL = "asset_disposal"
    SYSTEM_CODE_CHOICES = [
        (SYS_AP, "Accounts payable"),
        (SYS_NET_ASSETS, "Net assets without donor restrictions"),
        (SYS_NET_ASSETS_RESTRICTED, "Net assets with donor restrictions"),
        (SYS_INTERFUND, "Interfund transfers"),
        (SYS_DEPRECIATION, "Depreciation expense"),
        (SYS_ACCUM_DEPRECIATION, "Accumulated depreciation"),
        (SYS_DISPOSAL, "Gain / loss on asset disposal"),
    ]

    number = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    subtype = models.CharField(max_length=30, choices=SUBTYPE_CHOICES)
    function = models.CharField(
        "Functional class", max_length=12, choices=FUNCTION_CHOICES, blank=True,
        help_text="Expense accounts only: used for the statement of functional expenses.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    system_code = models.CharField(
        max_length=40, choices=SYSTEM_CODE_CHOICES, unique=True, null=True, blank=True, editable=False,
    )
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_last4 = models.CharField("Last 4 digits", max_length=4, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"{self.number} · {self.name}"

    def get_absolute_url(self):
        return reverse("ledger:account_detail", args=[self.pk])

    def clean(self):
        valid = {code for code, _ in self.SUBTYPES.get(self.type, [])}
        if self.subtype and self.subtype not in valid:
            raise ValidationError({"subtype": "This subtype does not belong to the selected account type."})
        if self.type != self.EXPENSE:
            self.function = ""

    @property
    def is_debit_normal(self):
        return self.type in self.DEBIT_NORMAL

    @property
    def is_cash(self):
        return self.subtype in self.CASH_SUBTYPES

    @property
    def is_balance_sheet(self):
        return self.type in {self.ASSET, self.LIABILITY, self.EQUITY}

    @property
    def subtype_label(self):
        return self.SUBTYPE_LABELS.get(self.subtype, self.subtype)

    def signed(self, debit, credit):
        debit, credit = debit or ZERO, credit or ZERO
        return debit - credit if self.is_debit_normal else credit - debit

    def balance(self, end=None, start=None, fund=None):
        qs = self.lines.filter(entry__status=JournalEntry.POSTED)
        if end:
            qs = qs.filter(entry__date__lte=end)
        if start:
            qs = qs.filter(entry__date__gte=start)
        if fund:
            qs = qs.filter(fund=fund)
        totals = qs.aggregate(dr=MoneySum("debit"), cr=MoneySum("credit"))
        return self.signed(totals["dr"], totals["cr"])

    @property
    def has_activity(self):
        return self.lines.exists()

    @classmethod
    def system(cls, code):
        return cls.objects.get(system_code=code)

    @classmethod
    def payment_accounts(cls):
        return cls.objects.filter(is_active=True, subtype__in=cls.PAYMENT_SUBTYPES)

    @classmethod
    def deposit_accounts(cls):
        return cls.objects.filter(is_active=True, subtype__in=cls.CASH_SUBTYPES)


class Fund(models.Model):
    UNRESTRICTED = "unrestricted"
    DESIGNATED = "designated"
    RESTRICTED = "restricted"
    RESTRICTION_CHOICES = [
        (UNRESTRICTED, "Without donor restrictions"),
        (DESIGNATED, "Board-designated (without donor restrictions)"),
        (RESTRICTED, "With donor restrictions"),
    ]

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100, unique=True)
    restriction = models.CharField(max_length=15, choices=RESTRICTION_CHOICES, default=UNRESTRICTED)
    description = models.TextField(blank=True, help_text="Purpose of the fund and any donor restrictions.")
    default_income_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        limit_choices_to={"type": Account.INCOME},
        help_text="Pre-selected income account when recording gifts to this fund.",
    )
    is_default = models.BooleanField(
        "General (operating) fund", default=False,
        help_text="Used by default for everyday income and expenses.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "code"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("ledger:fund_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Fund.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    @property
    def has_donor_restrictions(self):
        return self.restriction == self.RESTRICTED

    @property
    def net_asset_account(self):
        code = Account.SYS_NET_ASSETS_RESTRICTED if self.has_donor_restrictions else Account.SYS_NET_ASSETS
        return Account.system(code)

    @classmethod
    def default(cls):
        return cls.objects.filter(is_active=True).order_by("-is_default", "code").first()

    def balance(self, end=None):
        """Fund balance (net assets) = credits minus debits on net asset, income and expense lines."""
        qs = JournalLine.objects.filter(
            fund=self, entry__status=JournalEntry.POSTED,
            account__type__in=[Account.EQUITY, Account.INCOME, Account.EXPENSE],
        )
        if end:
            qs = qs.filter(entry__date__lte=end)
        totals = qs.aggregate(dr=MoneySum("debit"), cr=MoneySum("credit"))
        return (totals["cr"] or ZERO) - (totals["dr"] or ZERO)


class JournalEntry(models.Model):
    DRAFT = "draft"
    POSTED = "posted"
    VOID = "void"
    STATUS_CHOICES = [(DRAFT, "Draft"), (POSTED, "Posted"), (VOID, "Void")]

    SOURCE_MANUAL = "manual"
    SOURCE_GIVING = "giving"
    SOURCE_EXPENSE = "expense"
    SOURCE_PAYMENT = "payment"
    SOURCE_PAYROLL = "payroll"
    SOURCE_DEPRECIATION = "depreciation"
    SOURCE_DISPOSAL = "disposal"
    SOURCE_TRANSFER = "transfer"
    SOURCE_FUND_TRANSFER = "fund_transfer"
    SOURCE_INCOME = "income"
    SOURCE_OPENING = "opening"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Journal entry"),
        (SOURCE_GIVING, "Contribution deposit"),
        (SOURCE_EXPENSE, "Expense / bill"),
        (SOURCE_PAYMENT, "Expense payment"),
        (SOURCE_PAYROLL, "Payroll"),
        (SOURCE_DEPRECIATION, "Depreciation"),
        (SOURCE_DISPOSAL, "Asset disposal"),
        (SOURCE_TRANSFER, "Bank transfer"),
        (SOURCE_FUND_TRANSFER, "Fund transfer"),
        (SOURCE_INCOME, "Other income"),
        (SOURCE_OPENING, "Opening balances"),
    ]

    date = models.DateField(db_index=True)
    memo = models.CharField(max_length=255)
    reference = models.CharField(max_length=60, blank=True, help_text="Check number, deposit slip, invoice...")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=POSTED, db_index=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL, db_index=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    posted_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)
    documents = GenericRelation(Document)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "journal entries"

    def __str__(self):
        return f"{self.number} {self.memo}"

    @property
    def number(self):
        return f"JE-{self.pk:05d}" if self.pk else "JE-new"

    def get_absolute_url(self):
        return reverse("ledger:entry_detail", args=[self.pk])

    @property
    def total(self):
        return self.lines.aggregate(t=MoneySum("debit"))["t"] or ZERO

    @property
    def is_editable(self):
        return self.status == self.DRAFT and self.source_type == self.SOURCE_MANUAL

    @property
    def is_reconciled(self):
        return self.lines.filter(reconciliation__status=Reconciliation.COMPLETED).exists()

    def source_url(self):
        """Link back to the document that created this entry."""
        routes = {
            self.SOURCE_GIVING: "giving:batch_detail",
            self.SOURCE_EXPENSE: "expenses:expense_detail",
            self.SOURCE_PAYROLL: "payroll:run_detail",
            self.SOURCE_DEPRECIATION: "fixedassets:run_detail",
            self.SOURCE_DISPOSAL: "fixedassets:asset_detail",
        }
        if self.source_type == self.SOURCE_PAYMENT and self.source_id:
            from expenses.models import ExpensePayment

            payment = ExpensePayment.objects.filter(pk=self.source_id).first()
            return payment.expense.get_absolute_url() if payment else None
        if self.source_type in routes and self.source_id:
            return reverse(routes[self.source_type], args=[self.source_id])
        return None


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="lines")
    description = models.CharField(max_length=255, blank=True)
    debit = money_field()
    credit = money_field()
    reconciliation = models.ForeignKey(
        "Reconciliation", null=True, blank=True, on_delete=models.SET_NULL, related_name="lines",
    )

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["account", "fund"])]
        constraints = [
            models.CheckConstraint(condition=Q(debit__gte=0) & Q(credit__gte=0), name="journal_line_non_negative"),
        ]

    def __str__(self):
        return f"{self.account} {self.debit or ''} {self.credit or ''}"

    @property
    def amount(self):
        return self.debit - self.credit


class Reconciliation(models.Model):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    STATUS_CHOICES = [(IN_PROGRESS, "In progress"), (COMPLETED, "Completed")]

    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="reconciliations")
    statement_date = models.DateField()
    statement_balance = money_field(help_text="Ending balance printed on the bank statement.")
    beginning_balance = money_field()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=IN_PROGRESS)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    documents = GenericRelation(Document)

    class Meta:
        ordering = ["-statement_date", "-id"]

    def __str__(self):
        return f"{self.account.name} — {self.statement_date:%b %d, %Y}"

    def get_absolute_url(self):
        return reverse("ledger:reconciliation_detail", args=[self.pk])

    def cleared_total(self):
        totals = self.lines.filter(entry__status=JournalEntry.POSTED).aggregate(dr=MoneySum("debit"), cr=MoneySum("credit"))
        return self.account.signed(totals["dr"], totals["cr"])

    @property
    def cleared_balance(self):
        return self.beginning_balance + self.cleared_total()

    @property
    def difference(self):
        return self.statement_balance - self.cleared_balance


class Budget(models.Model):
    DRAFT = "draft"
    APPROVED = "approved"
    STATUS_CHOICES = [(DRAFT, "Draft"), (APPROVED, "Approved")]

    fiscal_year = models.PositiveIntegerField(help_text="Calendar year in which the fiscal year starts.")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="budgets")
    name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fiscal_year", "fund__code"]
        unique_together = [("fiscal_year", "fund")]

    def __str__(self):
        from core.utils import fiscal_year_label

        return self.name or f"{fiscal_year_label(self.fiscal_year)} {self.fund.name} budget"

    def get_absolute_url(self):
        return reverse("ledger:budget_detail", args=[self.pk])

    def totals(self):
        income = expense = ZERO
        for line in self.lines.select_related("account"):
            if line.account.type == Account.INCOME:
                income += line.total
            else:
                expense += line.total
        return {"income": income, "expense": expense, "net": income - expense}


class BudgetLine(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="budget_lines")
    months = models.JSONField(default=list, help_text="Twelve monthly amounts in fiscal-month order.")

    class Meta:
        unique_together = [("budget", "account")]
        ordering = ["account__number"]

    def __str__(self):
        return f"{self.budget} · {self.account}"

    @property
    def month_amounts(self):
        values = [Decimal(str(v or "0")) for v in (self.months or [])]
        return (values + [ZERO] * 12)[:12]

    @property
    def total(self):
        return sum(self.month_amounts, ZERO)
