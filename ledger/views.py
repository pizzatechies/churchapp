from collections import OrderedDict
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import has_cap, require_cap
from core.utils import (
    ZERO,
    MoneySum,
    csv_response,
    fiscal_months,
    fiscal_year_label,
    fiscal_year_of,
    fiscal_year_range,
    parse_date,
    period_from_request,
    q2,
    to_decimal,
    today,
)
from core.views import document_context

from . import services
from .forms import (
    AccountForm,
    BankTransferForm,
    BudgetForm,
    FundForm,
    FundTransferForm,
    IncomeForm,
    JournalEntryForm,
    JournalLineFormSet,
    OpeningBalanceForm,
    OpeningBalanceFormSet,
    ReconciliationStartForm,
    VoidForm,
)
from .models import (
    Account,
    Budget,
    BudgetLine,
    Fund,
    JournalEntry,
    JournalLine,
    Reconciliation,
)
from .services import LedgerError

# ------------------------------------------------------------------ accounts

@require_cap("view_finance")
def account_list(request):
    show_inactive = request.GET.get("inactive") == "1"
    accounts = Account.objects.all() if show_inactive else Account.objects.filter(is_active=True)
    balances = services.account_balances(end=today())
    fy_start, _ = fiscal_year_range(fiscal_year_of(today()))
    fy_balances = services.account_balances(start=fy_start, end=today())
    groups = OrderedDict((label, []) for _, label in Account.TYPE_CHOICES)
    labels = dict(Account.TYPE_CHOICES)
    for a in accounts:
        bal = balances.get(a.pk, ZERO) if a.is_balance_sheet else fy_balances.get(a.pk, ZERO)
        groups[labels[a.type]].append((a, bal))
    return render(request, "ledger/account_list.html", {"groups": groups, "show_inactive": show_inactive})


@require_cap("view_finance")
def account_detail(request, pk):
    account = get_object_or_404(Account, pk=pk)
    start, end, period = period_from_request(request)
    fund = Fund.objects.filter(pk=request.GET.get("fund")).first() if request.GET.get("fund") else None
    opening = account.balance(end=start - timedelta(days=1), fund=fund) if account.is_balance_sheet else ZERO
    lines = (
        account.lines.filter(entry__status=JournalEntry.POSTED, entry__date__gte=start, entry__date__lte=end)
        .select_related("entry", "fund", "reconciliation").order_by("entry__date", "entry_id", "id")
    )
    if fund:
        lines = lines.filter(fund=fund)
    rows, running = [], opening
    for line in lines:
        running += account.signed(line.debit, line.credit)
        rows.append((line, running))
    if request.GET.get("export") == "csv":
        return csv_response(
            f"account-{account.number}.csv",
            ["Date", "Entry", "Reference", "Memo", "Fund", "Debit", "Credit", "Balance"],
            [[l.entry.date, l.entry.number, l.entry.reference, l.description or l.entry.memo, l.fund.code,
              l.debit or "", l.credit or "", bal] for l, bal in rows],
        )
    fund_breakdown = []
    if account.is_balance_sheet:
        by_fund = services.account_fund_balances(end=end)
        fund_breakdown = [(f, by_fund.get((account.pk, f.pk), ZERO)) for f in Fund.objects.all()]
        fund_breakdown = [(f, b) for f, b in fund_breakdown if b]
    return render(request, "ledger/account_detail.html", {
        "account": account, "rows": rows, "opening": opening, "closing": running,
        "start": start, "end": end, "period": period, "fund": fund, "funds": Fund.objects.all(),
        "fund_breakdown": fund_breakdown,
        "totals": {"debit": sum((l.debit for l, _ in rows), ZERO), "credit": sum((l.credit for l, _ in rows), ZERO)},
        "last_rec": services.last_reconciled(account) if account.subtype in Account.PAYMENT_SUBTYPES else None,
    })


@require_cap("manage_settings")
def account_edit(request, pk=None):
    account = get_object_or_404(Account, pk=pk) if pk else None
    initial = {}
    if not account and request.GET.get("type"):
        initial["type"] = request.GET["type"]
    form = AccountForm(request.POST or None, instance=account, initial=initial)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        messages.success(request, f"Account {account} saved.")
        return redirect("ledger:account_list")
    return render(request, "ledger/account_form.html", {"form": form, "account": account})


