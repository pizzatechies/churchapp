from django.db import transaction
from django.utils import timezone

from ledger.models import JournalEntry
from ledger.services import EntryBuilder, LedgerError, create_entry, void_entry

from .models import ContributionBatch


@transaction.atomic
def post_batch(batch, user):
    """Deposit the batch: debit the bank account and credit each income account, per fund."""
    batch = ContributionBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != ContributionBatch.OPEN:
        raise LedgerError("This batch has already been posted.")
    contributions = list(batch.contributions.select_related("fund", "account"))
    if not contributions:
        raise LedgerError("Add at least one contribution before posting.")
    total = sum(c.amount for c in contributions)
    if batch.control_total is not None and batch.control_total != total:
        raise LedgerError(
            f"The entered contributions ({total:,.2f}) do not match the count sheet total "
            f"({batch.control_total:,.2f}). Find the difference before posting."
        )
    builder = EntryBuilder()
    for c in contributions:
        builder.debit(batch.deposit_account, c.fund, c.amount)
        builder.credit(c.account, c.fund, c.amount)
    entry = create_entry(
        date=batch.date,
        memo=f"Deposit {batch.number}: {batch.description}",
        lines=builder.lines(),
        user=user,
        source_type=JournalEntry.SOURCE_GIVING,
        source_id=batch.pk,
    )
    batch.status = ContributionBatch.POSTED
    batch.journal_entry = entry
    batch.posted_by = user
    batch.posted_at = timezone.now()
    batch.save()
    return batch


@transaction.atomic
def unpost_batch(batch, user, reason=""):
    """Void the deposit entry and reopen the batch so mistakes can be corrected."""
    if batch.status != ContributionBatch.POSTED:
        raise LedgerError("Only posted batches can be reopened.")
    if batch.journal_entry and batch.journal_entry.status == JournalEntry.POSTED:
        void_entry(batch.journal_entry, user, reason or f"Batch {batch.number} reopened for correction")
    batch.status = ContributionBatch.OPEN
    batch.journal_entry = None
    batch.posted_by = None
    batch.posted_at = None
    batch.save()
    return batch
