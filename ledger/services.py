"""
Posting engine and balance queries for the general ledger.

All other modules create journal entries exclusively through `create_entry`,
which enforces the accounting rules:

* at least two lines, no negative amounts, a line is either a debit or a credit;
* total debits equal total credits;
* debits equal credits within every fund (fund accounting);
* nothing can be added, changed or voided on or before the lock date.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import ChurchProfile
from core.utils import ZERO, MoneySum, q2

from .models import Account, Fund, JournalEntry, JournalLine, Reconciliation


class LedgerError(Exception):
    """A business-rule violation that should be shown to the user."""


def check_lock(entry_date):
    lock = ChurchProfile.get().lock_date
    if lock and entry_date <= lock:
        raise LedgerError(
            f"The books are closed through {lock:%B %d, %Y}. Transactions dated on or before "
            "that date cannot be added, changed or voided. Record an adjustment in an open period instead."
        )


@dataclass
class Line:
    account: Account
    fund: Fund
    debit: object = ZERO
    credit: object = ZERO
    description: str = ""


@dataclass
class EntryBuilder:
    """Accumulates amounts per account/fund and nets them into balanced lines."""

    _totals: dict = field(default_factory=lambda: defaultdict(lambda: ZERO))
    _objects: dict = field(default_factory=dict)

    def debit(self, account, fund, amount, description=""):
        self._add(account, fund, q2(amount), description)

    def credit(self, account, fund, amount, description=""):
        self._add(account, fund, -q2(amount), description)

    def _add(self, account, fund, signed_amount, description):
        key = (account.pk, fund.pk, description)
        self._objects[key] = (account, fund)
        self._totals[key] += signed_amount

    def lines(self):
        result = []
        for key, net in self._totals.items():
            if net == 0:
                continue
            account, fund = self._objects[key]
            if net > 0:
                result.append(Line(account, fund, debit=net, description=key[2]))
            else:
                result.append(Line(account, fund, credit=-net, description=key[2]))
        # Debits first, then credits: reads naturally on screen.
        result.sort(key=lambda line: (line.credit > 0, line.account.number))
        return result


def validate_lines(lines):
    """Raise LedgerError unless the lines form a valid, fund-balanced entry. Returns cleaned lines."""
    cleaned = []
    for line in lines:
        debit, credit = q2(line.debit or 0), q2(line.credit or 0)
        if debit < 0 or credit < 0:
            raise LedgerError("Amounts cannot be negative. Use the opposite column instead.")
        if debit and credit:
            raise LedgerError(f"A line on {line.account} has both a debit and a credit. Use separate lines.")
        if not debit and not credit:
            continue
        if line.account is None or line.fund is None:
            raise LedgerError("Every line needs an account and a fund.")
        cleaned.append(Line(line.account, line.fund, debit, credit, line.description or ""))

    if len(cleaned) < 2:
        raise LedgerError("A journal entry needs at least two lines with amounts.")

    total_dr = sum((l.debit for l in cleaned), ZERO)
    total_cr = sum((l.credit for l in cleaned), ZERO)
    if total_dr != total_cr:
        raise LedgerError(f"Debits ({total_dr:,.2f}) and credits ({total_cr:,.2f}) must be equal.")
    if total_dr == 0:
        raise LedgerError("A journal entry must have a non-zero amount.")

    by_fund = defaultdict(lambda: ZERO)
    funds = {}
    for l in cleaned:
        by_fund[l.fund.pk] += l.debit - l.credit
        funds[l.fund.pk] = l.fund
    unbalanced = [(funds[pk], diff) for pk, diff in by_fund.items() if diff != 0]
    if unbalanced:
        detail = "; ".join(
            f"{fund.name} has {'more debits' if diff > 0 else 'more credits'} by {abs(diff):,.2f}"
            for fund, diff in unbalanced
        )
        raise LedgerError(
            "Each fund must balance on its own (" + detail + "). "
            "To move money between funds, use a fund transfer."
        )
    return cleaned


@transaction.atomic
def create_entry(*, date, memo, lines, user=None, reference="", source_type=JournalEntry.SOURCE_MANUAL,
                 source_id=None, status=JournalEntry.POSTED):
    check_lock(date)
    cleaned = validate_lines(lines)
    now = timezone.now()
    entry = JournalEntry.objects.create(
        date=date,
        memo=memo[:255],
        reference=reference[:60],
        status=status,
        source_type=source_type,
        source_id=source_id,
        created_by=user,
        posted_by=user if status == JournalEntry.POSTED else None,
        posted_at=now if status == JournalEntry.POSTED else None,
    )
    JournalLine.objects.bulk_create([
        JournalLine(entry=entry, account=l.account, fund=l.fund, debit=l.debit, credit=l.credit,
                    description=l.description[:255])
        for l in cleaned
    ])
    return entry


@transaction.atomic
def replace_draft(entry, *, date, memo, lines, reference=""):
    if entry.status != JournalEntry.DRAFT:
        raise LedgerError("Only draft entries can be edited. Void a posted entry and enter a new one.")
    check_lock(date)
    cleaned = validate_lines(lines)
    entry.date, entry.memo, entry.reference = date, memo[:255], reference[:60]
    entry.save()
    entry.lines.all().delete()
    JournalLine.objects.bulk_create([
        JournalLine(entry=entry, account=l.account, fund=l.fund, debit=l.debit, credit=l.credit,
                    description=l.description[:255])
        for l in cleaned
    ])
    return entry


@transaction.atomic
def post_entry(entry, user):
    if entry.status != JournalEntry.DRAFT:
        raise LedgerError("Only draft entries can be posted.")
    check_lock(entry.date)
    validate_lines(list(entry.lines.select_related("account", "fund")))
    entry.status = JournalEntry.POSTED
    entry.posted_by = user
    entry.posted_at = timezone.now()
    entry.save()
    return entry


@transaction.atomic
def void_entry(entry, user, reason=""):
    """Void a posted entry. It stays visible for the audit trail but no longer affects any balance."""
    if entry.status == JournalEntry.VOID:
        raise LedgerError("This entry is already void.")
    if entry.status == JournalEntry.POSTED:
        check_lock(entry.date)
        if entry.is_reconciled:
            raise LedgerError(
                "This entry has been cleared on a completed bank reconciliation and cannot be voided. "
                "Record a correcting entry instead."
            )
    entry.lines.filter(reconciliation__isnull=False).update(reconciliation=None)
    entry.status = JournalEntry.VOID
    entry.voided_by = user
    entry.voided_at = timezone.now()
    entry.void_reason = reason[:255]
    entry.save()
    return entry


def delete_draft(entry):
    if entry.status != JournalEntry.DRAFT:
        raise LedgerError("Only drafts can be deleted. Posted entries are voided instead.")
    entry.delete()


# ------------------------------------------------------------------ balances

def posted_lines(*, start=None, end=None, funds=None, accounts=None):
    qs = JournalLine.objects.filter(entry__status=JournalEntry.POSTED)
    if start:
        qs = qs.filter(entry__date__gte=start)
    if end:
        qs = qs.filter(entry__date__lte=end)
    if funds:
        qs = qs.filter(fund__in=funds)
    if accounts is not None:
        qs = qs.filter(account__in=accounts)
    return qs


def totals_by(*group_fields, start=None, end=None, funds=None, accounts=None, extra_filter=None):
    """Debit/credit sums grouped by the given JournalLine fields (e.g. 'account_id', 'fund_id')."""
    qs = posted_lines(start=start, end=end, funds=funds, accounts=accounts)
    if extra_filter:
        qs = qs.filter(**extra_filter)
    rows = qs.values(*group_fields).annotate(dr=MoneySum("debit"), cr=MoneySum("credit"))
    result = {}
    for row in rows:
        key = tuple(row[f] for f in group_fields)
        result[key if len(key) > 1 else key[0]] = (row["dr"] or ZERO, row["cr"] or ZERO)
    return result


def account_balances(*, start=None, end=None, funds=None):
    """{account_id: signed balance} using each account's normal balance side."""
    accounts = {a.pk: a for a in Account.objects.all()}
    result = {}
    for account_id, (dr, cr) in totals_by("account_id", start=start, end=end, funds=funds).items():
        result[account_id] = accounts[account_id].signed(dr, cr)
    return result


