import csv
import io
from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.permissions import has_cap, require_cap
from core.utils import (
    ZERO,
    MoneySum,
    csv_response,
    fiscal_year_of,
    fiscal_year_range,
    parse_date,
    today,
)
from core.views import document_context
from ledger.services import LedgerError

from . import services
from .forms import (
    BatchForm,
    CampaignForm,
    ContributionForm,
    DonorForm,
    DonorImportForm,
    PledgeForm,
    StatementForm,
)
from .models import Campaign, Contribution, ContributionBatch, Donor, Pledge

# ------------------------------------------------------------------- batches

@require_cap("manage_giving")
def batch_list(request):
    batches = ContributionBatch.objects.select_related("deposit_account").annotate(
        amount=MoneySum("contributions__amount"), gifts=Count("contributions"),
    )
    status = request.GET.get("status", "")
    if status:
        batches = batches.filter(status=status)
    page = Paginator(batches, 30).get_page(request.GET.get("page"))
    open_count = ContributionBatch.objects.filter(status=ContributionBatch.OPEN).count()
    return render(request, "giving/batch_list.html", {"page_obj": page, "status": status, "open_count": open_count})


@require_cap("manage_giving")
def batch_edit(request, pk=None):
    batch = get_object_or_404(ContributionBatch, pk=pk) if pk else None
    if batch and not batch.is_open:
        messages.error(request, "Posted batches can't be edited. Reopen the batch first.")
        return redirect(batch.get_absolute_url())
    form = BatchForm(request.POST or None, instance=batch)
    if request.method == "POST" and form.is_valid():
        batch = form.save(commit=False)
        if not batch.pk:
            batch.created_by = request.user
        batch.save()
        batch.contributions.exclude(date=batch.date).filter(date__lt=batch.date.replace(day=1)).update(date=batch.date)
        messages.success(request, "Batch saved. Now enter the gifts.")
        return redirect(batch.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit {batch.number}" if batch else "New offering / deposit batch",
        "subtitle": "A batch is one bank deposit: a service's offering count, a midweek deposit or a month of online gifts.",
        "max_width": "760px", "cancel_url": reverse("giving:batch_list"),
    })


@require_cap("manage_giving")
def batch_detail(request, pk):
    batch = get_object_or_404(ContributionBatch.objects.select_related("deposit_account", "posted_by", "created_by"), pk=pk)
    form = None
    if batch.is_open:
        form = ContributionForm(request.POST or None, batch=batch)
        if request.method == "POST":
            if form.is_valid():
                contribution = form.save(commit=False)
                contribution.batch = batch
                contribution.save()
                messages.success(request, f"Added {contribution.amount:,.2f} from {contribution.donor or 'anonymous'}.")
                return redirect(batch.get_absolute_url() + "#entry")
        else:
            last = batch.contributions.order_by("-id").first()
            if last:
                form = ContributionForm(batch=batch, initial={"fund": last.fund_id, "account": last.account_id, "method": last.method})
    contributions = batch.contributions.select_related("donor", "fund", "account")
    total = batch.total
    return render(request, "giving/batch_detail.html", {
        "batch": batch, "form": form, "contributions": contributions, "total": total,
        "difference": (batch.control_total - total) if batch.control_total is not None else None,
        "can_post": has_cap(request.user, "post_giving"),
        **document_context(batch, request.user),
    })


@require_cap("manage_giving")
def contribution_edit(request, pk):
    contribution = get_object_or_404(Contribution.objects.select_related("batch"), pk=pk)
    batch = contribution.batch
    if not batch.is_open:
        messages.error(request, "This batch is posted. Reopen it to make changes.")
        return redirect(batch.get_absolute_url())
    form = ContributionForm(request.POST or None, instance=contribution, batch=batch)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Contribution updated.")
        return redirect(batch.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit contribution in {batch.number}", "cancel_url": batch.get_absolute_url(),
    })


