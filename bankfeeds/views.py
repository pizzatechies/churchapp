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

def _is_mpesa_named(account):
    name = f"{account.name} {account.bank_name}".lower()
    return "pesa" in name or "paybill" in name or "till" in name


@require_cap("manage_settings")
def link(request, account_pk):
    account = _feed_account(account_pk)
    connection = getattr(account, "bank_connection", None)
    wants_mpesa = request.GET.get("method") == BankConnection.MPESA or _is_mpesa_named(account)
    form = BankConnectionForm(request.POST or None, instance=connection, initial=None if connection else {
        "default_fund": Fund.default(),
        "default_income_account": Account.objects.filter(type=Account.INCOME, subtype="contributions", is_active=True).first(),
        "method": BankConnection.MPESA if wants_mpesa else BankConnection.STATEMENT,
    })
    if request.method == "POST" and form.is_valid():
        connection = form.save(commit=False)
        connection.account = account
        if not connection.pk:
            connection.created_by = request.user
        connection.save()
        messages.success(request, f"{account.name} is linked." + (" Next, register the payment address with Safaricom (step 3)." if connection.is_live else ""))
        return redirect(reverse("bankfeeds:link", args=[account.pk]) if connection.is_live else connection.get_absolute_url())
    live = connection and connection.is_live
    return render(request, "bankfeeds/link.html", {
        "account": account, "connection": connection, "form": form,
        "urls": _callback_urls(request, connection) if live else None,
        "daraja_ready": daraja.configured(), "env_environment": settings.MPESA_ENVIRONMENT,
        "bank_account_as_mpesa": live and not _is_mpesa_named(account),
        "mpesa_accounts": Account.objects.filter(subtype="bank", is_active=True, bank_connection__isnull=True).exclude(pk=account.pk),
        "sleeps": settings.ON_FREE_HOSTING,
        "line_count": connection.transactions.count() if connection else 0,
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
    environment = request.POST.get("environment") or connection.environment
    if environment not in dict(BankConnection.ENVIRONMENT_CHOICES):
        environment = BankConnection.PRODUCTION
    urls = _callback_urls(request, connection)
    try:
        daraja.register_urls(connection.shortcode, urls["confirm"], urls["validate"],
                             key=request.POST.get("consumer_key"), secret=request.POST.get("consumer_secret"), environment=environment)
    except daraja.DarajaError as e:
        messages.error(request, f"Safaricom didn't accept the registration: {e}")
    else:
        connection.registered_at, connection.environment = timezone.now(), environment
        connection.save(update_fields=["registered_at", "environment"])
        messages.success(request, f"Registered with Safaricom. Payments to {connection.shortcode} will now appear in the bank feed."
                         + (" Use “Simulate a payment” to try it." if environment == BankConnection.SANDBOX else ""))
    return redirect("bankfeeds:link", account_pk=account_pk)


@require_POST
@require_cap("manage_settings")
def mark_registered(request, account_pk):
    """For churches that registered the addresses on the Daraja portal themselves."""
    connection = get_object_or_404(BankConnection, account_id=account_pk, method=BankConnection.MPESA)
    connection.registered_at = timezone.now()
    connection.save(update_fields=["registered_at"])
    messages.success(request, "Noted as registered. The first payment to arrive will confirm it.")
    return redirect("bankfeeds:link", account_pk=account_pk)


@require_POST
@require_cap("manage_settings")
def check_address(request, account_pk):
    """Call our own payment address over the internet, as Safaricom will."""
    connection = get_object_or_404(BankConnection, account_id=account_pk, method=BankConnection.MPESA)
    url = _callback_urls(request, connection)["confirm"]
    try:
        daraja.check_addresses(url, url, connection.environment)
        daraja.self_check(url)
    except daraja.DarajaError as e:
        connection.last_check_ok, connection.last_check_note = False, str(e)[:255]
        messages.error(request, str(e))
    else:
        connection.last_check_ok, connection.last_check_note = True, "The payment address answered correctly from the internet."
        messages.success(request, "The payment address works: Safaricom will be able to reach it.")
    connection.last_check_at = timezone.now()
    connection.save(update_fields=["last_check_at", "last_check_ok", "last_check_note"])
    return redirect("bankfeeds:link", account_pk=account_pk)


@require_POST
@require_cap("manage_settings")
def simulate(request, account_pk):
    connection = get_object_or_404(BankConnection, account_id=account_pk, method=BankConnection.MPESA)
    if connection.environment != BankConnection.SANDBOX:
        messages.error(request, "Test payments only work in Safaricom's sandbox. Make a small real payment to try a live Paybill.")
        return redirect("bankfeeds:link", account_pk=account_pk)
    try:
        daraja.simulate_payment(connection.shortcode, request.POST.get("amount") or 10, request.POST.get("reference") or "TEST",
                                key=request.POST.get("consumer_key"), secret=request.POST.get("consumer_secret"))
    except daraja.DarajaError as e:
        messages.error(request, f"Safaricom didn't make the test payment: {e}")
    else:
        messages.success(request, "Safaricom accepted the test payment. It should appear in the bank feed within a minute.")
    return redirect("bankfeeds:link", account_pk=account_pk)


@require_POST
@require_cap("manage_settings")
def move_link(request, account_pk):
    """Move a live M-Pesa link from the bank current account to a separate M-Pesa account."""
    connection = get_object_or_404(BankConnection, account_id=account_pk, method=BankConnection.MPESA)
    if connection.transactions.exists():
        messages.error(request, "This link already has payments. Unlink it and link the M-Pesa account afresh, or keep it here.")
        return redirect("bankfeeds:link", account_pk=account_pk)
    target_pk = request.POST.get("target")
    if target_pk == "new":
        target = services.create_mpesa_account(connection.shortcode)
    else:
        target = get_object_or_404(Account, pk=target_pk or 0, subtype="bank", bank_connection__isnull=True)
    connection.account = target
    connection.save(update_fields=["account"])
    messages.success(request, f"The live M-Pesa link now belongs to {target.name}. The payment address stays the same, so "
                              "nothing needs to change at Safaricom.")
    return redirect("bankfeeds:link", account_pk=target.pk)


@require_POST
@require_cap("manage_settings")
def add_mpesa_account(request):
    shortcode = "".join(c for c in request.POST.get("shortcode", "") if c.isdigit())[:7]
    account = services.create_mpesa_account(shortcode)
    messages.success(request, f"{account.name} was added to the chart of accounts. Now link it to M-Pesa.")
    return redirect(f"{reverse('bankfeeds:link', args=[account.pk])}?method={BankConnection.MPESA}")


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
    if payload.get("TransactionType") == daraja.TEST_TRANSACTION_TYPE:
        # Ecclesia's own "check the payment address" call: answer, record nothing.
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Ecclesia payment address OK"})
    short = str(payload.get("BusinessShortCode") or "").strip()
    if connection.shortcode and short and short != connection.shortcode:
        # Tills report their store (head office) number, not the till number. The secret address
        # already proves the notice is for this church, so keep the payment and just note it.
        log.info("M-Pesa payment for short code %s arrived at the address for %s.", short, connection.shortcode)
    try:
        services.receive_c2b(connection, payload)
    except FeedError as e:
        log.warning("M-Pesa payment not stored: %s", e)
    return JsonResponse(ACCEPTED)