def account_fund_balances(*, start=None, end=None, funds=None):
    """{(account_id, fund_id): signed balance}."""
    accounts = {a.pk: a for a in Account.objects.all()}
    result = {}
    for (account_id, fund_id), (dr, cr) in totals_by("account_id", "fund_id", start=start, end=end, funds=funds).items():
        result[(account_id, fund_id)] = accounts[account_id].signed(dr, cr)
    return result


def fund_balances(*, end=None, start=None):
    """{fund_id: net assets} — credits minus debits on net asset, income and expense lines."""
    qs = posted_lines(start=start, end=end).filter(
        account__type__in=[Account.EQUITY, Account.INCOME, Account.EXPENSE]
    )
    rows = qs.values("fund_id").annotate(dr=MoneySum("debit"), cr=MoneySum("credit"))
    return {row["fund_id"]: (row["cr"] or ZERO) - (row["dr"] or ZERO) for row in rows}


def surplus(*, start=None, end=None, funds=None):
    """Income minus expenses for the period."""
    qs = posted_lines(start=start, end=end, funds=funds).filter(account__type__in=[Account.INCOME, Account.EXPENSE])
    totals = qs.aggregate(dr=MoneySum("debit"), cr=MoneySum("credit"))
    return (totals["cr"] or ZERO) - (totals["dr"] or ZERO)


