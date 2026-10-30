"""
Expense workflow: draft → submitted → approved (posted to accounts payable) → paid.

Approval posts the expense to the ledger (debit expense, credit accounts
payable). Each payment then clears accounts payable against the bank account,
split across funds in proportion to what each fund still owes.
"""

from django.db import transaction
from django.utils import timezone

from core.models import ChurchProfile
from core.utils import ZERO, MoneySum, q2
from ledger.models import Account, JournalEntry, JournalLine
from ledger.services import EntryBuilder, LedgerError, create_entry, void_entry

from .models import Expense, ExpenseLine, ExpensePayment


def _ap():
    return Account.system(Account.SYS_AP)


@transaction.atomic
def submit_expense(expense, user):
    if expense.status not in (Expense.DRAFT, Expense.REJECTED):
        raise LedgerError("Only draft or rejected expenses can be submitted.")
    expense.recalculate_total()
    if expense.total <= 0:
        raise LedgerError("Add at least one line with an amount before submitting.")
    expense.submitted_at = timezone.now()
    expense.reviewed_by = None
    expense.reviewed_at = None
    expense.review_note = ""
    if not expense.requested_by:
        expense.requested_by = user
    threshold = ChurchProfile.get().expense_approval_threshold
    if expense.total <= threshold:
        expense.status = Expense.PENDING
        expense.save()
        return _approve(expense, None, f"Automatically approved (at or under the {threshold:,.2f} approval limit)")
    expense.status = Expense.PENDING
    expense.save()
    return expense


def can_approve(expense, user):
    """Segregation of duties check. Returns (allowed, reason)."""
    profile = ChurchProfile.get()
    if profile.require_separate_approver and expense.requested_by_id == user.pk and not user.is_superuser:
        return False, "You requested this expense, so someone else must approve it."
    return True, ""


@transaction.atomic
def approve_expense(expense, user, note=""):
    if expense.status != Expense.PENDING:
        raise LedgerError("Only expenses awaiting approval can be approved.")
    allowed, reason = can_approve(expense, user)
    if not allowed:
        raise LedgerError(reason)
    return _approve(expense, user, note)


def _approve(expense, user, note):
    lines = list(expense.lines.select_related("account", "fund"))
    ap = _ap()
    builder = EntryBuilder()
    for line in lines:
        builder.debit(line.account, line.fund, line.amount, line.description)
        builder.credit(ap, line.fund, line.amount)
    entry = create_entry(
        date=expense.date,
        memo=f"{expense.number} {expense.vendor.name}: {expense.description}",
        reference=expense.reference,
        lines=builder.lines(),
        user=user or expense.requested_by,
        source_type=JournalEntry.SOURCE_EXPENSE,
        source_id=expense.pk,
    )
    expense.journal_entry = entry
    expense.status = Expense.APPROVED
    expense.reviewed_by = user
    expense.reviewed_at = timezone.now()
    expense.review_note = note[:255]
    expense.save()
    return expense


@transaction.atomic
def reject_expense(expense, user, note=""):
    if expense.status != Expense.PENDING:
        raise LedgerError("Only expenses awaiting approval can be rejected.")
    if not note:
        raise LedgerError("Please give a reason so the requester knows what to fix.")
    expense.status = Expense.REJECTED
    expense.reviewed_by = user
    expense.reviewed_at = timezone.now()
    expense.review_note = note[:255]
    expense.save()
    return expense


def remaining_by_fund(expense):
    """What is still owed on the expense, per fund."""
    ap = _ap()
    owed = expense.fund_totals()
    payment_entries = expense.payments.filter(is_void=False, journal_entry__isnull=False).values("journal_entry")
    paid = (
        JournalLine.objects.filter(entry__in=payment_entries, account=ap)
        .values("fund").annotate(dr=MoneySum("debit"))
    )
    paid_map = {row["fund"]: row["dr"] or ZERO for row in paid}
    return {fund: amount - paid_map.get(fund.pk, ZERO) for fund, amount in owed.items()}


