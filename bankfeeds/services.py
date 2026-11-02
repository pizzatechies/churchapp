"""Importing, matching and recording bank feed lines."""

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from core.models import ChurchProfile
from core.utils import ZERO, q2
from giving.models import Contribution, ContributionBatch, Donor
from ledger import services as ledger
from ledger.models import Account, Fund, JournalEntry, JournalLine
from ledger.services import EntryBuilder, LedgerError

from .models import BankConnection, BankTransaction, StatementImport
from .parsers import parse_statement

MATCH_WINDOW_DAYS = 10


class FeedError(Exception):
    """A rule violation to show the user."""


# ---------------------------------------------------------------- importing

@transaction.atomic
def import_statement(connection, file_name, content, user=None):
    month_first = ChurchProfile.cached().country == "US"
    lines = parse_statement(file_name, content, month_first=month_first)
    existing = set(BankTransaction.objects.filter(account=connection.account, external_id__in=[l.external_id for l in lines])
                   .values_list("external_id", flat=True))
    # Payments that already arrived live from M-Pesa carry the same receipt number as the portal statement.
    live_refs = set(BankTransaction.objects.filter(account=connection.account, source=BankTransaction.LIVE)
                    .exclude(reference="").values_list("reference", flat=True))
    new = [l for l in lines if l.external_id not in existing and not (l.reference and l.reference in live_refs)]
    closing = next((Decimal(l.raw["closing_balance"]) for l in lines if l.raw.get("closing_balance")), None)
    with_balance = [l for l in lines if l.balance is not None]
    if closing is None and with_balance:
        # Statements list oldest-first or newest-first; the closing balance is on the newest end.
        newest_first = with_balance[0].date > with_balance[-1].date
        closing = (with_balance[0] if newest_first else with_balance[-1]).balance
    imp = StatementImport.objects.create(
        connection=connection, file_name=file_name[:255], added=len(new), skipped=len(lines) - len(new),
        first_date=min(l.date for l in lines), last_date=max(l.date for l in lines), closing_balance=closing, imported_by=user,
    )
    BankTransaction.objects.bulk_create([
        BankTransaction(
            connection=connection, account=connection.account, statement_import=imp, source=BankTransaction.IMPORT,
            external_id=l.external_id, date=l.date, amount=l.amount, description=l.description, reference=l.reference,
            payer_name=l.payer_name, payer_phone=l.payer_phone, balance=l.balance,
            raw={k: str(v) for k, v in l.raw.items()},
        ) for l in new
    ])
    imp.matched = auto_match(connection)
    return imp


# ----------------------------------------------------------------- matching

def match_candidates(txn, exclude_entries=()):
    """Posted journal entries on the same account, for the same amount, within a few days, not yet matched."""
    taken = BankTransaction.objects.filter(account=txn.account, journal_entry__isnull=False).exclude(pk=txn.pk).values("journal_entry")
    rows = (
        JournalLine.objects.filter(
            account=txn.account, entry__status=JournalEntry.POSTED,
            entry__date__gte=txn.date - timedelta(days=MATCH_WINDOW_DAYS),
            entry__date__lte=txn.date + timedelta(days=MATCH_WINDOW_DAYS),
        )
        .exclude(entry__in=taken)
        .exclude(entry__in=list(exclude_entries))
        .values("entry_id", "entry__date", "entry__memo", "entry__reference")
        .annotate(dr=Sum("debit"), cr=Sum("credit"))
    )
    found = []
    for r in rows:
        net = (r["dr"] or ZERO) - (r["cr"] or ZERO)  # bank and cash accounts: money in is a debit
        if net == txn.amount:
            found.append({"entry_id": r["entry_id"], "date": r["entry__date"], "memo": r["entry__memo"],
                          "reference": r["entry__reference"], "days": abs((r["entry__date"] - txn.date).days)})
    ref = (txn.reference or "").lower()
    # Closest date first; a matching reference (cheque or M-Pesa code) wins outright.
    found.sort(key=lambda c: (not (ref and ref in (c["reference"] or "").lower()), c["days"], c["entry_id"]))
    return found