def cash_balances(end=None):
    """[(account, balance)] for every bank and cash account."""
    balances = account_balances(end=end)
    return [(a, balances.get(a.pk, ZERO)) for a in Account.objects.filter(subtype__in=Account.CASH_SUBTYPES, is_active=True)]


def last_reconciled(account):
    return account.reconciliations.filter(status=Reconciliation.COMPLETED).order_by("-statement_date").first()


# --------------------------------------------------------- common postings

def record_bank_transfer(*, date, from_account, to_account, amount, user, fund=None, memo="", reference=""):
    """Move money between two cash/bank accounts. The fund that owns the money does not change."""
    amount = q2(amount)
    if from_account == to_account:
        raise LedgerError("Choose two different accounts.")
    if amount <= 0:
        raise LedgerError("The amount must be greater than zero.")
    fund = fund or Fund.default()
    builder = EntryBuilder()
    builder.debit(to_account, fund, amount)
    builder.credit(from_account, fund, amount)
    return create_entry(
        date=date, memo=memo or f"Transfer from {from_account.name} to {to_account.name}",
        reference=reference, lines=builder.lines(), user=user, source_type=JournalEntry.SOURCE_TRANSFER,
    )


def record_fund_transfer(*, date, from_fund, to_fund, amount, cash_account, user, memo=""):
    """
    Move money from one fund to another. Both sides post to the interfund transfer
    account so each fund stays balanced on its own.
    """
    amount = q2(amount)
    if from_fund == to_fund:
        raise LedgerError("Choose two different funds.")
    if amount <= 0:
        raise LedgerError("The amount must be greater than zero.")
    transfers = Account.system(Account.SYS_INTERFUND)
    builder = EntryBuilder()
    builder.debit(transfers, from_fund, amount, f"Transfer to {to_fund.name}")
    builder.credit(cash_account, from_fund, amount)
    builder.debit(cash_account, to_fund, amount)
    builder.credit(transfers, to_fund, amount, f"Transfer from {from_fund.name}")
    return create_entry(
        date=date, memo=memo or f"Fund transfer: {from_fund.name} → {to_fund.name}",
        lines=builder.lines(), user=user, source_type=JournalEntry.SOURCE_FUND_TRANSFER,
    )


