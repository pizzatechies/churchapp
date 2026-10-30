from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.utils import ZERO, q2
from ledger.models import JournalEntry
from ledger.services import EntryBuilder, LedgerError, create_entry, void_entry

from .models import Employee, Paycheck, PaycheckLine, PayrollItem, PayrollRun


def default_earnings(employee, hours=None):
    """{PayrollItem: amount} of regular pay and housing allowance for one pay period."""
    periods = Decimal(employee.periods_per_year)
    earnings = {}
    regular = PayrollItem.objects.filter(code=PayrollItem.REGULAR).first()
    housing = PayrollItem.objects.filter(code=PayrollItem.HOUSING).first()
    if regular:
        if employee.pay_type == Employee.HOURLY:
            hrs = employee.default_hours if hours is None else hours
            earnings[regular] = q2(employee.hourly_rate * hrs)
        else:
            earnings[regular] = q2(employee.annual_salary / periods)
    if housing and employee.annual_housing_allowance:
        earnings[housing] = q2(employee.annual_housing_allowance / periods)
    return earnings


def calculate_withholdings(employee, earnings):
    """Apply the employee's deductions and employer contributions to the given earnings."""
    wage_base = sum((amt for item, amt in earnings.items() if item.in_wage_base), ZERO)
    result = {}
    for assignment in employee.payroll_items.select_related("item").filter(item__is_active=True):
        item = assignment.item
        if item.kind == PayrollItem.EARNING:
            continue
        if item.calculation == PayrollItem.PERCENT:
            result[item] = q2(wage_base * assignment.amount / Decimal(100))
        else:
            result[item] = q2(assignment.amount)
    return result


@transaction.atomic
def build_paycheck(run, employee, hours=None, earnings=None):
    """Create (or rebuild) a paycheck from the employee's pay setup."""
    if run.status != PayrollRun.DRAFT:
        raise LedgerError("Paychecks can only be changed while the payroll run is a draft.")
    if earnings is None:
        earnings = default_earnings(employee, hours)
    withholdings = calculate_withholdings(employee, earnings)
    paycheck, _ = Paycheck.objects.get_or_create(run=run, employee=employee)
    paycheck.hours = hours if hours is not None else (employee.default_hours if employee.pay_type == Employee.HOURLY else None)
    paycheck.lines.all().delete()
    PaycheckLine.objects.bulk_create([
        PaycheckLine(paycheck=paycheck, item=item, amount=amount)
        for item, amount in {**earnings, **withholdings}.items()
    ])
    paycheck.recalculate_totals()
    paycheck.save()
    return paycheck


@transaction.atomic
def save_paycheck_amounts(paycheck, amounts, hours=None, check_number=""):
    """Manual edits: amounts is {PayrollItem: Decimal}."""
    if paycheck.run.status != PayrollRun.DRAFT:
        raise LedgerError("Paychecks can only be changed while the payroll run is a draft.")
    paycheck.lines.all().delete()
    PaycheckLine.objects.bulk_create([
        PaycheckLine(paycheck=paycheck, item=item, amount=q2(amount))
        for item, amount in amounts.items() if amount
    ])
    paycheck.hours = hours
    paycheck.check_number = check_number
    paycheck.recalculate_totals()
    if paycheck.net < 0:
        raise LedgerError("Deductions cannot exceed gross pay.")
    paycheck.save()
    return paycheck


@transaction.atomic
def create_run(*, period_start, period_end, pay_date, bank_account, user, employees=None, memo=""):
    if period_end < period_start:
        raise LedgerError("The pay period ends before it starts.")
    run = PayrollRun.objects.create(
        period_start=period_start, period_end=period_end, pay_date=pay_date,
        bank_account=bank_account, created_by=user, memo=memo,
    )
    employees = employees if employees is not None else Employee.objects.filter(is_active=True)
    for employee in employees:
        build_paycheck(run, employee)
    return run


@transaction.atomic
def post_run(run, user):
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.status != PayrollRun.DRAFT:
        raise LedgerError("This payroll run has already been posted.")
    paychecks = list(run.paychecks.select_related("employee__wage_account", "employee__fund").prefetch_related("lines__item"))
    if not paychecks:
        raise LedgerError("Add at least one paycheck before posting.")
    builder = EntryBuilder()
    for pc in paychecks:
        if pc.net < 0:
            raise LedgerError(f"{pc.employee}'s deductions exceed gross pay.")
        fund = pc.employee.fund
        for line in pc.lines.all():
            item = line.item
            if not line.amount:
                continue
            if item.kind == PayrollItem.EARNING:
                builder.debit(item.expense_account or pc.employee.wage_account, fund, line.amount)
            elif item.kind == PayrollItem.DEDUCTION:
                builder.credit(item.liability_account, fund, line.amount, item.name)
            else:
                builder.debit(item.expense_account, fund, line.amount)
                builder.credit(item.liability_account, fund, line.amount, item.name)
        if pc.net:
            builder.credit(run.bank_account, fund, pc.net, "Net pay")
    entry = create_entry(
        date=run.pay_date,
        memo=f"Payroll {run.period_start:%b %d} – {run.period_end:%b %d, %Y}",
        lines=builder.lines(),
        user=user,
        source_type=JournalEntry.SOURCE_PAYROLL,
        source_id=run.pk,
    )
    run.journal_entry = entry
    run.status = PayrollRun.POSTED
    run.posted_by = user
    run.posted_at = timezone.now()
    run.save()
    return run


@transaction.atomic
def void_run(run, user, reason=""):
    if run.status != PayrollRun.POSTED:
        raise LedgerError("Only posted payroll runs can be voided.")
    if run.journal_entry and run.journal_entry.status == JournalEntry.POSTED:
        void_entry(run.journal_entry, user, reason or "Payroll run voided")
    run.status = PayrollRun.VOID
    run.save()
    return run