# --------------------------------------------------------------------- funds

@require_cap("view_finance")
def fund_list(request):
    end = today()
    fy = fiscal_year_of(end)
    fy_start, _ = fiscal_year_range(fy)
    balances = services.fund_balances(end=end)
    opening = services.fund_balances(end=fy_start - timedelta(days=1))
    activity = services.totals_by("fund_id", "account__type", start=fy_start, end=end)
    rows = []
    for fund in Fund.objects.all():
        income = expense = ZERO
        dr, cr = activity.get((fund.pk, Account.INCOME), (ZERO, ZERO))
        income = cr - dr
        dr, cr = activity.get((fund.pk, Account.EXPENSE), (ZERO, ZERO))
        expense = dr - cr
        rows.append({
            "fund": fund, "opening": opening.get(fund.pk, ZERO), "income": income, "expense": expense,
            "balance": balances.get(fund.pk, ZERO),
        })
    total = {k: sum((r[k] for r in rows), ZERO) for k in ("opening", "income", "expense", "balance")}
    return render(request, "ledger/fund_list.html", {"rows": rows, "total": total, "fy_label": fiscal_year_label(fy)})


@require_cap("view_finance")
def fund_detail(request, pk):
    fund = get_object_or_404(Fund, pk=pk)
    start, end, period = period_from_request(request)
    balances = services.account_fund_balances(end=end, funds=[fund])
    period_bal = services.account_fund_balances(start=start, end=end, funds=[fund])
    accounts = {a.pk: a for a in Account.objects.all()}
    assets = [(accounts[a], b) for (a, f), b in balances.items() if accounts[a].type == Account.ASSET and b]
    liabilities = [(accounts[a], b) for (a, f), b in balances.items() if accounts[a].type == Account.LIABILITY and b]
    income = sorted([(accounts[a], b) for (a, f), b in period_bal.items() if accounts[a].type == Account.INCOME and b], key=lambda x: x[0].number)
    expenses = sorted([(accounts[a], b) for (a, f), b in period_bal.items() if accounts[a].type == Account.EXPENSE and b], key=lambda x: x[0].number)
    transfers = sum((b for (a, f), b in period_bal.items() if accounts[a].type == Account.EQUITY), ZERO)
    return render(request, "ledger/fund_detail.html", {
        "fund": fund, "start": start, "end": end, "period": period,
        "balance": fund.balance(end=end),
        "opening": fund.balance(end=start - timedelta(days=1)),
        "assets": sorted(assets, key=lambda x: x[0].number),
        "liabilities": sorted(liabilities, key=lambda x: x[0].number),
        "income": income, "expenses": expenses,
        "income_total": sum((b for _, b in income), ZERO),
        "expense_total": sum((b for _, b in expenses), ZERO),
        "transfers": transfers,
    })


@require_cap("manage_settings")
def fund_edit(request, pk=None):
    fund = get_object_or_404(Fund, pk=pk) if pk else None
    form = FundForm(request.POST or None, instance=fund)
    if request.method == "POST" and form.is_valid():
        fund = form.save()
        messages.success(request, f"Fund {fund} saved.")
        return redirect("ledger:fund_list")
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit {fund}" if fund else "New fund",
        "subtitle": "Funds track money given or set aside for a specific purpose.",
        "cancel_url": reverse("ledger:fund_list"),
    })


# ------------------------------------------------------------------- banking