def auto_match(connection):
    """Match lines that have exactly one possible entry, and whose entry no other line could also be."""
    pending = list(connection.transactions.filter(status=BankTransaction.NEW).order_by("date", "id"))
    options = {t.pk: [c["entry_id"] for c in match_candidates(t)] for t in pending}
    claims = {}
    for entry_ids in options.values():
        for e in entry_ids:
            claims[e] = claims.get(e, 0) + 1
    matched = 0
    for t in pending:
        ids = options[t.pk]
        if len(ids) == 1 and claims[ids[0]] == 1:
            t.journal_entry_id, t.status, t.auto_matched = ids[0], BankTransaction.MATCHED, True
            t.save(update_fields=["journal_entry", "status", "auto_matched"])
            matched += 1
    return matched


@transaction.atomic
def match(txn, entry, user=None):
    if txn.status != BankTransaction.NEW:
        raise FeedError("This line has already been dealt with.")
    if entry.status != JournalEntry.POSTED:
        raise FeedError("Only posted entries can be matched.")
    net = entry.lines.filter(account=txn.account).aggregate(dr=Sum("debit"), cr=Sum("credit"))
    if (net["dr"] or ZERO) - (net["cr"] or ZERO) != txn.amount:
        raise FeedError("That entry doesn't move the same amount through this account.")
    txn.journal_entry, txn.status, txn.reviewed_by, txn.auto_matched = entry, BankTransaction.MATCHED, user, False
    try:
        with transaction.atomic():
            txn.save(update_fields=["journal_entry", "status", "reviewed_by", "auto_matched"])
    except IntegrityError:
        raise FeedError("That entry is already matched to another line from this account.")
    return txn


def ignore(txn, user=None):
    if txn.status != BankTransaction.NEW:
        raise FeedError("This line has already been dealt with.")
    txn.status, txn.reviewed_by = BankTransaction.IGNORED, user
    txn.save(update_fields=["status", "reviewed_by"])


@transaction.atomic
def undo(txn, user=None):
    """Put a line back to 'To review'. Entries and gifts the feed created are removed again."""
    if txn.status == BankTransaction.RECORDED and txn.contribution_id:
        c = txn.contribution
        if c.batch.status != ContributionBatch.OPEN:
            raise FeedError(f"The gift is in batch {c.batch.number}, which has been posted. Reopen the batch first.")
        txn.contribution = None
        txn.save(update_fields=["contribution"])
        c.delete()
    elif txn.status == BankTransaction.MATCHED and txn.journal_entry_id:
        entry = txn.journal_entry
        txn.journal_entry = None
        txn.save(update_fields=["journal_entry"])
        if entry.source_type == JournalEntry.SOURCE_BANK_FEED and entry.status == JournalEntry.POSTED:
            try:
                ledger.void_entry(entry, user, "Bank feed line put back for review")
            except LedgerError as e:
                raise FeedError(str(e))
    txn.status, txn.auto_matched, txn.reviewed_by = BankTransaction.NEW, False, None
    txn.save(update_fields=["status", "auto_matched", "reviewed_by"])


# ---------------------------------------------------------------- recording

def _memo(txn, fallback):
    return (txn.description or fallback)[:255]


@transaction.atomic
def record_entry(txn, category, fund, user=None, memo=""):
    """Record a line that isn't in the books yet: other income for money in, spending (e.g. bank charges) for money out."""
    if txn.status != BankTransaction.NEW:
        raise FeedError("This line has already been dealt with.")
    if txn.money_in and category.type != Account.INCOME:
        raise FeedError("Choose an income category for money coming in.")
    if not txn.money_in and category.type != Account.EXPENSE:
        raise FeedError("Choose a spending category for money going out.")
    amount = abs(txn.amount)
    builder = EntryBuilder()
    if txn.money_in:
        builder.debit(txn.account, fund, amount)
        builder.credit(category, fund, amount)
    else:
        builder.debit(category, fund, amount)
        builder.credit(txn.account, fund, amount)
    try:
        entry = ledger.create_entry(
            date=txn.date, memo=memo or _memo(txn, category.name), reference=txn.reference, lines=builder.lines(),
            user=user, source_type=JournalEntry.SOURCE_BANK_FEED, source_id=txn.pk,
        )
    except LedgerError as e:
        raise FeedError(str(e))
    txn.journal_entry, txn.status, txn.reviewed_by = entry, BankTransaction.MATCHED, user
    txn.save(update_fields=["journal_entry", "status", "reviewed_by"])
    return entry


