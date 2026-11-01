"""Screens for linking bank and M-Pesa accounts, and the callbacks Safaricom posts payments to."""

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.permissions import has_cap, require_cap
from giving.models import Donor
from ledger.models import Account, Fund, JournalEntry

from . import daraja, services
from .forms import BankConnectionForm, StatementUploadForm
from .models import BankConnection, BankTransaction
from .parsers import StatementError
from .services import FeedError

log = logging.getLogger(__name__)


def _feed_account(pk):
    return get_object_or_404(Account, pk=pk, subtype__in=["bank", "cash"])


def _callback_urls(request, connection):
    return {
        "confirm": request.build_absolute_uri(reverse("c2b_confirm", args=[connection.token])),
        "validate": request.build_absolute_uri(reverse("c2b_validate", args=[connection.token])),
    }


# ----------------------------------------------------------------- linking

@require_cap("manage_settings")
def link(request, account_pk):
    account = _feed_account(account_pk)
    connection = getattr(account, "bank_connection", None)
    form = BankConnectionForm(request.POST or None, instance=connection, initial=None if connection else {
        "default_fund": Fund.default(),
        "default_income_account": Account.objects.filter(type=Account.INCOME, subtype="contributions", is_active=True).first(),
        "method": BankConnection.MPESA if "pesa" in account.name.lower() else BankConnection.STATEMENT,
    })
    if request.method == "POST" and form.is_valid():
        connection = form.save(commit=False)
        connection.account = account
        if not connection.pk:
            connection.created_by = request.user
        connection.save()
        messages.success(request, f"{account.name} is linked." + (" Next, register the payment address with Safaricom." if connection.is_live else ""))
        return redirect(reverse("bankfeeds:link", args=[account.pk]) if connection.is_live else connection.get_absolute_url())
    return render(request, "bankfeeds/link.html", {
        "account": account, "connection": connection, "form": form,
        "urls": _callback_urls(request, connection) if connection and connection.is_live else None,
        "daraja_ready": daraja.configured(), "environment": settings.MPESA_ENVIRONMENT,
    })


@require_POST
@require_cap("manage_settings")
def unlink(request, account_pk):
    account = _feed_account(account_pk)
    connection = get_object_or_404(BankConnection, account=account)
    connection.delete()
    messages.success(request, f"{account.name} is no longer linked. Its bank feed was removed; the books are unchanged.")
    return redirect("ledger:banking")


@require_POST
@require_cap("manage_settings")
def register(request, account_pk):
    connection = get_object_or_404(BankConnection, account_id=account_pk, method=BankConnection.MPESA)
    urls = _callback_urls(request, connection)
    try:
        daraja.register_urls(connection.shortcode, urls["confirm"], urls["validate"])
    except daraja.DarajaError as e:
        messages.error(request, f"Safaricom didn't accept the registration: {e}")
    else:
        connection.registered_at = timezone.now()
        connection.save(update_fields=["registered_at"])
        messages.success(request, f"Registered with Safaricom. Payments to {connection.shortcode} will now appear in the bank feed.")
    return redirect("bankfeeds:link", account_pk=account_pk)


# -------------------------------------------------------------------- feed

TABS = [(BankTransaction.NEW, "To review"), (BankTransaction.MATCHED, "Matched"),
        (BankTransaction.RECORDED, "Gifts"), (BankTransaction.IGNORED, "Ignored"), ("all", "All")]


@require_cap("manage_ledger")
def feed(request, account_pk):
    account = _feed_account(account_pk)
    connection = getattr(account, "bank_connection", None)
    if connection is None:
        if has_cap(request.user, "manage_settings"):
            return redirect("bankfeeds:link", account_pk=account.pk)
        messages.info(request, f"{account.name} isn't linked yet. Ask the treasurer or an administrator to link it.")
        return redirect("ledger:banking")
    status = request.GET.get("status", BankTransaction.NEW)
    qs = connection.transactions.select_related("journal_entry", "contribution__batch", "contribution__donor")
    if status != "all":
        qs = qs.filter(status=status)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    rows = []
    for t in page:
        row = {"t": t}
        if t.status == BankTransaction.NEW:
            row["candidates"] = services.match_candidates(t)[:3]
            if t.money_in:
                row["guess"] = services.guess_gift(connection, t, by_name=True)
            else:
                row["spend_guess"] = services.guess_spending(t)
        rows.append(row)
    imports = list(connection.imports.all()[:5])
    for imp in imports:
        if imp.closing_balance is not None and imp.last_date:
            imp.book_balance = account.balance(end=imp.last_date)
            imp.difference = imp.closing_balance - imp.book_balance
    return render(request, "bankfeeds/feed.html", {
        "account": account, "connection": connection, "rows": rows, "page_obj": page, "status": status,
        "tabs": TABS, "counts": services.counts(connection), "upload_form": StatementUploadForm(),
        "imports": imports,
        "funds": Fund.objects.filter(is_active=True),
        "income_accounts": Account.objects.filter(type=Account.INCOME, is_active=True),
        "expense_accounts": Account.objects.filter(type=Account.EXPENSE, is_active=True),
        "donors": Donor.objects.filter(is_active=True).only("id", "first_name", "last_name", "organization_name", "donor_type", "envelope_number"),
        "can_manage_link": has_cap(request.user, "manage_settings"),
    })