@require_cap("view_finance")
def banking(request):
    balances = services.account_balances(end=today())
    accounts = []
    uncleared = dict(
        JournalLine.objects.filter(entry__status=JournalEntry.POSTED, reconciliation__isnull=True)
        .values_list("account").annotate(n=Count("id"))
    )
    from bankfeeds.models import BankConnection, BankTransaction

    connections = {c.account_id: c for c in BankConnection.objects.all()}
    to_review = dict(
        BankTransaction.objects.filter(status=BankTransaction.NEW).values_list("account").annotate(n=Count("id"))
    )
    for account in Account.payment_accounts():
        accounts.append({
            "account": account,
            "balance": balances.get(account.pk, ZERO),
            "last_rec": services.last_reconciled(account),
            "uncleared": uncleared.get(account.pk, 0),
            "connection": connections.get(account.pk),
            "to_review": to_review.get(account.pk, 0),
            "linkable": account.subtype in Account.CASH_SUBTYPES,
        })
    recent = (
        JournalLine.objects.filter(entry__status=JournalEntry.POSTED, account__subtype__in=Account.PAYMENT_SUBTYPES)
        .select_related("entry", "account", "fund").order_by("-entry__date", "-entry_id")[:15]
    )
    has_mpesa = any("pesa" in f"{a['account'].name} {a['account'].bank_name}".lower() for a in accounts)
    return render(request, "ledger/banking.html", {"accounts": accounts, "recent": recent, "has_mpesa": has_mpesa})


def _simple_posting_view(request, form_class, title, subtitle, action, success):
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            entry = action(form.cleaned_data)
        except LedgerError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, success)
            return redirect(entry.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": title, "subtitle": subtitle, "submit_label": "Record", "max_width": "760px",
        "cancel_url": reverse("ledger:banking"),
    })


@require_cap("manage_ledger")
def bank_transfer(request):
    return _simple_posting_view(
        request, BankTransferForm, "Transfer between accounts",
        "Move money between bank or cash accounts, e.g. checking to savings, or a petty cash top-up.",
        lambda d: services.record_bank_transfer(user=request.user, **d), "Transfer recorded.",
    )


@require_cap("manage_ledger")
def fund_transfer(request):
    return _simple_posting_view(
        request, FundTransferForm, "Transfer between funds",
        "Reassign money from one fund to another (for example a board-approved transfer). "
        "Only move donor-restricted money when the restriction allows it.",
        lambda d: services.record_fund_transfer(user=request.user, **d), "Fund transfer recorded.",
    )


@require_cap("manage_ledger")
def record_income(request):
    return _simple_posting_view(
        request, IncomeForm, "Record other income",
        "Facility rentals, interest, grants, fundraisers and other money that isn't a donor contribution.",
        lambda d: services.record_income(user=request.user, **d), "Income recorded.",
    )


# ----------------------------------------------------------- journal entries

@require_cap("view_finance")
def entry_list(request):
    entries = JournalEntry.objects.annotate(amount=MoneySum("lines__debit")).select_related("created_by").order_by("-date", "-id")
    q = request.GET.get("q", "").strip()
    source = request.GET.get("source", "")
    status = request.GET.get("status", "")
    start, end = parse_date(request.GET.get("start")), parse_date(request.GET.get("end"))
    if q:
        filters = Q(memo__icontains=q) | Q(reference__icontains=q) | Q(lines__description__icontains=q)
        digits = q.upper().replace("JE-", "")
        if digits.isdigit():
            filters |= Q(pk=int(digits))
        entries = entries.filter(filters).distinct()
    if source:
        entries = entries.filter(source_type=source)
    if status:
        entries = entries.filter(status=status)
    if start:
        entries = entries.filter(date__gte=start)
    if end:
        entries = entries.filter(date__lte=end)
    page = Paginator(entries, 40).get_page(request.GET.get("page"))
    return render(request, "ledger/entry_list.html", {
        "page_obj": page, "q": q, "source": source, "status": status, "start": start, "end": end,
        "sources": JournalEntry.SOURCE_CHOICES, "statuses": JournalEntry.STATUS_CHOICES,
    })


@require_cap("view_finance")
def entry_detail(request, pk):
    entry = get_object_or_404(JournalEntry.objects.select_related("created_by", "posted_by", "voided_by"), pk=pk)
    lines = entry.lines.select_related("account", "fund", "reconciliation")
    totals = {"debit": sum((l.debit for l in lines), ZERO), "credit": sum((l.credit for l in lines), ZERO)}
    return render(request, "ledger/entry_detail.html", {
        "entry": entry, "lines": lines, "totals": totals, "void_form": VoidForm(),
        **document_context(entry, request.user),
    })


