from collections import OrderedDict

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.permissions import require_cap
from core.utils import ZERO, csv_response
from core.views import document_context
from ledger.services import LedgerError

from . import services
from .forms import DepreciationRunForm, DisposalForm, FixedAssetForm
from .models import DepreciationRun, FixedAsset


@require_cap("view_finance")
def asset_list(request):
    show = request.GET.get("show", "active")
    assets = FixedAsset.objects.select_related("fund", "asset_account").prefetch_related("depreciation_entries__run")
    if show == "active":
        assets = assets.filter(status=FixedAsset.ACTIVE)
    elif show == "disposed":
        assets = assets.filter(status=FixedAsset.DISPOSED)
    groups = OrderedDict()
    labels = dict(FixedAsset.CATEGORY_CHOICES)
    totals = {"cost": ZERO, "accumulated": ZERO, "book": ZERO}
    rows = []
    for a in assets:
        acc = a.accumulated_depreciation
        row = {"asset": a, "accumulated": acc, "book": a.cost - acc}
        rows.append(row)
        groups.setdefault(labels[a.category], []).append(row)
        totals["cost"] += a.cost
        totals["accumulated"] += acc
        totals["book"] += a.cost - acc
    if request.GET.get("export") == "csv":
        return csv_response("fixed-assets.csv", ["Asset", "Category", "Tag", "Serial", "Location", "Acquired", "Cost", "Salvage",
                                                 "Life (months)", "Accumulated depreciation", "Book value", "Status"], [
            [r["asset"].name, r["asset"].get_category_display(), r["asset"].tag_number, r["asset"].serial_number, r["asset"].location,
             r["asset"].acquisition_date, r["asset"].cost, r["asset"].salvage_value, r["asset"].useful_life_months,
             r["accumulated"], r["book"], r["asset"].get_status_display()] for r in rows])
    return render(request, "fixedassets/asset_list.html", {
        "groups": groups, "totals": totals, "show": show,
        "last_run": DepreciationRun.objects.filter(is_void=False).first(),
    })


@require_cap("view_finance")
def asset_detail(request, pk):
    asset = get_object_or_404(FixedAsset.objects.select_related("fund", "asset_account", "accumulated_account", "expense_account"), pk=pk)
    return render(request, "fixedassets/asset_detail.html", {
        "asset": asset, "entries": asset.depreciation_entries.select_related("run").order_by("-period_end"),
        **document_context(asset, request.user),
    })


@require_cap("manage_assets")
def asset_edit(request, pk=None):
    asset = get_object_or_404(FixedAsset, pk=pk) if pk else None
    form = FixedAssetForm(request.POST or None, instance=asset)
    if request.method == "POST" and form.is_valid():
        asset = form.save()
        messages.success(request, f"{asset} saved.")
        return redirect(asset.get_absolute_url())
    return render(request, "fixedassets/asset_form.html", {"form": form, "asset": asset})


@require_cap("manage_assets")
def asset_dispose(request, pk):
    asset = get_object_or_404(FixedAsset, pk=pk)
    form = DisposalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.dispose_asset(asset, user=request.user, **form.cleaned_data)
        except LedgerError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, f"{asset} removed from the books.")
            return redirect(asset.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Dispose of {asset}",
        "subtitle": f"Cost {asset.cost:,.2f}, book value {asset.book_value:,.2f}. Any gain or loss is recorded automatically.",
        "submit_label": "Record disposal", "max_width": "720px", "cancel_url": asset.get_absolute_url(),
    })


@require_cap("view_finance")
def run_list(request):
    return render(request, "fixedassets/run_list.html", {"runs": DepreciationRun.objects.select_related("journal_entry", "created_by")})


@require_cap("manage_assets")
def run_create(request):
    form = DepreciationRunForm(request.POST or request.GET or None)
    preview = []
    if form.is_bound and form.is_valid():
        through = form.cleaned_data["through"]
        if request.method == "POST":
            try:
                run = services.run_depreciation(through, request.user)
            except LedgerError as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, f"Depreciation of {run.total:,.2f} recorded through {run.through_date:%B %Y}.")
                return redirect(run.get_absolute_url())
        preview = services.preview(through)
    return render(request, "fixedassets/run_form.html", {
        "form": form, "preview": preview, "preview_total": sum((p[2] for p in preview), ZERO),
    })


@require_cap("view_finance")
def run_detail(request, pk):
    run = get_object_or_404(DepreciationRun, pk=pk)
    return render(request, "fixedassets/run_detail.html", {"run": run, "entries": run.entries.select_related("asset")})


@require_POST
@require_cap("manage_assets")
def run_void(request, pk):
    run = get_object_or_404(DepreciationRun, pk=pk)
    try:
        services.void_depreciation_run(run, request.user)
        messages.success(request, "Depreciation run voided.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(run.get_absolute_url())