def feed_batch(connection, day, user=None):
    """The open offering batch that collects the feed's gifts for one day."""
    label = "M-Pesa gifts" if connection.is_live else f"{connection.account.name} gifts"
    description = f"{label} · {day:%d %b %Y}"
    batch = ContributionBatch.objects.filter(deposit_account=connection.account, date=day, description=description,
                                             status=ContributionBatch.OPEN).first()
    return batch or ContributionBatch.objects.create(
        date=day, description=description, deposit_account=connection.account, created_by=user,
        notes="Created by the bank feed. Check the gifts, then post the batch.",
    )


@transaction.atomic
def record_gift(txn, fund, category, donor=None, user=None):
    if txn.status != BankTransaction.NEW:
        raise FeedError("This line has already been dealt with.")
    if not txn.money_in:
        raise FeedError("Only money coming in can be a gift.")
    if category.type != Account.INCOME:
        raise FeedError("Choose an income category for the gift.")
    if ChurchProfile.get().lock_date and txn.date <= ChurchProfile.get().lock_date:
        raise FeedError("The books are closed for that date. Record it in an open period instead.")
    batch = feed_batch(txn.connection, txn.date, user)
    gift = Contribution.objects.create(
        batch=batch, donor=donor, date=txn.date, fund=fund, account=category, amount=txn.amount,
        method=Contribution.MOBILE_MONEY if txn.connection.is_live else Contribution.BANK_TRANSFER,
        check_number=txn.reference[:40], memo=" ".join(p for p in [txn.payer_name, txn.account_reference] if p)[:255],
    )
    txn.contribution, txn.status, txn.reviewed_by = gift, BankTransaction.RECORDED, user
    txn.save(update_fields=["contribution", "status", "reviewed_by"])
    return gift


# --------------------------------------------------------- guessing a gift

def _digits(phone):
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 and "*" not in (phone or "") else ""


BANK_CHARGE_WORDS = ("fee", "charge", "excise", "commission", "transaction cost", "ledger", "levy", "stamp duty", "sms alert")


def guess_spending(txn):
    """Bank charges are the usual unrecorded money out; suggest the bank fees account for them."""
    text = (txn.description or "").lower()
    if any(w in text for w in BANK_CHARGE_WORDS):
        return Account.objects.filter(type=Account.EXPENSE, is_active=True, name__icontains="bank").order_by("number").first()
    return None


def _donor_by_name(txn):
    """A giver whose full name or organisation name appears in the payer name or narration (for suggestions only)."""
    text = f" {txn.payer_name} {txn.description} ".lower()
    best = None
    for d in Donor.objects.filter(is_active=True):
        name = d.display_name.lower()
        if len(name) >= 6 and f" {name} " in text and (best is None or len(name) > len(best.display_name)):
            best = d
    return best


def guess_gift(connection, txn, by_name=False):
    """Best guess at (donor, fund, category) from what the giver typed as the account number, and their phone.

    Name matches are only offered as suggestions on screen (`by_name`), never used for automatic recording,
    because two people can share a name.
    """
    ref = (txn.account_reference or "").strip()
    words = [w for w in re.split(r"[\s,./#:_-]+", ref.lower()) if w]
    donor = None
    for w in words:
        if w.isdigit():
            donor = Donor.objects.filter(envelope_number=w, is_active=True).first()
            if donor:
                break
    if donor is None and _digits(txn.payer_phone):
        tail = _digits(txn.payer_phone)
        donor = next((d for d in Donor.objects.filter(is_active=True).exclude(phone="") if _digits(d.phone) == tail), None)
    if donor is None and by_name:
        donor = _donor_by_name(txn)

    funds = list(Fund.objects.filter(is_active=True))
    fund = None
    for w in words:
        fund = next((f for f in funds if f.code.lower() == w or (len(w) >= 4 and f.name.lower().startswith(w))), None)
        if fund:
            break
    incomes = list(Account.objects.filter(type=Account.INCOME, is_active=True, subtype="contributions"))
    category = None
    for w in words:
        if len(w) >= 4:
            category = next((a for a in incomes if w.rstrip("s") in a.name.lower()), None)
            if category:
                break
    fund = fund or connection.default_fund or Fund.default()
    category = category or (fund.default_income_account if fund and fund.default_income_account else None) \
        or connection.default_income_account or (incomes[0] if incomes else None)
    return donor, fund, category


# ------------------------------------------------------------- M-Pesa (C2B)