def record_income(*, date, deposit_account, income_account, fund, amount, user, memo="", reference=""):
    amount = q2(amount)
    if amount <= 0:
        raise LedgerError("The amount must be greater than zero.")
    builder = EntryBuilder()
    builder.debit(deposit_account, fund, amount)
    builder.credit(income_account, fund, amount)
    return create_entry(
        date=date, memo=memo or f"{income_account.name} deposit", reference=reference,
        lines=builder.lines(), user=user, source_type=JournalEntry.SOURCE_INCOME,
    )


def record_opening_balances(*, date, rows, user):
    """
    rows: iterable of (account, fund, balance) for balance-sheet accounts, with
    balances given on each account's normal side. Each fund is offset to its
    net asset account.
    """
    builder = EntryBuilder()
    count = 0
    for account, fund, balance in rows:
        balance = q2(balance)
        if not balance:
            continue
        if account.type in (Account.INCOME, Account.EXPENSE):
            raise LedgerError("Opening balances are for asset, liability and net asset accounts only.")
        count += 1
        if account.is_debit_normal:
            builder.debit(account, fund, balance)
            builder.credit(fund.net_asset_account, fund, balance, "Opening balance")
        else:
            builder.credit(account, fund, balance)
            builder.debit(fund.net_asset_account, fund, balance, "Opening balance")
    if not count:
        raise LedgerError("Enter at least one opening balance.")
    return create_entry(
        date=date, memo="Opening balances", lines=builder.lines(), user=user,
        source_type=JournalEntry.SOURCE_OPENING,
    )


# ------------------------------------------------------------ reconciliation

def start_reconciliation(*, account, statement_date, statement_balance, user):
    if account.reconciliations.filter(status=Reconciliation.IN_PROGRESS).exists():
        raise LedgerError("Finish or delete the reconciliation already in progress for this account first.")
    previous = last_reconciled(account)
    if previous and statement_date <= previous.statement_date:
        raise LedgerError(f"This account has already been reconciled through {previous.statement_date:%b %d, %Y}.")
    return Reconciliation.objects.create(
        account=account,
        statement_date=statement_date,
        statement_balance=q2(statement_balance),
        beginning_balance=previous.statement_balance if previous else ZERO,
        created_by=user,
    )


def reconciliation_candidates(rec):
    return (
        JournalLine.objects.filter(account=rec.account, entry__status=JournalEntry.POSTED, entry__date__lte=rec.statement_date)
        .filter(Q(reconciliation__isnull=True) | Q(reconciliation=rec))
        .select_related("entry", "fund")
        .order_by("entry__date", "entry_id", "id")
    )


@transaction.atomic
def set_cleared(rec, line_ids):
    if rec.status != Reconciliation.IN_PROGRESS:
        raise LedgerError("This reconciliation is already completed.")
    candidates = reconciliation_candidates(rec)
    ids = set(int(i) for i in line_ids)
    candidates.filter(pk__in=ids).update(reconciliation=rec)
    rec.lines.exclude(pk__in=ids).update(reconciliation=None)


@transaction.atomic
def complete_reconciliation(rec, user):
    if rec.status != Reconciliation.IN_PROGRESS:
        raise LedgerError("This reconciliation is already completed.")
    if rec.difference != 0:
        raise LedgerError(f"The reconciliation is out of balance by {rec.difference:,.2f}. Keep checking off items until the difference is zero.")
    rec.status = Reconciliation.COMPLETED
    rec.completed_by = user
    rec.completed_at = timezone.now()
    rec.save()
    return rec


@transaction.atomic
def reopen_reconciliation(rec):
    latest = last_reconciled(rec.account)
    if rec.status != Reconciliation.COMPLETED or latest != rec:
        raise LedgerError("Only the most recent completed reconciliation can be reopened.")
    if rec.account.reconciliations.filter(status=Reconciliation.IN_PROGRESS).exists():
        raise LedgerError("Delete the reconciliation in progress first.")
    rec.status = Reconciliation.IN_PROGRESS
    rec.completed_by = None
    rec.completed_at = None
    rec.save()
    return rec
