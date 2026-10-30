from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import ChurchProfile
from core.permissions import has_cap, require_cap
from core.utils import ZERO, MoneySum, csv_response, parse_date, today
from core.views import document_context
from ledger.services import LedgerError

from . import services
from .forms import (
    ExpenseForm,
    ExpenseLineFormSet,
    PaymentForm,
    PayNowForm,
    ReviewForm,
    VendorForm,
    VoidReasonForm,
)
from .models import Expense, ExpensePayment, Vendor

STATUS_TABS = [
    ("", "All"),
    ("draft", "Drafts"),
    ("pending", "Awaiting approval"),
    ("unpaid", "Unpaid"),
    ("paid", "Paid"),
    ("rejected", "Rejected"),
    ("void", "Void"),
]


def _filter_status(qs, status):
    if status == "unpaid":
        return qs.filter(status__in=Expense.OPEN_BALANCE)
    if status:
        return qs.filter(status=status)
    return qs


@require_cap("manage_expenses", "approve_expenses")
def expense_list(request):
    expenses = Expense.objects.select_related("vendor", "requested_by")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    vendor_id = request.GET.get("vendor", "")
    start, end = parse_date(request.GET.get("start")), parse_date(request.GET.get("end"))
    expenses = _filter_status(expenses, status)
    if q:
        filters = Q(description__icontains=q) | Q(reference__icontains=q) | Q(vendor__name__icontains=q)
        digits = q.upper().replace("EX-", "")
        if digits.isdigit():
            filters |= Q(pk=int(digits))
        expenses = expenses.filter(filters)
    if vendor_id:
        expenses = expenses.filter(vendor_id=vendor_id)
    if start:
        expenses = expenses.filter(date__gte=start)
    if end:
        expenses = expenses.filter(date__lte=end)
    if request.GET.get("export") == "csv":
        return csv_response("expenses.csv", ["Number", "Date", "Due", "Payee", "Type", "Description", "Reference", "Status", "Total", "Paid", "Balance"], [
            [e.number, e.date, e.due_date or "", e.vendor.name, e.get_expense_type_display(), e.description, e.reference,
             e.get_status_display(), e.total, e.amount_paid, e.balance_due] for e in expenses
        ])
    totals = expenses.aggregate(total=MoneySum("total"), paid=MoneySum("amount_paid"))
    counts = dict(Expense.objects.values_list("status").annotate(n=Count("id")))
    counts["unpaid"] = counts.get("approved", 0) + counts.get("partial", 0)
    page = Paginator(expenses, 40).get_page(request.GET.get("page"))
    return render(request, "expenses/expense_list.html", {
        "page_obj": page, "status": status, "tabs": STATUS_TABS, "counts": counts, "q": q, "vendor_id": vendor_id,
        "vendors": Vendor.objects.all(), "start": start, "end": end,
        "totals": {k: v or ZERO for k, v in totals.items()},
        "outstanding": services.total_outstanding(),
    })


@require_cap("approve_expenses")
def approvals(request):
    pending = Expense.objects.filter(status=Expense.PENDING).select_related("vendor", "requested_by").prefetch_related("lines__account", "lines__fund")
    rows = [(e, services.can_approve(e, request.user)) for e in pending]
    return render(request, "expenses/approvals.html", {
        "rows": rows, "threshold": ChurchProfile.get().expense_approval_threshold,
    })


@require_cap("manage_expenses", "approve_expenses")
def expense_detail(request, pk):
    expense = get_object_or_404(Expense.objects.select_related("vendor", "requested_by", "reviewed_by", "journal_entry"), pk=pk)
    allowed, reason = services.can_approve(expense, request.user)
    return render(request, "expenses/expense_detail.html", {
        "expense": expense,
        "lines": expense.lines.select_related("account", "fund"),
        "payments": expense.payments.select_related("pay_from", "journal_entry", "created_by"),
        "can_manage": has_cap(request.user, "manage_expenses"),
        "can_approve": has_cap(request.user, "approve_expenses") and allowed,
        "approve_block_reason": reason if has_cap(request.user, "approve_expenses") else "",
        "can_pay": has_cap(request.user, "pay_expenses"),
        "review_form": ReviewForm(), "void_form": VoidReasonForm(),
        **document_context(expense, request.user),
    })