def _c2b_date(value):
    try:
        return timezone.make_aware(datetime.strptime(str(value)[:14], "%Y%m%d%H%M%S")).date()
    except (ValueError, TypeError):
        return timezone.localdate()


def receive_c2b(connection, payload):
    """Store one payment Safaricom sent us. Returns the BankTransaction (or the existing one for a repeat)."""
    trans_id = str(payload.get("TransID") or "").strip()[:40]
    if not trans_id:
        raise FeedError("No TransID in the payment.")
    try:
        amount = q2(Decimal(str(payload.get("TransAmount") or "0").replace(",", "")))
    except InvalidOperation:
        raise FeedError("The amount isn't a number.")
    if amount <= 0:
        raise FeedError("The amount must be positive.")
    if BankTransaction.objects.filter(account=connection.account, reference=trans_id).exclude(external_id=f"m-{trans_id}").exists():
        # Already uploaded from a statement before the live notice arrived.
        return BankTransaction.objects.filter(account=connection.account, reference=trans_id).first()
    name = " ".join(p for p in (str(payload.get(k) or "").strip() for k in ("FirstName", "MiddleName", "LastName")) if p)
    txn, created = BankTransaction.objects.get_or_create(
        account=connection.account, external_id=f"m-{trans_id}",
        defaults={
            "connection": connection, "source": BankTransaction.LIVE, "date": _c2b_date(payload.get("TransTime")),
            "amount": amount, "reference": trans_id, "payer_name": name.title()[:150],
            "payer_phone": str(payload.get("MSISDN") or "")[:40],
            "account_reference": str(payload.get("BillRefNumber") or "").strip()[:60],
            "description": f"{payload.get('TransactionType') or 'Payment'} from {name.title() or 'M-Pesa customer'}"[:255],
            "balance": _balance(payload.get("OrgAccountBalance")),
            "raw": {k: str(v) for k, v in payload.items()},
        },
    )
    BankConnection.objects.filter(pk=connection.pk).update(last_received_at=timezone.now())
    if created:
        settle_new_payment(connection, txn)
    return txn


def _balance(value):
    try:
        return q2(Decimal(str(value).replace(",", ""))) if value not in (None, "") else None
    except InvalidOperation:
        return None


def settle_new_payment(connection, txn):
    """Match a new live payment to the books, or add it to the day's gift batch if the church asked for that."""
    if match_candidates(txn) and auto_match(connection):
        txn.refresh_from_db()
        if txn.status != BankTransaction.NEW:
            return
    if connection.auto_record_gifts:
        donor, fund, category = guess_gift(connection, txn)
        if fund and category:
            try:
                record_gift(txn, fund, category, donor=donor)
            except FeedError:
                pass  # e.g. a closed period: it stays in "To review"


def counts(connection):
    result = {s: 0 for s, _ in BankTransaction.STATUS_CHOICES}
    for row in connection.transactions.values("status").annotate(n=Count("id")):
        result[row["status"]] = row["n"]
    return result


def feed_entry_line_ids(rec):
    """Line ids on a reconciliation that the bank feed shows went through the bank by the statement date."""
    txns = BankTransaction.objects.filter(account=rec.account, date__lte=rec.statement_date).filter(
        Q(journal_entry__isnull=False) | Q(contribution__batch__journal_entry__isnull=False)
    )
    entry_ids = set(txns.exclude(journal_entry__isnull=True).values_list("journal_entry", flat=True))
    entry_ids |= set(txns.exclude(contribution__isnull=True).values_list("contribution__batch__journal_entry", flat=True))
    entry_ids.discard(None)
    return set(JournalLine.objects.filter(account=rec.account, entry_id__in=entry_ids).values_list("pk", flat=True))


def create_mpesa_account(shortcode=""):
    """A bank-type account for the money that sits in the M-Pesa Paybill/Till before it moves to the bank."""
    taken = set(Account.objects.values_list("number", flat=True))
    number = next(str(n) for n in range(1030, 1100) if str(n) not in taken)
    name = f"M-Pesa Paybill {shortcode}".strip() if shortcode else "M-Pesa Paybill"
    base, n = name, 2
    while Account.objects.filter(name=name).exists():
        name, n = f"{base} ({n})", n + 1
    return Account.objects.create(number=number, name=name, type=Account.ASSET, subtype="bank", bank_name="Safaricom M-Pesa",
                                  description="Money paid to the church's M-Pesa Paybill or Till, before it is moved to the bank.")
