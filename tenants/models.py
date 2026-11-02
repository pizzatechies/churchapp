"""
The Ecclesia platform: the churches Pizza Technologies hosts, their plans and payments.

Every church gets its own PostgreSQL schema (via django-tenants), so one church's
records can never appear in another's. These platform tables live in the shared
"public" schema, which only the platform super admins sign in to.
"""

import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django_tenants.models import DomainMixin, TenantMixin

from core.utils import add_months

RESERVED_SLUGS = {"platform", "static", "media", "admin", "api", "www", "church", "public", "healthz", "login"}


class Plan(models.Model):
    code = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    tagline = models.CharField(max_length=120, blank=True)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    yearly_months = models.PositiveSmallIntegerField(
        default=10, help_text="Paying yearly costs this many months (10 = two months free).",
    )
    max_members = models.PositiveIntegerField(null=True, blank=True, help_text="Empty for unlimited.")
    max_staff = models.PositiveIntegerField("Staff logins", null=True, blank=True, help_text="Empty for unlimited.")
    storage_gb = models.PositiveIntegerField("Storage (GB)", default=20)
    custom_domains = models.BooleanField("Own web addresses", default=False)
    support = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "monthly_price"]

    def __str__(self):
        return self.name

    @property
    def yearly_price(self):
        return self.monthly_price * self.yearly_months


slug_validator = RegexValidator(r"^[a-z0-9](?:[a-z0-9-]{0,40}[a-z0-9])?$", "Use lowercase letters, numbers and hyphens, e.g. lifesource.")


class Church(TenantMixin):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [(TRIAL, "Free trial"), (ACTIVE, "Active"), (SUSPENDED, "Suspended"), (CANCELLED, "Cancelled")]

    MONTHLY = "monthly"
    YEARLY = "yearly"
    CYCLE_CHOICES = [(MONTHLY, "Monthly"), (YEARLY, "Yearly")]

    name = models.CharField(max_length=150)
    slug = models.SlugField(
        "Web address name", max_length=42, unique=True, validators=[slug_validator],
        help_text="The church's addresses end in /church/<this name>/.",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="churches")
    billing_cycle = models.CharField(max_length=10, choices=CYCLE_CHOICES, default=MONTHLY)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=TRIAL, db_index=True)
    trial_ends = models.DateField(null=True, blank=True)
    paid_until = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=2, default="KE")
    contact_name = models.CharField(max_length=120, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    suspended_reason = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(
        "Served at the main addresses", default=False,
        help_text="This church also opens at the apps' plain addresses (without /church/...), for apps set up before churches had their own addresses.",
    )
    usage = models.JSONField(default=dict, blank=True)
    usage_updated_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True
    auto_drop_schema = False  # never: cancelling keeps the records

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "churches"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            Church.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @staticmethod
    def schema_for(slug):
        return "church_" + re.sub(r"[^a-z0-9]", "_", slug)[:55]

    # ---------------------------------------------------------- billing state

    @property
    def price(self):
        return self.plan.yearly_price if self.billing_cycle == self.YEARLY else self.plan.monthly_price

    @property
    def monthly_value(self):
        """What the church is worth per month, for monthly recurring revenue."""
        return (self.plan.yearly_price / 12).quantize(Decimal("0.01")) if self.billing_cycle == self.YEARLY else self.plan.monthly_price

    @property
    def is_accessible(self):
        return self.status not in (self.SUSPENDED, self.CANCELLED)

    @property
    def due_date(self):
        if self.paid_until:
            return self.paid_until
        return self.trial_ends

    @property
    def days_overdue(self):
        due = self.due_date
        if not self.is_accessible or due is None:
            return 0
        return max(0, (timezone.localdate() - due).days)

    @property
    def state(self):
        """(code, label) including the derived 'overdue' and 'trial ended' states."""
        if not self.is_accessible:
            return self.status, self.get_status_display()
        if self.days_overdue:
            return "overdue", ("Trial ended" if self.status == self.TRIAL and not self.paid_until else "Overdue")
        return self.status, self.get_status_display()

    @property
    def payment_due_soon(self):
        due = self.due_date
        return bool(due and self.is_accessible and 0 <= (due - timezone.localdate()).days <= 7)

    def extend(self, months, start=None):
        """Move paid_until forward by whole months, from the later of today and the current paid-up date."""
        today = timezone.localdate()
        start = start or max(today, (self.paid_until + timedelta(days=1)) if self.paid_until else today)
        self.paid_until = add_months(start, months) - timedelta(days=1)
        if self.status == self.TRIAL:
            self.status = self.ACTIVE
        return start, self.paid_until


class Domain(DomainMixin):
    """Optional own web address for a church (Kingdom plan), e.g. members.yourchurch.org."""

    class Meta:
        ordering = ["domain"]


class Payment(models.Model):
    MPESA = "mpesa"
    BANK = "bank"
    CASH = "cash"
    CARD = "card"
    OTHER = "other"
    METHOD_CHOICES = [(MPESA, "M-Pesa"), (BANK, "Bank transfer"), (CASH, "Cash"), (CARD, "Card"), (OTHER, "Other")]

    church = models.ForeignKey(Church, on_delete=models.CASCADE, related_name="payments")
    paid_on = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=MPESA)
    reference = models.CharField(max_length=60, blank=True, help_text="M-Pesa code or bank reference.")
    months = models.PositiveSmallIntegerField(default=1, help_text="How many months this pays for.")
    covers_from = models.DateField(null=True, blank=True)
    covers_to = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]

    def __str__(self):
        return f"{self.church} {self.amount} on {self.paid_on}"


class PlatformProfile(models.Model):
    """Extra settings for platform super admins."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="platform_profile")
    phone = models.CharField(max_length=40, blank=True)
    must_change_password = models.BooleanField(default=False)


class FailedLogin(models.Model):
    """Failed sign-ins and password-reset requests, for slowing down password guessing. Shared by every app and church."""

    LOGIN = "login"
    RESET = "reset"
    schema = models.CharField(max_length=63)
    kind = models.CharField(max_length=10, default=LOGIN)
    username = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["schema", "username", "created_at"]), models.Index(fields=["ip", "created_at"])]