@require_cap("manage_expenses")
def expense_edit(request, pk=None):
    expense = get_object_or_404(Expense, pk=pk) if pk else None
    if expense and not expense.is_editable:
        messages.error(request, "Approved expenses can't be edited. Void it and enter a new one if it's wrong.")
        return redirect(expense.get_absolute_url())
    initial = {}
    if not expense and request.GET.get("vendor"):
        initial["vendor"] = request.GET["vendor"]
    form = ExpenseForm(request.POST or None, instance=expense, initial=initial)
    formset = ExpenseLineFormSet(request.POST or None, instance=expense or Expense(), prefix="lines")
    paynow = PayNowForm(request.POST or None, prefix="pay") if not expense else None
    if not request.POST and not expense and initial.get("vendor"):
        vendor = Vendor.objects.filter(pk=initial["vendor"]).first()
        if vendor and vendor.default_account_id:
            formset = ExpenseLineFormSet(instance=Expense(), prefix="lines", initial=[{"account": vendor.default_account_id}])
    if request.method == "POST" and form.is_valid() and formset.is_valid() and (paynow is None or paynow.is_valid()):
        try:
            with transaction.atomic():
                expense = form.save(commit=False)
                if not expense.pk:
                    expense.requested_by = request.user
                expense.save()
                formset.instance = expense
                formset.save()
                expense.recalculate_total()
                expense.save()
                if "submit" in request.POST or (paynow and paynow.cleaned_data.get("paid")):
                    expense = services.submit_expense(expense, request.user)
                    if paynow and paynow.cleaned_data.get("paid"):
                        if expense.status != Expense.APPROVED:
                            raise LedgerError(
                                "This expense is over the approval limit, so it can't be marked paid until it is approved. "
                                "Untick “already paid”, submit it, and record the payment after approval."
                            )
                        services.record_payment(
                            expense, request.user, date=expense.date, amount=expense.total,
                            pay_from=paynow.cleaned_data["pay_from"], method=paynow.cleaned_data["method"] or ExpensePayment.CHECK,
                            reference=paynow.cleaned_data["payment_reference"],
                        )
        except LedgerError as e:
            form.add_error(None, str(e))
            if pk is None:
                expense = None
        else:
            expense.refresh_from_db()
            if expense.status == Expense.PENDING:
                messages.success(request, f"{expense.number} submitted for approval.")
            elif expense.status == Expense.PAID:
                messages.success(request, f"{expense.number} recorded and paid.")
            elif expense.status == Expense.APPROVED:
                messages.success(request, f"{expense.number} approved automatically (under the approval limit) and ready to pay.")
            else:
                messages.success(request, f"{expense.number} saved as a draft.")
            return redirect(expense.get_absolute_url())
    return render(request, "expenses/expense_form.html", {
        "form": form, "formset": formset, "paynow": paynow, "expense": expense,
        "threshold": ChurchProfile.get().expense_approval_threshold,
    })


def _action(request, pk, func, success, *args):
    expense = get_object_or_404(Expense, pk=pk)
    try:
        func(expense, request.user, *args)
        messages.success(request, success.format(n=expense.number))
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(expense.get_absolute_url())


@require_POST
@require_cap("manage_expenses")
def expense_submit(request, pk):
    return _action(request, pk, services.submit_expense, "{n} submitted.")


@require_POST
@require_cap("approve_expenses")
def expense_approve(request, pk):
    note = request.POST.get("note", "")
    response = _action(request, pk, services.approve_expense, "{n} approved and posted to accounts payable.", note)
    if request.POST.get("next") == "approvals":
        return redirect("expenses:approvals")
    return response


@require_POST
@require_cap("approve_expenses")
def expense_reject(request, pk):
    response = _action(request, pk, services.reject_expense, "{n} rejected and returned to the requester.", request.POST.get("note", ""))
    if request.POST.get("next") == "approvals":
        return redirect("expenses:approvals")
    return response


@require_POST
@require_cap("manage_expenses")
def expense_void(request, pk):
    return _action(request, pk, services.void_expense, "{n} voided.", request.POST.get("reason", ""))