def allocate(amount, remaining):
    """Split `amount` across funds proportionally to what each still owes; exact to the cent."""
    open_funds = {f: r for f, r in remaining.items() if r > 0}
    total_remaining = sum(open_funds.values(), ZERO)
    if amount == total_remaining:
        return open_funds
    allocation = {}
    allocated = ZERO
    ordered = sorted(open_funds.items(), key=lambda item: item[1])
    for i, (fund, owed) in enumerate(ordered):
        if i == len(ordered) - 1:
            share = amount - allocated
        else:
            share = q2(amount * owed / total_remaining)
        allocation[fund] = share
        allocated += share
    return {f: a for f, a in allocation.items() if a}


@transaction.atomic
def record_payment(expense, user, *, date, amount, pay_from, method=ExpensePayment.CHECK, reference="", memo=""):
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    amount = q2(amount)
    if expense.status not in Expense.OPEN_BALANCE:
        raise LedgerError("Only approved, unpaid expenses can be paid.")
    if amount <= 0:
        raise LedgerError("The payment amount must be greater than zero.")
    if amount > expense.balance_due:
        raise LedgerError(f"The payment is more than the balance due ({expense.balance_due:,.2f}).")
    if pay_from.subtype not in Account.PAYMENT_SUBTYPES:
        raise LedgerError("Payments must come from a bank, cash or credit card account.")
    ap = _ap()
    builder = EntryBuilder()
    for fund, share in allocate(amount, remaining_by_fund(expense)).items():
        builder.debit(ap, fund, share)
        builder.credit(pay_from, fund, share)
    payment = ExpensePayment.objects.create(
        expense=expense, date=date, amount=amount, pay_from=pay_from, method=method,
        reference=reference, memo=memo, created_by=user,
    )
    payment.journal_entry = create_entry(
        date=date,
        memo=f"Payment to {expense.vendor.name} for {expense.number}",
        reference=reference,
        lines=builder.lines(),
        user=user,
        source_type=JournalEntry.SOURCE_PAYMENT,
        source_id=payment.pk,
    )
    payment.save()
    expense.refresh_payment_status()
    expense.save()
    return payment


@transaction.atomic
def void_payment(payment, user, reason=""):
    if payment.is_void:
        raise LedgerError("This payment is already void.")
    if payment.journal_entry and payment.journal_entry.status == JournalEntry.POSTED:
        void_entry(payment.journal_entry, user, reason or "Payment voided")
    payment.is_void = True
    payment.voided_at = timezone.now()
    payment.save()
    expense = payment.expense
    expense.refresh_payment_status()
    expense.save()
    return payment


@transaction.atomic
def void_expense(expense, user, reason=""):
    if expense.status == Expense.VOID:
        raise LedgerError("This expense is already void.")
    if expense.payments.filter(is_void=False).exists():
        raise LedgerError("Void the payments on this expense first.")
    if expense.journal_entry and expense.journal_entry.status == JournalEntry.POSTED:
        void_entry(expense.journal_entry, user, reason or f"{expense.number} voided")
    expense.status = Expense.VOID
    expense.review_note = (reason or expense.review_note)[:255]
    expense.save()
    return expense


@transaction.atomic
def duplicate_expense(expense, user):
    from core.utils import today

    copy = Expense.objects.create(
        vendor=expense.vendor,
        expense_type=expense.expense_type,
        date=today(),
        description=expense.description,
        requested_by=user,
    )
    ExpenseLine.objects.bulk_create([
        ExpenseLine(expense=copy, account=l.account, fund=l.fund, description=l.description, amount=l.amount)
        for l in expense.lines.all()
    ])
    copy.recalculate_total()
    copy.save()
    return copy


def outstanding_payables():
    return Expense.objects.filter(status__in=Expense.OPEN_BALANCE)


def total_outstanding():
    totals = outstanding_payables().aggregate(t=MoneySum("total"), p=MoneySum("amount_paid"))
    return (totals["t"] or ZERO) - (totals["p"] or ZERO)