@require_POST
@require_cap("manage_ledger")
def import_statement(request, account_pk):
    connection = get_object_or_404(BankConnection, account_id=account_pk)
    form = StatementUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
        return redirect(connection.get_absolute_url())
    f = form.cleaned_data["file"]
    try:
        imp = services.import_statement(connection, f.name, f.read(), request.user)
    except StatementError as e:
        messages.error(request, str(e))
    else:
        text = f"Imported {imp.added} line{'s' if imp.added != 1 else ''} from {imp.file_name}"
        if imp.skipped:
            text += f" ({imp.skipped} already imported)"
        text += f". {imp.matched} matched to the books automatically."
        messages.success(request, text)
    return redirect(connection.get_absolute_url())


@require_POST
@require_cap("manage_ledger")
def auto_match(request, account_pk):
    connection = get_object_or_404(BankConnection, account_id=account_pk)
    n = services.auto_match(connection)
    messages.success(request, f"{n} line{'s' if n != 1 else ''} matched." if n else "Nothing new to match automatically.")
    return redirect(connection.get_absolute_url())


@require_POST
@require_cap("manage_ledger")
def line_action(request, pk):
    txn = get_object_or_404(BankTransaction.objects.select_related("connection", "account"), pk=pk)
    action = request.POST.get("action")
    try:
        if action == "match":
            entry = get_object_or_404(JournalEntry, pk=request.POST.get("entry") or 0)
            services.match(txn, entry, request.user)
            messages.success(request, f"Matched to {entry.number}.")
        elif action == "ignore":
            services.ignore(txn, request.user)
        elif action == "undo":
            services.undo(txn, request.user)
            messages.success(request, "Put back for review.")
        elif action == "record":
            fund = get_object_or_404(Fund, pk=request.POST.get("fund") or 0)
            category = get_object_or_404(Account, pk=request.POST.get("category") or 0)
            if txn.money_in and request.POST.get("kind") == "gift":
                donor = Donor.objects.filter(pk=request.POST.get("donor") or 0).first()
                gift = services.record_gift(txn, fund, category, donor=donor, user=request.user)
                messages.success(request, f"Added to offering batch {gift.batch.number}. Post the batch when it's checked.")
            else:
                entry = services.record_entry(txn, category, fund, request.user, memo=request.POST.get("memo", "").strip())
                messages.success(request, f"Recorded as {entry.number}.")
        else:
            raise Http404
    except FeedError as e:
        messages.error(request, str(e))
    back = request.POST.get("next") or txn.connection.get_absolute_url()
    return redirect(back if back.startswith("/") else txn.connection.get_absolute_url())


# ------------------------------------------------------- Safaricom callbacks

def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")


def _live_connection(request, token):
    if settings.MPESA_ALLOWED_IPS and _client_ip(request) not in settings.MPESA_ALLOWED_IPS:
        return None
    return BankConnection.objects.select_related("account").filter(token=token, method=BankConnection.MPESA).first()


def _payload(request):
    try:
        data = json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


ACCEPTED = {"ResultCode": 0, "ResultDesc": "Accepted"}


@csrf_exempt
@login_not_required
@require_POST
def c2b_validate(request, token):
    connection = _live_connection(request, token)
    if connection is None:
        return JsonResponse({"ResultCode": "C2B00016", "ResultDesc": "Rejected"}, status=404)
    return JsonResponse(ACCEPTED)


@csrf_exempt
@login_not_required
@require_POST
def c2b_confirm(request, token):
    connection = _live_connection(request, token)
    if connection is None:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Unknown address"}, status=404)
    payload = _payload(request)
    if payload is None:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Not JSON"}, status=400)
    short = str(payload.get("BusinessShortCode") or "").strip()
    if connection.shortcode and short and short != connection.shortcode:
        log.warning("M-Pesa payment for short code %s arrived at the address for %s; ignored.", short, connection.shortcode)
        return JsonResponse(ACCEPTED)
    try:
        services.receive_c2b(connection, payload)
    except FeedError as e:
        log.warning("M-Pesa payment not stored: %s", e)
    return JsonResponse(ACCEPTED)