@require_POST
@require_cap("manage_giving")
def contribution_delete(request, pk):
    contribution = get_object_or_404(Contribution.objects.select_related("batch"), pk=pk)
    batch = contribution.batch
    if not batch.is_open:
        messages.error(request, "This batch is posted. Reopen it to make changes.")
    else:
        contribution.delete()
        messages.success(request, "Contribution removed.")
    return redirect(batch.get_absolute_url())


@require_POST
@require_cap("post_giving")
def batch_post(request, pk):
    batch = get_object_or_404(ContributionBatch, pk=pk)
    try:
        batch = services.post_batch(batch, request.user)
        messages.success(request, f"{batch.number} posted: {batch.total:,.2f} deposited to {batch.deposit_account.name}.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(batch.get_absolute_url())


@require_POST
@require_cap("post_giving")
def batch_unpost(request, pk):
    batch = get_object_or_404(ContributionBatch, pk=pk)
    try:
        services.unpost_batch(batch, request.user, request.POST.get("reason", ""))
        messages.success(request, f"{batch.number} reopened. Its deposit entry was voided; post it again after correcting.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(batch.get_absolute_url())


@require_POST
@require_cap("manage_giving")
def batch_delete(request, pk):
    batch = get_object_or_404(ContributionBatch, pk=pk)
    if not batch.is_open:
        messages.error(request, "Posted batches can't be deleted.")
        return redirect(batch.get_absolute_url())
    batch.delete()
    messages.success(request, "Batch deleted.")
    return redirect("giving:batch_list")


# -------------------------------------------------------------------- donors

@require_cap("view_donors")
def donor_list(request):
    fy = fiscal_year_of(today())
    fy_start, fy_end = fiscal_year_range(fy)
    donors = Donor.objects.annotate(
        ytd=MoneySum("contributions__amount", filter=Q(
            contributions__batch__status=ContributionBatch.POSTED,
            contributions__date__gte=fy_start, contributions__date__lte=fy_end,
        )),
        last_gift=Max("contributions__date", filter=Q(contributions__batch__status=ContributionBatch.POSTED)),
    )
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "active")
    if q:
        donors = donors.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(organization_name__icontains=q)
            | Q(email__icontains=q) | Q(envelope_number__iexact=q) | Q(phone__icontains=q)
        )
    if status == "active":
        donors = donors.filter(is_active=True)
    elif status == "members":
        donors = donors.filter(is_member=True, is_active=True)
    elif status == "inactive":
        donors = donors.filter(is_active=False)
    sort = request.GET.get("sort", "name")
    donors = donors.order_by({"ytd": "-ytd", "last": "-last_gift"}.get(sort, "sort_name"))
    if request.GET.get("export") == "csv":
        return csv_response("donors.csv", [
            "Name", "Type", "Envelope", "Email", "Phone", "Address", "Address 2", "City", "State", "Postal code",
            "Country", "Member", "Active", f"Given FY{fy}", "Last gift",
        ], [[d.display_name, d.get_donor_type_display(), d.envelope_number or "", d.email, d.phone, d.address_line1,
             d.address_line2, d.city, d.state, d.postal_code, d.country, "Yes" if d.is_member else "No",
             "Yes" if d.is_active else "No", d.ytd or ZERO, d.last_gift or ""] for d in donors])
    page = Paginator(donors, 50).get_page(request.GET.get("page"))
    return render(request, "giving/donor_list.html", {"page_obj": page, "q": q, "status": status, "sort": sort})


@require_cap("view_donors")
def donor_detail(request, pk):
    donor = get_object_or_404(Donor, pk=pk)
    contributions = donor.posted_contributions().select_related("fund", "batch").order_by("-date", "-id")
    by_year = defaultdict(lambda: ZERO)
    for c in contributions:
        by_year[c.date.year] += c.amount
    pending = donor.contributions.filter(batch__status=ContributionBatch.OPEN).select_related("batch", "fund")
    return render(request, "giving/donor_detail.html", {
        "donor": donor, "contributions": contributions[:100], "count": contributions.count(),
        "by_year": sorted(by_year.items(), reverse=True), "pending": pending,
        "pledges": donor.pledges.select_related("campaign"),
        "lifetime": sum(by_year.values(), ZERO), "this_year": today().year,
    })


