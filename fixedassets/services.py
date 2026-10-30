from django.db import transaction

from core.utils import ZERO, add_months, month_end, months_between, q2
from ledger.models import Account, JournalEntry
from ledger.services import EntryBuilder, LedgerError, create_entry, void_entry

from .models import DepreciationEntry, DepreciationRun, FixedAsset


def depreciation_due(asset, through):
    """(months, amount, first_month) still to be recorded for the asset up to `through` (straight line)."""
    through = month_end(through)
    if asset.status != FixedAsset.ACTIVE or not asset.useful_life_months:
        return 0, ZERO, None
    if asset.in_service_date > through:
        return 0, ZERO, None
    start = asset.in_service_date.replace(day=1)
    if asset.depreciated_through:
        start = add_months(asset.depreciated_through.replace(day=1), 1)
    if start > through:
        return 0, ZERO, None
    months = months_between(start, through)
    remaining = asset.depreciable_base - asset.accumulated_depreciation
    if remaining <= 0:
        return 0, ZERO, None
    amount = min(remaining, q2(asset.monthly_depreciation * months))
    return months, amount, start


def preview(through):
    rows = []
    for asset in FixedAsset.objects.filter(status=FixedAsset.ACTIVE).select_related("fund"):
        months, amount, start = depreciation_due(asset, through)
        if amount > 0:
            rows.append((asset, months, amount, start))
    return rows


@transaction.atomic
def run_depreciation(through, user):
    through = month_end(through)
    rows = preview(through)
    if not rows:
        raise LedgerError("There is no depreciation to record through that month.")
    run = DepreciationRun.objects.create(through_date=through, created_by=user)
    builder = EntryBuilder()
    for asset, months, amount, start in rows:
        builder.debit(asset.expense_account, asset.fund, amount)
        builder.credit(asset.accumulated_account, asset.fund, amount)
        DepreciationEntry.objects.create(run=run, asset=asset, months=months, amount=amount,
                                         period_start=start, period_end=through)
        asset.depreciated_through = through
        asset.save(update_fields=["depreciated_through"])
    run.journal_entry = create_entry(
        date=through, memo=f"Depreciation through {through:%B %Y}", lines=builder.lines(), user=user,
        source_type=JournalEntry.SOURCE_DEPRECIATION, source_id=run.pk,
    )
    run.save()
    return run


@transaction.atomic
def void_depreciation_run(run, user):
    if run.is_void:
        raise LedgerError("This depreciation run is already void.")
    latest = DepreciationRun.objects.filter(is_void=False).order_by("-through_date", "-id").first()
    if latest != run:
        raise LedgerError("Only the most recent depreciation run can be voided.")
    if run.journal_entry and run.journal_entry.status == JournalEntry.POSTED:
        void_entry(run.journal_entry, user, "Depreciation run voided")
    run.is_void = True
    run.save()
    for entry in run.entries.select_related("asset"):
        asset = entry.asset
        prior = asset.depreciation_entries.filter(run__is_void=False).order_by("-period_end").first()
        asset.depreciated_through = prior.period_end if prior else None
        asset.save(update_fields=["depreciated_through"])
    return run


@transaction.atomic
def dispose_asset(asset, *, date, proceeds, deposit_account, user, memo=""):
    """Remove the asset from the books, recording any sale proceeds and the gain or loss."""
    if asset.status != FixedAsset.ACTIVE:
        raise LedgerError("This asset has already been disposed of.")
    proceeds = q2(proceeds or 0)
    if proceeds and not deposit_account:
        raise LedgerError("Choose the account the sale proceeds were deposited to.")
    months, due, _ = depreciation_due(asset, date)
    if due > 0:
        raise LedgerError(
            f"Record depreciation through {date:%B %Y} before disposing of this asset "
            f"({months} month(s) are still unrecorded)."
        )
    accumulated = asset.accumulated_depreciation
    gain = proceeds - (asset.cost - accumulated)
    disposal = Account.system(Account.SYS_DISPOSAL)
    builder = EntryBuilder()
    if accumulated:
        builder.debit(asset.accumulated_account, asset.fund, accumulated)
    if proceeds:
        builder.debit(deposit_account, asset.fund, proceeds)
    builder.credit(asset.asset_account, asset.fund, asset.cost)
    if gain > 0:
        builder.credit(disposal, asset.fund, gain, "Gain on disposal")
    elif gain < 0:
        builder.debit(disposal, asset.fund, -gain, "Loss on disposal")
    asset.disposal_entry = create_entry(
        date=date, memo=memo or f"Disposal of {asset.name}", lines=builder.lines(), user=user,
        source_type=JournalEntry.SOURCE_DISPOSAL, source_id=asset.pk,
    )
    asset.status = FixedAsset.DISPOSED
    asset.disposal_date = date
    asset.disposal_proceeds = proceeds
    asset.save()
    return asset