def _lines_from_formset(formset):
    lines = []
    for form in formset.forms:
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            continue
        d = form.cleaned_data
        if not (d.get("debit") or d.get("credit")):
            continue
        lines.append(services.Line(d["account"], d["fund"], d.get("debit") or ZERO, d.get("credit") or ZERO, d.get("description", "")))
    return lines


@require_cap("manage_ledger")
def entry_edit(request, pk=None):
    entry = get_object_or_404(JournalEntry, pk=pk) if pk else None
    if entry and not entry.is_editable:
        messages.error(request, "Only draft journal entries can be edited.")
        return redirect(entry.get_absolute_url())
    copy_from = None
    if not entry and request.GET.get("copy"):
        copy_from = JournalEntry.objects.filter(pk=request.GET["copy"]).first()
    source = entry or copy_from
    initial_lines = [
        {"account": l.account_id, "fund": l.fund_id, "description": l.description,
         "debit": l.debit or None, "credit": l.credit or None}
        for l in source.lines.all()
    ] if source else []
    form = JournalEntryForm(request.POST or None, instance=entry,
                            initial={"memo": copy_from.memo, "reference": copy_from.reference} if copy_from else None)
    formset = JournalLineFormSet(request.POST or None, prefix="lines", initial=initial_lines or None)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        lines = _lines_from_formset(formset)
        status = JournalEntry.DRAFT if "save_draft" in request.POST else JournalEntry.POSTED
        try:
            with transaction.atomic():
                if entry:
                    services.replace_draft(entry, date=form.cleaned_data["date"], memo=form.cleaned_data["memo"],
                                           reference=form.cleaned_data["reference"], lines=lines)
                    if status == JournalEntry.POSTED:
                        services.post_entry(entry, request.user)
                else:
                    entry = services.create_entry(
                        date=form.cleaned_data["date"], memo=form.cleaned_data["memo"],
                        reference=form.cleaned_data["reference"], lines=lines, user=request.user, status=status,
                    )
        except LedgerError as e:
            form.add_error(None, str(e))
            if pk is None:
                entry = None
        else:
            messages.success(request, "Journal entry saved as draft." if status == JournalEntry.DRAFT else "Journal entry posted.")
            return redirect(entry.get_absolute_url())
    return render(request, "ledger/entry_form.html", {"form": form, "formset": formset, "entry": entry})