@require_cap("manage_giving")
def donor_edit(request, pk=None):
    donor = get_object_or_404(Donor, pk=pk) if pk else None
    form = DonorForm(request.POST or None, instance=donor)
    if request.method == "POST" and form.is_valid():
        donor = form.save()
        messages.success(request, f"{donor} saved.")
        return redirect(donor.get_absolute_url())
    return render(request, "giving/donor_form.html", {"form": form, "donor": donor})


IMPORT_COLUMNS = {
    "first_name": ["first name", "first_name", "firstname", "first"],
    "last_name": ["last name", "last_name", "lastname", "surname", "last"],
    "organization_name": ["organization", "organization_name", "company", "business"],
    "envelope_number": ["envelope", "envelope number", "envelope_number", "envelope #"],
    "email": ["email", "e-mail", "email address"],
    "phone": ["phone", "telephone", "mobile", "cell"],
    "address_line1": ["address", "address 1", "address_line1", "street"],
    "address_line2": ["address 2", "address_line2"],
    "city": ["city", "town"],
    "state": ["state", "province", "region"],
    "postal_code": ["zip", "postal code", "postal_code", "postcode", "zip code"],
    "country": ["country"],
}


@require_cap("manage_giving")
def donor_import(request):
    form = DonorImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        raw = form.cleaned_data["file"].read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))
        headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        mapping = {}
        for field, aliases in IMPORT_COLUMNS.items():
            for alias in aliases:
                if alias in headers:
                    mapping[field] = headers[alias]
                    break
        if not ({"first_name", "last_name", "organization_name"} & set(mapping)):
            form.add_error("file", "The file needs at least a 'First name' and 'Last name' (or 'Organization') column.")
        else:
            created, skipped, errors = 0, 0, []
            with transaction.atomic():
                for n, row in enumerate(reader, start=2):
                    values = {f: (row.get(col) or "").strip() for f, col in mapping.items()}
                    if not any(values.get(k) for k in ("first_name", "last_name", "organization_name")):
                        continue
                    env = values.get("envelope_number") or None
                    if env and Donor.objects.filter(envelope_number=env).exists():
                        skipped += 1
                        continue
                    duplicate = Donor.objects.filter(
                        first_name__iexact=values.get("first_name", ""), last_name__iexact=values.get("last_name", ""),
                        organization_name__iexact=values.get("organization_name", ""),
                    )
                    if values.get("email"):
                        duplicate = duplicate.filter(email__iexact=values["email"])
                    if duplicate.exists():
                        skipped += 1
                        continue
                    donor_type = Donor.ORGANIZATION if values.get("organization_name") and not values.get("last_name") else Donor.INDIVIDUAL
                    try:
                        with transaction.atomic():
                            Donor.objects.create(donor_type=donor_type, **{**values, "envelope_number": env})
                        created += 1
                    except Exception as e:  # noqa: BLE001 — report bad rows instead of failing the whole file
                        errors.append(f"Row {n}: {e}")
            result = {"created": created, "skipped": skipped, "errors": errors[:20]}
            messages.success(request, f"Imported {created} donor(s); skipped {skipped} already on file.")
    return render(request, "giving/donor_import.html", {"form": form, "result": result, "columns": IMPORT_COLUMNS})


# ----------------------------------------------------------------- campaigns

@require_cap("view_donors")
def campaign_list(request):
    campaigns = Campaign.objects.select_related("fund").prefetch_related("pledges")
    return render(request, "giving/campaign_list.html", {"campaigns": campaigns})


@require_cap("view_donors")
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("fund"), pk=pk)
    pledges = list(campaign.pledges.select_related("donor"))
    received = defaultdict(lambda: ZERO)
    for row in campaign.contributions().values("donor_id").annotate(t=MoneySum("amount")):
        received[row["donor_id"]] = row["t"]
    rows = [(p, received[p.donor_id], max(ZERO, p.amount - received[p.donor_id])) for p in pledges]
    non_pledged = sum((v for k, v in received.items() if k not in {p.donor_id for p in pledges}), ZERO)
    return render(request, "giving/campaign_detail.html", {
        "campaign": campaign, "rows": rows, "non_pledged": non_pledged,
        "total_pledged": sum((p.amount for p in pledges), ZERO),
        "pledge_received": sum((r for _, r, _ in rows), ZERO),
        "total_received": campaign.total_received,
    })


