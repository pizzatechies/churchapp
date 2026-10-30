from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.models import Document
from core.utils import MoneySum
from ledger.models import Account, Fund, JournalEntry, money_field

ZERO = Decimal("0.00")


class Donor(models.Model):
    INDIVIDUAL = "individual"
    HOUSEHOLD = "household"
    ORGANIZATION = "organization"
    TYPE_CHOICES = [(INDIVIDUAL, "Individual"), (HOUSEHOLD, "Household / family"), (ORGANIZATION, "Organization / business")]

    donor_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default=INDIVIDUAL)
    first_name = models.CharField(max_length=80, blank=True, help_text="For households, e.g. “John & Mary”.")
    last_name = models.CharField(max_length=80, blank=True)
    organization_name = models.CharField(max_length=150, blank=True)
    envelope_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address_line1 = models.CharField("Address", max_length=150, blank=True)
    address_line2 = models.CharField("Address line 2", max_length=150, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField("State / province", max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=80, blank=True)
    is_member = models.BooleanField("Church member", default=False)
    member_since = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_name = models.CharField(max_length=200, editable=False, db_index=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_name"]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.envelope_number:
            self.envelope_number = None
        if self.donor_type == self.ORGANIZATION and self.organization_name:
            self.sort_name = self.organization_name.lower()
        else:
            self.sort_name = f"{self.last_name}, {self.first_name}".strip(", ").lower()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("giving:donor_detail", args=[self.pk])

    @property
    def display_name(self):
        if self.donor_type == self.ORGANIZATION and self.organization_name:
            return self.organization_name
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.organization_name or f"Donor #{self.pk}"

    @property
    def address_lines(self):
        city_line = " ".join(p for p in [f"{self.city}," if self.city else "", self.state, self.postal_code] if p).strip(", ")
        return [line for line in [self.address_line1, self.address_line2, city_line, self.country] if line]

    def posted_contributions(self):
        return self.contributions.filter(batch__status=ContributionBatch.POSTED)

    def total_given(self, start=None, end=None):
        qs = self.posted_contributions()
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        return qs.aggregate(t=MoneySum("amount"))["t"] or ZERO


class Campaign(models.Model):
    """A pledge drive, e.g. a building campaign or an annual stewardship campaign."""

    name = models.CharField(max_length=120)
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="campaigns")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    goal = money_field(null=True, blank=True, default=None)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("giving:campaign_detail", args=[self.pk])

    def contributions(self):
        qs = Contribution.objects.filter(batch__status=ContributionBatch.POSTED, fund=self.fund, date__gte=self.start_date)
        if self.end_date:
            qs = qs.filter(date__lte=self.end_date)
        return qs

    @property
    def total_pledged(self):
        return self.pledges.aggregate(t=MoneySum("amount"))["t"] or ZERO

    @property
    def total_received(self):
        return self.contributions().aggregate(t=MoneySum("amount"))["t"] or ZERO

    @property
    def received_from_pledgers(self):
        donors = self.pledges.values("donor_id")
        return self.contributions().filter(donor_id__in=donors).aggregate(t=MoneySum("amount"))["t"] or ZERO

    @property
    def percent_of_goal(self):
        if not self.goal:
            return None
        return min(Decimal(100), self.total_received / self.goal * 100)


class Pledge(models.Model):
    FREQUENCY_CHOICES = [
        ("once", "One-time"), ("weekly", "Weekly"), ("monthly", "Monthly"),
        ("quarterly", "Quarterly"), ("annually", "Annually"),
    ]

    donor = models.ForeignKey(Donor, on_delete=models.PROTECT, related_name="pledges")
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="pledges")
    amount = money_field(validators=[MinValueValidator(Decimal("0.01"))], help_text="Total amount pledged for the campaign.")
    pledge_date = models.DateField()
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default="monthly")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["donor__sort_name"]
        unique_together = [("donor", "campaign")]

    def __str__(self):
        return f"{self.donor} → {self.campaign}"

    @property
    def fulfilled(self):
        return self.campaign.contributions().filter(donor=self.donor).aggregate(t=MoneySum("amount"))["t"] or ZERO

    @property
    def remaining(self):
        return max(ZERO, self.amount - self.fulfilled)

    @property
    def percent(self):
        return min(Decimal(100), self.fulfilled / self.amount * 100) if self.amount else Decimal(0)


