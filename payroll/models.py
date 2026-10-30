from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from core.utils import MoneySum
from ledger.models import Account, Fund, JournalEntry, money_field

ZERO = Decimal("0.00")

PERIODS_PER_YEAR = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12}


class PayrollItem(models.Model):
    """
    A configurable line on a paycheck: an earning, an employee deduction
    (withholding) or an employer contribution. Rates and accounts are set
    up once to match local tax law (PAYE, FICA, pension schemes...).
    """

    EARNING = "earning"
    DEDUCTION = "deduction"
    EMPLOYER = "employer"
    KIND_CHOICES = [
        (EARNING, "Earning"),
        (DEDUCTION, "Employee deduction / withholding"),
        (EMPLOYER, "Employer contribution / tax"),
    ]
    FIXED = "fixed"
    PERCENT = "percent"
    CALC_CHOICES = [(FIXED, "Fixed amount per paycheck"), (PERCENT, "Percent of wages")]

    REGULAR = "REGULAR"
    HOUSING = "HOUSING"

    code = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    calculation = models.CharField(max_length=10, choices=CALC_CHOICES, default=FIXED)
    default_amount = models.DecimalField(
        "Default rate / amount", max_digits=12, decimal_places=4, default=Decimal("0"),
        help_text="Percent (e.g. 7.65) or fixed amount. Can be overridden for each employee.",
    )
    expense_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"type": Account.EXPENSE},
        help_text="Earnings: leave blank to use each employee's wage account. Employer contributions: required.",
    )
    liability_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"type": Account.LIABILITY},
        help_text="Where withheld or owed amounts are held until paid to the tax authority or provider.",
    )
    in_wage_base = models.BooleanField(
        "Counts toward wages for percentage items", default=True,
        help_text="Untick for a clergy housing allowance, which is usually excluded from income tax wages.",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.kind in (self.DEDUCTION, self.EMPLOYER) and not self.liability_account:
            raise ValidationError({"liability_account": "Deductions and employer contributions need a liability account."})
        if self.kind == self.EMPLOYER and not self.expense_account:
            raise ValidationError({"expense_account": "Employer contributions need an expense account."})
        if self.kind == self.EARNING and self.calculation == self.PERCENT:
            raise ValidationError({"calculation": "Earnings must be fixed amounts."})


class Employee(models.Model):
    CLERGY = "clergy"
    STAFF = "staff"
    TYPE_CHOICES = [(CLERGY, "Clergy / minister"), (STAFF, "Lay staff")]
    SALARY = "salary"
    HOURLY = "hourly"
    PAY_TYPE_CHOICES = [(SALARY, "Salaried"), (HOURLY, "Hourly")]
    FREQUENCY_CHOICES = [
        ("weekly", "Weekly"), ("biweekly", "Every two weeks"),
        ("semimonthly", "Twice a month"), ("monthly", "Monthly"),
    ]

    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    title = models.CharField("Position", max_length=100, blank=True)
    employee_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=STAFF)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    tax_id_last4 = models.CharField("Tax ID (last 4)", max_length=4, blank=True)
    pay_type = models.CharField(max_length=10, choices=PAY_TYPE_CHOICES, default=SALARY)
    pay_frequency = models.CharField(max_length=12, choices=FREQUENCY_CHOICES, default="semimonthly")
    annual_salary = money_field()
    hourly_rate = money_field()
    default_hours = models.DecimalField("Hours per pay period", max_digits=7, decimal_places=2, default=Decimal("0"))
    annual_housing_allowance = money_field(
        help_text="Clergy housing allowance designated by the board in advance (paid evenly each period).",
    )
    wage_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="+", limit_choices_to={"type": Account.EXPENSE},
        help_text="Expense account charged with this person's wages.",
    )
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="+", help_text="Fund that pays this person.")
    hire_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("payroll:employee_detail", args=[self.pk])

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def periods_per_year(self):
        return PERIODS_PER_YEAR[self.pay_frequency]

    @property
    def annual_compensation(self):
        if self.pay_type == self.SALARY:
            base = self.annual_salary
        else:
            base = self.hourly_rate * self.default_hours * self.periods_per_year
        return base + self.annual_housing_allowance


class EmployeePayrollItem(models.Model):
    """A deduction or employer contribution that applies to an employee, with an optional custom rate."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_items")
    item = models.ForeignKey(PayrollItem, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(
        "Rate / amount", max_digits=12, decimal_places=4, default=Decimal("0"),
        help_text="Percent of wages or fixed amount per paycheck, depending on the item.",
    )

    class Meta:
        unique_together = [("employee", "item")]
        ordering = ["item__sort_order", "item__name"]

    def __str__(self):
        return f"{self.employee}: {self.item}"


class PayrollRun(models.Model):
    DRAFT = "draft"
    POSTED = "posted"
    VOID = "void"
    STATUS_CHOICES = [(DRAFT, "Draft"), (POSTED, "Posted"), (VOID, "Void")]

    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField()
    bank_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                     limit_choices_to={"subtype__in": ["bank", "cash"]}, verbose_name="Pay from")
    memo = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    journal_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pay_date", "-id"]

    def __str__(self):
        return f"Payroll {self.period_start:%b %d} – {self.period_end:%b %d, %Y}"

    def get_absolute_url(self):
        return reverse("payroll:run_detail", args=[self.pk])

    def totals(self):
        t = self.paychecks.aggregate(gross=MoneySum("gross"), deductions=MoneySum("deductions"), net=MoneySum("net"), employer=MoneySum("employer_cost"))
        return {k: v or ZERO for k, v in t.items()}


class Paycheck(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="paychecks")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="paychecks")
    hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    gross = money_field()
    deductions = money_field()
    net = money_field()
    employer_cost = money_field(help_text="Employer contributions and taxes on top of gross pay.")
    check_number = models.CharField("Check # / reference", max_length=40, blank=True)

    class Meta:
        ordering = ["employee__last_name", "employee__first_name"]
        unique_together = [("run", "employee")]

    def __str__(self):
        return f"{self.employee} – {self.run}"

    def get_absolute_url(self):
        return reverse("payroll:paycheck_stub", args=[self.pk])

    def lines_by_kind(self, kind):
        return [l for l in self.lines.all() if l.item.kind == kind]

    def recalculate_totals(self):
        gross = deductions = employer = ZERO
        for line in self.lines.select_related("item"):
            if line.item.kind == PayrollItem.EARNING:
                gross += line.amount
            elif line.item.kind == PayrollItem.DEDUCTION:
                deductions += line.amount
            else:
                employer += line.amount
        self.gross, self.deductions, self.employer_cost = gross, deductions, employer
        self.net = gross - deductions


class PaycheckLine(models.Model):
    paycheck = models.ForeignKey(Paycheck, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(PayrollItem, on_delete=models.PROTECT, related_name="+")
    amount = money_field()

    class Meta:
        ordering = ["item__sort_order", "item__name"]
        unique_together = [("paycheck", "item")]

    def __str__(self):
        return f"{self.item}: {self.amount}"
