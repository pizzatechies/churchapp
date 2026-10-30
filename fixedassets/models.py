from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse

from core.utils import MoneySum
from ledger.models import Account, Fund, JournalEntry, money_field

ZERO = Decimal("0.00")


class FixedAsset(models.Model):
    CATEGORY_CHOICES = [
        ("land", "Land"),
        ("building", "Buildings"),
        ("improvement", "Building improvements"),
        ("furniture", "Furniture & fixtures"),
        ("equipment", "Equipment"),
        ("av", "Sound, video & musical instruments"),
        ("technology", "Computers & technology"),
        ("vehicle", "Vehicles"),
        ("other", "Other"),
    ]
    SUGGESTED_LIFE_YEARS = {
        "land": 0, "building": 40, "improvement": 15, "furniture": 7, "equipment": 7,
        "av": 5, "technology": 3, "vehicle": 5, "other": 5,
    }
    ACTIVE = "active"
    DISPOSED = "disposed"
    STATUS_CHOICES = [(ACTIVE, "In service"), (DISPOSED, "Disposed")]

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default="equipment")
    description = models.TextField(blank=True)
    tag_number = models.CharField("Asset tag", max_length=40, blank=True)
    serial_number = models.CharField(max_length=80, blank=True)
    location = models.CharField(max_length=100, blank=True)
    acquisition_date = models.DateField()
    in_service_date = models.DateField(help_text="Depreciation starts in this month.")
    cost = money_field()
    salvage_value = money_field(help_text="Expected value at the end of its useful life.")
    useful_life_months = models.PositiveIntegerField(
        default=60, help_text="0 means the asset is not depreciated (e.g. land).",
    )
    asset_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                      limit_choices_to={"subtype": "fixed_asset"})
    accumulated_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                            limit_choices_to={"subtype": "accumulated_depreciation"},
                                            verbose_name="Accumulated depreciation account")
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                        limit_choices_to={"type": Account.EXPENSE},
                                        verbose_name="Depreciation expense account")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_proceeds = money_field()
    disposal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    prior_depreciation = money_field(
        verbose_name="Depreciation before this system",
        help_text="For assets you already owned: accumulated depreciation recorded in your old books.",
    )
    prior_depreciation_through = models.DateField(
        "Prior depreciation recorded through", null=True, blank=True,
        help_text="Month-end the prior depreciation covers. Depreciation here starts the month after.",
    )
    depreciated_through = models.DateField(null=True, blank=True, editable=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("fixedassets:asset_detail", args=[self.pk])

    @property
    def depreciable_base(self):
        return max(ZERO, self.cost - self.salvage_value)

    @property
    def monthly_depreciation(self):
        if not self.useful_life_months:
            return ZERO
        return (self.depreciable_base / self.useful_life_months).quantize(Decimal("0.01"))

    @property
    def accumulated_depreciation(self):
        recorded = self.depreciation_entries.filter(run__is_void=False).aggregate(t=MoneySum("amount"))["t"] or ZERO
        return self.prior_depreciation + recorded

    @property
    def book_value(self):
        return self.cost - self.accumulated_depreciation

    @property
    def fully_depreciated(self):
        return self.useful_life_months == 0 or self.accumulated_depreciation >= self.depreciable_base


class DepreciationRun(models.Model):
    through_date = models.DateField(help_text="Depreciation is recorded for every month up to and including this one.")
    journal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_void = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-through_date", "-id"]

    def __str__(self):
        return f"Depreciation through {self.through_date:%b %Y}"

    def get_absolute_url(self):
        return reverse("fixedassets:run_detail", args=[self.pk])

    @property
    def total(self):
        return self.entries.aggregate(t=MoneySum("amount"))["t"] or ZERO


class DepreciationEntry(models.Model):
    run = models.ForeignKey(DepreciationRun, on_delete=models.CASCADE, related_name="entries")
    asset = models.ForeignKey(FixedAsset, on_delete=models.CASCADE, related_name="depreciation_entries")
    months = models.PositiveIntegerField()
    amount = money_field()
    period_start = models.DateField()
    period_end = models.DateField()

    class Meta:
        ordering = ["asset__name"]

    def __str__(self):
        return f"{self.asset} {self.amount}"