class ContributionBatch(models.Model):
    """One deposit: a Sunday offering count, a midweek deposit, or a month of online gifts."""

    OPEN = "open"
    POSTED = "posted"
    STATUS_CHOICES = [(OPEN, "Open"), (POSTED, "Posted")]

    date = models.DateField(help_text="Date the money was received / deposited.")
    description = models.CharField(max_length=150, help_text="e.g. “Sunday morning service” or “Online giving – March”.")
    deposit_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"subtype__in": ["bank", "cash"]},
    )
    control_total = money_field(
        null=True, blank=True, default=None,
        help_text="Total on the count sheet or deposit slip. The batch can only be posted when entries match it.",
    )
    counted_by = models.CharField(
        max_length=150, blank=True, help_text="Best practice: two unrelated people count every offering.",
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    journal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    posted_at = models.DateTimeField(null=True, blank=True)
    documents = GenericRelation(Document)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "contribution batches"

    def __str__(self):
        return f"{self.number} {self.description}"

    @property
    def number(self):
        return f"B-{self.pk:05d}" if self.pk else "B-new"

    def get_absolute_url(self):
        return reverse("giving:batch_detail", args=[self.pk])

    @property
    def total(self):
        return self.contributions.aggregate(t=MoneySum("amount"))["t"] or ZERO

    @property
    def is_open(self):
        return self.status == self.OPEN

    def totals_by_method(self):
        rows = self.contributions.values("method").annotate(total=MoneySum("amount"), count=models.Count("id")).order_by("method")
        labels = dict(Contribution.METHOD_CHOICES)
        return [(labels.get(r["method"], r["method"]), r["count"], r["total"]) for r in rows]

    def totals_by_fund(self):
        rows = self.contributions.values("fund__name").annotate(total=MoneySum("amount"), count=models.Count("id")).order_by("fund__name")
        return [(r["fund__name"], r["count"], r["total"]) for r in rows]


class Contribution(models.Model):
    CASH = "cash"
    CHECK = "check"
    CARD = "card"
    ONLINE = "online"
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    OTHER = "other"
    METHOD_CHOICES = [
        (CASH, "Cash"), (CHECK, "Cheque"), (CARD, "Card"), (ONLINE, "Online giving"),
        (BANK_TRANSFER, "Bank transfer / EFT"), (MOBILE_MONEY, "M-Pesa / mobile money"), (OTHER, "Other"),
    ]

    batch = models.ForeignKey(ContributionBatch, on_delete=models.CASCADE, related_name="contributions")
    donor = models.ForeignKey(Donor, null=True, blank=True, on_delete=models.PROTECT, related_name="contributions",
                              help_text="Leave blank for anonymous or loose offering.")
    date = models.DateField()
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="contributions")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="contributions",
                                limit_choices_to={"type": Account.INCOME}, verbose_name="Category")
    amount = money_field(validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=15, choices=METHOD_CHOICES, default=CHECK)
    check_number = models.CharField("Cheque / M-Pesa ref", max_length=40, blank=True)
    memo = models.CharField(max_length=255, blank=True)
    is_deductible = models.BooleanField(
        "Tax deductible", default=True,
        help_text="Untick if the donor received goods or services in return (e.g. a dinner ticket).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        indexes = [models.Index(fields=["donor", "date"])]

    def __str__(self):
        return f"{self.donor or 'Anonymous'} {self.amount} to {self.fund}"