@require_cap("manage_giving")
def campaign_edit(request, pk=None):
    campaign = get_object_or_404(Campaign, pk=pk) if pk else None
    form = CampaignForm(request.POST or None, instance=campaign)
    if request.method == "POST" and form.is_valid():
        campaign = form.save()
        messages.success(request, "Campaign saved.")
        return redirect(campaign.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit {campaign}" if campaign else "New pledge campaign",
        "subtitle": "Gifts to the campaign's fund between its start and end dates count toward pledges.",
        "cancel_url": reverse("giving:campaign_list"),
    })


@require_cap("manage_giving")
def pledge_edit(request, pk=None):
    pledge = get_object_or_404(Pledge, pk=pk) if pk else None
    initial = {}
    if not pledge:
        if request.GET.get("campaign"):
            initial["campaign"] = request.GET["campaign"]
        if request.GET.get("donor"):
            initial["donor"] = request.GET["donor"]
    form = PledgeForm(request.POST or None, instance=pledge, initial=initial)
    if request.method == "POST":
        if "delete" in request.POST and pledge:
            campaign = pledge.campaign
            pledge.delete()
            messages.success(request, "Pledge deleted.")
            return redirect(campaign.get_absolute_url())
        if form.is_valid():
            pledge = form.save()
            messages.success(request, "Pledge saved.")
            return redirect(pledge.campaign.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": "Edit pledge" if pledge else "Record a pledge", "max_width": "760px",
        "cancel_url": reverse("giving:campaign_list"),
    })


# ---------------------------------------------------------------- statements

def statement_data(start, end, donor=None):
    contributions = Contribution.objects.filter(
        batch__status=ContributionBatch.POSTED, date__gte=start, date__lte=end, donor__isnull=False,
    ).select_related("fund", "donor").order_by("donor__sort_name", "date", "id")
    if donor:
        contributions = contributions.filter(donor=donor)
    statements = {}
    for c in contributions:
        s = statements.setdefault(c.donor_id, {
            "donor": c.donor, "gifts": [], "total": ZERO, "deductible": ZERO, "by_fund": defaultdict(lambda: ZERO),
        })
        s["gifts"].append(c)
        s["total"] += c.amount
        s["by_fund"][c.fund.name] += c.amount
        if c.is_deductible:
            s["deductible"] += c.amount
    result = list(statements.values())
    for s in result:
        s["by_fund"] = sorted(s["by_fund"].items())
    return result


@require_cap("view_donors")
def statements(request):
    form = StatementForm(request.GET or None)
    if request.GET and form.is_valid():
        start, end = form.period()
        donor = form.cleaned_data.get("donor")
        data = statement_data(start, end, donor)
        if request.GET.get("export") == "csv":
            return csv_response(
                f"giving-statements-{start}-{end}.csv",
                ["Donor", "Envelope", "Email", "Address", "City", "State", "Postal code", "Total", "Tax deductible"],
                [[s["donor"].display_name, s["donor"].envelope_number or "", s["donor"].email, s["donor"].address_line1,
                  s["donor"].city, s["donor"].state, s["donor"].postal_code, s["total"], s["deductible"]] for s in data],
            )
        return render(request, "giving/statements_print.html", {
            "statements": data, "start": start, "end": end, "generated": today(),
        })
    return render(request, "giving/statements.html", {"form": form})


@require_cap("view_donors")
def donor_statement(request, pk):
    donor = get_object_or_404(Donor, pk=pk)
    year = int(request.GET.get("year") or today().year)
    start = parse_date(request.GET.get("start")) or date(year, 1, 1)
    end = parse_date(request.GET.get("end")) or date(year, 12, 31)
    return render(request, "giving/statements_print.html", {
        "statements": statement_data(start, end, donor), "start": start, "end": end, "generated": today(),
        "single": donor,
    })