@require_POST
@require_cap("manage_ledger")
def entry_post(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    try:
        services.post_entry(entry, request.user)
        messages.success(request, f"{entry.number} posted.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(entry.get_absolute_url())


@require_POST
@require_cap("manage_ledger")
def entry_void(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    if entry.source_type != JournalEntry.SOURCE_MANUAL and entry.source_url():
        messages.error(request, "This entry was created by another document. Void or reopen it from there.")
        return redirect(entry.get_absolute_url())
    form = VoidForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please give a reason for voiding.")
        return redirect(entry.get_absolute_url())
    try:
        services.void_entry(entry, request.user, form.cleaned_data["reason"])
        messages.success(request, f"{entry.number} voided.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(entry.get_absolute_url())


@require_POST
@require_cap("manage_ledger")
def entry_delete(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    try:
        services.delete_draft(entry)
        messages.success(request, "Draft deleted.")
        return redirect("ledger:entry_list")
    except LedgerError as e:
        messages.error(request, str(e))
        return redirect(entry.get_absolute_url())


# --------------------------------------------------------- opening balances

@require_cap("manage_settings")
def opening_balances(request):
    form = OpeningBalanceForm(request.POST or None, initial={"date": today().replace(month=1, day=1) - timedelta(days=1)})
    initial = [{"account": a.pk} for a in Account.objects.filter(subtype__in=["bank", "cash"], is_active=True)]
    formset = OpeningBalanceFormSet(request.POST or None, prefix="rows", initial=initial or None)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        rows = [
            (f.cleaned_data["account"], f.cleaned_data["fund"], f.cleaned_data["balance"])
            for f in formset.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("balance")
            and f.cleaned_data.get("account") and f.cleaned_data.get("fund")
        ]
        try:
            entry = services.record_opening_balances(date=form.cleaned_data["date"], rows=rows, user=request.user)
        except LedgerError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, "Opening balances recorded.")
            return redirect(entry.get_absolute_url())
    existing = JournalEntry.objects.filter(source_type=JournalEntry.SOURCE_OPENING, status=JournalEntry.POSTED)
    return render(request, "ledger/opening_balances.html", {"form": form, "formset": formset, "existing": existing})


# ------------------------------------------------------------ reconciliation

@require_cap("view_finance")
def reconciliation_list(request):
    recs = Reconciliation.objects.select_related("account", "completed_by")
    accounts = []
    for account in Account.payment_accounts():
        accounts.append((account, services.last_reconciled(account), account.reconciliations.filter(status=Reconciliation.IN_PROGRESS).first()))
    return render(request, "ledger/reconciliation_list.html", {"recs": recs[:60], "accounts": accounts})


@require_cap("manage_ledger")
def reconciliation_start(request):
    initial = {}
    if request.GET.get("account"):
        initial["account"] = request.GET["account"]
    form = ReconciliationStartForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            rec = services.start_reconciliation(user=request.user, **form.cleaned_data)
        except LedgerError as e:
            form.add_error(None, str(e))
        else:
            return redirect(rec.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": "Reconcile an account",
        "subtitle": "Enter the closing date and balance from your bank or credit card statement.",
        "submit_label": "Start reconciling", "max_width": "640px", "cancel_url": reverse("ledger:reconciliation_list"),
    })


@require_cap("view_finance")
def reconciliation_detail(request, pk):
    rec = get_object_or_404(Reconciliation.objects.select_related("account"), pk=pk)
    editable = rec.status == Reconciliation.IN_PROGRESS and has_cap(request.user, "manage_ledger")
    if request.method == "POST":
        if not editable:
            messages.error(request, "This reconciliation can't be changed.")
            return redirect(rec.get_absolute_url())
        try:
            services.set_cleared(rec, request.POST.getlist("cleared"))
            if "finish" in request.POST:
                services.complete_reconciliation(rec, request.user)
                messages.success(request, f"{rec.account.name} reconciled through {rec.statement_date:%b %d, %Y}.")
            else:
                messages.success(request, "Progress saved.")
        except LedgerError as e:
            messages.error(request, str(e))
        return redirect(rec.get_absolute_url())
    from bankfeeds.services import feed_entry_line_ids

    lines = services.reconciliation_candidates(rec) if rec.status == Reconciliation.IN_PROGRESS else rec.lines.select_related("entry", "fund").order_by("entry__date")
    sign = 1 if rec.account.is_debit_normal else -1
    items = [(line, (line.debit - line.credit) * sign) for line in lines]
    return render(request, "ledger/reconciliation_detail.html", {
        "rec": rec, "items": items, "editable": editable, "in_feed": feed_entry_line_ids(rec),
        "has_feed": hasattr(rec.account, "bank_connection"), **document_context(rec, request.user),
    })


@require_POST
@require_cap("manage_settings")
def reconciliation_reopen(request, pk):
    rec = get_object_or_404(Reconciliation, pk=pk)
    try:
        services.reopen_reconciliation(rec)
        messages.success(request, "Reconciliation reopened.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(rec.get_absolute_url())


@require_POST
@require_cap("manage_ledger")
def reconciliation_delete(request, pk):
    rec = get_object_or_404(Reconciliation, pk=pk)
    if rec.status != Reconciliation.IN_PROGRESS:
        messages.error(request, "Completed reconciliations can't be deleted.")
        return redirect(rec.get_absolute_url())
    rec.lines.update(reconciliation=None)
    rec.delete()
    messages.success(request, "Reconciliation deleted.")
    return redirect("ledger:reconciliation_list")


# ------------------------------------------------------------------- budgets

@require_cap("view_finance")
def budget_list(request):
    budgets = Budget.objects.select_related("fund").prefetch_related("lines__account")
    rows = [(b, b.totals()) for b in budgets]
    return render(request, "ledger/budget_list.html", {"rows": rows})


def _prefill_from_actuals(budget):
    """Seed a new budget with last fiscal year's actual monthly figures."""
    months = fiscal_months(budget.fiscal_year - 1)
    lines = {}
    for i, first, last in months:
        for account_id, amount in services.account_balances(start=first, end=last, funds=[budget.fund]).items():
            lines.setdefault(account_id, [ZERO] * 12)[i] = amount
    accounts = {a.pk: a for a in Account.objects.filter(type__in=[Account.INCOME, Account.EXPENSE], is_active=True)}
    BudgetLine.objects.bulk_create([
        BudgetLine(budget=budget, account=accounts[a], months=[str(q2(max(v, ZERO))) for v in amounts])
        for a, amounts in lines.items() if a in accounts and any(amounts)
    ])


@require_cap("manage_budget")
def budget_create(request):
    form = BudgetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            budget = form.save()
            source = form.cleaned_data.get("copy_from")
            if source:
                BudgetLine.objects.bulk_create([
                    BudgetLine(budget=budget, account=l.account, months=l.months) for l in source.lines.all()
                ])
            elif not form.cleaned_data.get("blank"):
                _prefill_from_actuals(budget)
        messages.success(request, "Budget created. Adjust the amounts and save.")
        return redirect(budget.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": "New budget", "submit_label": "Create budget", "max_width": "760px",
        "subtitle": "One budget per fund per fiscal year. Amounts are entered monthly.",
        "cancel_url": reverse("ledger:budget_list"),
    })


@require_cap("view_finance")
def budget_detail(request, pk):
    budget = get_object_or_404(Budget.objects.select_related("fund"), pk=pk)
    can_edit = has_cap(request.user, "manage_budget")
    accounts = list(Account.objects.filter(type__in=[Account.INCOME, Account.EXPENSE]).filter(
        Q(is_active=True) | Q(budget_lines__budget=budget)).distinct().order_by("number"))
    existing = {l.account_id: l for l in budget.lines.all()}
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "You don't have permission to edit budgets.")
            return redirect(budget.get_absolute_url())
        with transaction.atomic():
            for account in accounts:
                values = [to_decimal(request.POST.get(f"a{account.pk}_m{i}")) for i in range(12)]
                line = existing.get(account.pk)
                if any(values):
                    if line is None:
                        line = BudgetLine(budget=budget, account=account)
                    line.months = [str(v) for v in values]
                    line.save()
                elif line is not None:
                    line.delete()
            if "approve" in request.POST:
                budget.status = Budget.APPROVED
                budget.approved_by = request.user
                budget.approved_at = timezone.now()
                budget.save()
        messages.success(request, "Budget approved." if "approve" in request.POST else "Budget saved.")
        return redirect(budget.get_absolute_url())
    months = fiscal_months(budget.fiscal_year)
    sections = []
    for type_, label in [(Account.INCOME, "Income"), (Account.EXPENSE, "Expenses")]:
        rows = []
        for a in accounts:
            if a.type != type_:
                continue
            line = existing.get(a.pk)
            amounts = line.month_amounts if line else [ZERO] * 12
            rows.append({"account": a, "months": [(i, amt) for i, amt in enumerate(amounts)], "total": sum(amounts, ZERO)})
        sections.append({"type": type_, "label": label, "rows": rows})
    return render(request, "ledger/budget_detail.html", {
        "budget": budget, "sections": sections, "months": months, "can_edit": can_edit, "totals": budget.totals(),
    })


@require_POST
@require_cap("manage_budget")
def budget_status(request, pk):
    budget = get_object_or_404(Budget, pk=pk)
    if request.POST.get("action") == "unapprove":
        budget.status = Budget.DRAFT
        budget.approved_by = None
        budget.approved_at = None
        budget.save()
        messages.success(request, "Budget returned to draft.")
    elif request.POST.get("action") == "delete":
        budget.delete()
        messages.success(request, "Budget deleted.")
        return redirect("ledger:budget_list")
    return redirect(budget.get_absolute_url())

