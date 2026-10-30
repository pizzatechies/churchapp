from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

DEFAULT_STATEMENT_FOOTER = (
    "Thank you for your faithful generosity and partnership in the work of the ministry. "
    "Please keep this statement for your records."
)
US_STATEMENT_FOOTER = (
    "Thank you for your faithful generosity. No goods or services were provided in "
    "exchange for these contributions other than intangible religious benefits, "
    "unless otherwise noted. Please keep this statement for your tax records."
)

# Country presets: currency, statement wording and payroll defaults (see core/setup.py).
COUNTRY_CHOICES = [
    ("KE", "Kenya"), ("UG", "Uganda"), ("TZ", "Tanzania"), ("RW", "Rwanda"), ("ET", "Ethiopia"),
    ("NG", "Nigeria"), ("GH", "Ghana"), ("ZA", "South Africa"), ("ZM", "Zambia"), ("ZW", "Zimbabwe"),
    ("MW", "Malawi"), ("US", "United States"), ("CA", "Canada"), ("GB", "United Kingdom"),
    ("IE", "Ireland"), ("AU", "Australia"), ("NZ", "New Zealand"), ("IN", "India"), ("PH", "Philippines"),
    ("XX", "Other"),
]
CURRENCIES = {
    "KE": ("KES", "KSh"), "UG": ("UGX", "USh"), "TZ": ("TZS", "TSh"), "RW": ("RWF", "FRw"), "ET": ("ETB", "Br"),
    "NG": ("NGN", "₦"), "GH": ("GHS", "GH₵"), "ZA": ("ZAR", "R"), "ZM": ("ZMW", "K"), "ZW": ("USD", "$"),
    "MW": ("MWK", "MK"), "US": ("USD", "$"), "CA": ("CAD", "$"), "GB": ("GBP", "£"), "IE": ("EUR", "€"),
    "AU": ("AUD", "$"), "NZ": ("NZD", "$"), "IN": ("INR", "₹"), "PH": ("PHP", "₱"), "XX": ("USD", "$"),
}
# A sensible default "needs approval above" limit, roughly the same real value in each currency.
APPROVAL_THRESHOLDS = {
    "KES": 50000, "UGX": 1500000, "TZS": 1000000, "RWF": 500000, "ETB": 20000, "NGN": 500000, "GHS": 5000,
    "ZAR": 7500, "ZMW": 10000, "MWK": 650000, "INR": 30000, "PHP": 20000,
}

MONTH_CHOICES = [
    (1, "January"), (2, "February"), (3, "March"), (4, "April"), (5, "May"), (6, "June"),
    (7, "July"), (8, "August"), (9, "September"), (10, "October"), (11, "November"), (12, "December"),
]


class ChurchProfile(models.Model):
    """Organisation-wide settings. There is exactly one row (pk=1)."""

    CACHE_KEY = "church-profile"

    name = models.CharField(max_length=150, default="LifeSource Church")
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.CharField(max_length=150, blank=True)
    tax_id = models.CharField("Tax ID (e.g. KRA PIN, EIN)", max_length=40, blank=True)
    country = models.CharField(max_length=2, choices=COUNTRY_CHOICES, default="KE")
    currency_code = models.CharField(max_length=3, default="KES", help_text="ISO code, e.g. KES, UGX, NGN, USD.")
    currency_symbol = models.CharField(max_length=5, default="KSh", help_text="Shown before amounts, e.g. KSh, USh, ₦, $.")
    fiscal_year_start_month = models.PositiveSmallIntegerField(
        choices=MONTH_CHOICES, default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    lock_date = models.DateField(
        "Books closed through", null=True, blank=True,
        help_text="Transactions dated on or before this date can no longer be added, changed or voided.",
    )
    expense_approval_threshold = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("50000.00"),
        help_text="Expenses above this amount need approval from the finance committee, "
                  "treasurer or an administrator. Smaller expenses are approved automatically when submitted.",
    )
    require_separate_approver = models.BooleanField(
        default=True,
        help_text="Segregation of duties: people cannot approve expenses they requested themselves.",
    )
    statement_footer = models.TextField(
        "Giving statement message", default=DEFAULT_STATEMENT_FOOTER,
        help_text="Printed at the bottom of every contribution statement.",
    )
    treasurer_name = models.CharField(
        max_length=100, blank=True, help_text="Signs contribution statements and reports.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "church profile"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def get(cls):
        """Fresh copy from the database. Use this for anything that enforces rules."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def cached(cls):
        """Short-lived cached copy, fine for display purposes such as the currency symbol."""
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj = cls.get()
            cache.set(cls.CACHE_KEY, obj, 60)
        return obj


class AuditLog(models.Model):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ACTION_CHOICES = [(CREATE, "Created"), (UPDATE, "Changed"), (DELETE, "Deleted")]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    model = models.CharField(max_length=60, db_index=True)
    object_id = models.CharField(max_length=40)
    object_repr = models.CharField(max_length=200)
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        return f"{self.get_action_display()} {self.model} {self.object_repr}"


def document_upload_path(instance, filename):
    return f"documents/{instance.content_type.model}/{instance.object_id}/{filename}"


class Document(models.Model):
    """A file (receipt, invoice, bank statement, count sheet...) attached to any record."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    file = models.FileField(upload_to=document_upload_path)
    original_name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return self.original_name