@require_POST
@require_cap("manage_expenses")
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if expense.status not in (Expense.DRAFT, Expense.REJECTED):
        messages.error(request, "Only drafts and rejected expenses can be deleted. Void it instead.")
        return redirect(expense.get_absolute_url())
    expense.delete()
    messages.success(request, "Expense deleted.")
    return redirect("expenses:expense_list")


@require_POST
@require_cap("manage_expenses")
def expense_duplicate(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    copy = services.duplicate_expense(expense, request.user)
    messages.success(request, f"Copied to new draft {copy.number}. Check the date and amounts.")
    return redirect("expenses:expense_edit", pk=copy.pk)


@require_cap("pay_expenses")
def payment_create(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if expense.status not in Expense.OPEN_BALANCE:
        messages.error(request, "Only approved, unpaid expenses can be paid.")
        return redirect(expense.get_absolute_url())
    form = PaymentForm(request.POST or None, expense=expense)
    if request.method == "POST" and form.is_valid():
        try:
            services.record_payment(expense, request.user, **{k: form.cleaned_data[k] for k in ("date", "amount", "pay_from", "method", "reference", "memo")})
        except LedgerError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, "Payment recorded.")
            return redirect(expense.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Pay {expense.number} · {expense.vendor}",
        "subtitle": f"Balance due {expense.balance_due:,.2f} of {expense.total:,.2f}.",
        "submit_label": "Record payment", "max_width": "760px", "cancel_url": expense.get_absolute_url(),
    })


@require_POST
@require_cap("pay_expenses")
def payment_void(request, pk):
    payment = get_object_or_404(ExpensePayment, pk=pk)
    try:
        services.void_payment(payment, request.user, request.POST.get("reason", ""))
        messages.success(request, "Payment voided; the expense is unpaid again.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(payment.expense.get_absolute_url())


# ------------------------------------------------------------------- vendors

@require_cap("manage_expenses")
def vendor_list(request):
    vendors = Vendor.objects.annotate(
        open_balance=MoneySum("expenses__total", filter=Q(expenses__status__in=Expense.OPEN_BALANCE)),
        open_paid=MoneySum("expenses__amount_paid", filter=Q(expenses__status__in=Expense.OPEN_BALANCE)),
        bills=Count("expenses"),
    )
    q = request.GET.get("q", "").strip()
    if q:
        vendors = vendors.filter(Q(name__icontains=q) | Q(contact_name__icontains=q) | Q(email__icontains=q))
    if request.GET.get("inactive") != "1":
        vendors = vendors.filter(is_active=True)
    vendors = list(vendors.select_related("default_account"))
    for v in vendors:
        v.owed = (v.open_balance or ZERO) - (v.open_paid or ZERO)
    return render(request, "expenses/vendor_list.html", {"vendors": vendors, "q": q})


@require_cap("manage_expenses")
def vendor_detail(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk)
    expenses = vendor.expenses.order_by("-date", "-id")
    year = today().year
    return render(request, "expenses/vendor_detail.html", {
        "vendor": vendor, "expenses": expenses[:100],
        "paid_this_year": vendor.total_paid(start=today().replace(month=1, day=1)),
        "paid_last_year": vendor.total_paid(start=today().replace(year=year - 1, month=1, day=1), end=today().replace(year=year - 1, month=12, day=31)),
        "open_balance": sum((e.balance_due for e in expenses.filter(status__in=Expense.OPEN_BALANCE)), ZERO),
        **document_context(vendor, request.user),
    })


@require_cap("manage_expenses")
def vendor_edit(request, pk=None):
    vendor = get_object_or_404(Vendor, pk=pk) if pk else None
    form = VendorForm(request.POST or None, instance=vendor)
    if request.method == "POST" and form.is_valid():
        vendor = form.save()
        messages.success(request, f"{vendor} saved.")
        return redirect(vendor.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit {vendor}" if vendor else "New vendor / payee",
        "subtitle": "Suppliers, utilities, contractors — and members or staff you reimburse.",
        "cancel_url": reverse("expenses:vendor_list"),
    })
