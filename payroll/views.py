from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.permissions import require_cap
from core.utils import ZERO, today
from core.views import document_context
from ledger.services import LedgerError

from . import services
from .forms import (
    EmployeeForm,
    EmployeeItemFormSet,
    PaycheckForm,
    PayrollItemForm,
    PayrollRunForm,
)
from .models import Employee, Paycheck, PaycheckLine, PayrollItem, PayrollRun

# ---------------------------------------------------------------------- runs

@require_cap("view_payroll")
def run_list(request):
    runs = list(PayrollRun.objects.select_related("bank_account").prefetch_related("paychecks"))
    rows = [(r, r.totals(), r.paychecks.count()) for r in runs]
    year = today().year
    ytd = {"gross": ZERO, "net": ZERO, "employer": ZERO}
    for r, t, _ in rows:
        if r.status == PayrollRun.POSTED and r.pay_date.year == year:
            ytd["gross"] += t["gross"]
            ytd["net"] += t["net"]
            ytd["employer"] += t["employer"]
    return render(request, "payroll/run_list.html", {"rows": rows, "ytd": ytd, "year": year})


@require_cap("manage_payroll")
def run_create(request):
    form = PayrollRunForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            run = services.create_run(
                period_start=data["period_start"], period_end=data["period_end"], pay_date=data["pay_date"],
                bank_account=data["bank_account"], user=request.user, employees=data["employees"], memo=data["memo"],
            )
        except LedgerError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, "Paychecks generated. Review them, then post the payroll.")
            return redirect(run.get_absolute_url())
    return render(request, "payroll/run_form.html", {"form": form})


@require_cap("view_payroll")
def run_detail(request, pk):
    run = get_object_or_404(PayrollRun.objects.select_related("bank_account", "journal_entry"), pk=pk)
    paychecks = run.paychecks.select_related("employee").prefetch_related("lines__item")
    by_item = defaultdict(lambda: ZERO)
    kinds = {}
    for pc in paychecks:
        for line in pc.lines.all():
            by_item[line.item] += line.amount
            kinds[line.item] = line.item.kind
    summary = [
        (label, [(item, amt) for item, amt in sorted(by_item.items(), key=lambda x: x[0].sort_order) if kinds[item] == kind])
        for label, kind in [("Earnings", PayrollItem.EARNING), ("Withheld from staff", PayrollItem.DEDUCTION), ("Employer costs", PayrollItem.EMPLOYER)]
    ]
    missing = Employee.objects.filter(is_active=True).exclude(pk__in=paychecks.values("employee"))
    return render(request, "payroll/run_detail.html", {
        "run": run, "paychecks": paychecks, "totals": run.totals(), "summary": summary, "missing": missing,
    })


@require_POST
@require_cap("manage_payroll")
def run_post(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    try:
        services.post_run(run, request.user)
        messages.success(request, "Payroll posted to the books.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(run.get_absolute_url())


@require_POST
@require_cap("manage_payroll")
def run_void(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    try:
        services.void_run(run, request.user, request.POST.get("reason", ""))
        messages.success(request, "Payroll run voided.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(run.get_absolute_url())


@require_POST
@require_cap("manage_payroll")
def run_delete(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    if run.status != PayrollRun.DRAFT:
        messages.error(request, "Only draft payroll runs can be deleted.")
        return redirect(run.get_absolute_url())
    run.delete()
    messages.success(request, "Draft payroll deleted.")
    return redirect("payroll:run_list")


@require_POST
@require_cap("manage_payroll")
def paycheck_add(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    employee = get_object_or_404(Employee, pk=request.POST.get("employee"))
    try:
        services.build_paycheck(run, employee)
        messages.success(request, f"Added a paycheck for {employee}.")
    except LedgerError as e:
        messages.error(request, str(e))
    return redirect(run.get_absolute_url())


@require_cap("manage_payroll")
def paycheck_edit(request, pk):
    paycheck = get_object_or_404(Paycheck.objects.select_related("run", "employee"), pk=pk)
    run = paycheck.run
    if run.status != PayrollRun.DRAFT:
        return redirect("payroll:paycheck_stub", pk=pk)
    form = PaycheckForm(request.POST or None, paycheck=paycheck)
    if request.method == "POST":
        if "delete" in request.POST:
            paycheck.delete()
            messages.success(request, "Paycheck removed from this run.")
            return redirect(run.get_absolute_url())
        if form.is_valid():
            try:
                with transaction.atomic():
                    if "recalculate" in request.POST:
                        hours = form.cleaned_data.get("hours")
                        services.build_paycheck(run, paycheck.employee, hours=hours)
                        paycheck.refresh_from_db()
                        if form.cleaned_data.get("check_number"):
                            paycheck.check_number = form.cleaned_data["check_number"]
                            paycheck.save()
                        messages.success(request, "Recalculated from the pay setup.")
                        return redirect("payroll:paycheck_edit", pk=pk)
                    services.save_paycheck_amounts(
                        paycheck, form.amounts(), hours=form.cleaned_data.get("hours"),
                        check_number=form.cleaned_data.get("check_number", ""),
                    )
            except LedgerError as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, f"Paycheck for {paycheck.employee} saved.")
                return redirect(run.get_absolute_url())
    return render(request, "payroll/paycheck_form.html", {"form": form, "paycheck": paycheck, "run": run})


@require_cap("view_payroll")
def paycheck_stub(request, pk):
    paycheck = get_object_or_404(Paycheck.objects.select_related("run", "employee"), pk=pk)
    lines = list(paycheck.lines.select_related("item"))
    year_start = date(paycheck.run.pay_date.year, 1, 1)
    ytd_lines = PaycheckLine.objects.filter(
        paycheck__employee=paycheck.employee, paycheck__run__status=PayrollRun.POSTED,
        paycheck__run__pay_date__gte=year_start, paycheck__run__pay_date__lte=paycheck.run.pay_date,
    ).select_related("item")
    ytd = defaultdict(lambda: ZERO)
    for l in ytd_lines:
        ytd[l.item_id] += l.amount
    sections = []
    for label, kind in [("Earnings", PayrollItem.EARNING), ("Deductions", PayrollItem.DEDUCTION), ("Employer contributions", PayrollItem.EMPLOYER)]:
        sections.append((label, [(l, ytd.get(l.item_id, ZERO)) for l in lines if l.item.kind == kind]))
    return render(request, "payroll/paycheck_stub.html", {"paycheck": paycheck, "sections": sections})


# ----------------------------------------------------------------- employees

@require_cap("view_payroll")
def employee_list(request):
    show_all = request.GET.get("all") == "1"
    employees = Employee.objects.select_related("fund", "wage_account")
    if not show_all:
        employees = employees.filter(is_active=True)
    return render(request, "payroll/employee_list.html", {"employees": employees, "show_all": show_all})


@require_cap("view_payroll")
def employee_detail(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    year = int(request.GET.get("year") or today().year)
    paychecks = employee.paychecks.filter(run__status=PayrollRun.POSTED, run__pay_date__year=year).select_related("run")
    totals = defaultdict(lambda: ZERO)
    for line in PaycheckLine.objects.filter(paycheck__in=paychecks).select_related("item"):
        totals[line.item] += line.amount
    ytd = sorted(totals.items(), key=lambda x: (x[0].sort_order, x[0].name))
    return render(request, "payroll/employee_detail.html", {
        "employee": employee, "paychecks": paychecks.order_by("-run__pay_date"), "ytd": ytd, "year": year,
        "years": range(today().year, today().year - 6, -1),
        "items": employee.payroll_items.select_related("item"),
        "gross": sum((p.gross for p in paychecks), ZERO), "net": sum((p.net for p in paychecks), ZERO),
        **document_context(employee, request.user),
    })


@require_cap("manage_payroll")
def employee_edit(request, pk=None):
    employee = get_object_or_404(Employee, pk=pk) if pk else None
    form = EmployeeForm(request.POST or None, instance=employee)
    initial = []
    if not employee:
        initial = [{"item": i.pk, "amount": i.default_amount} for i in PayrollItem.objects.filter(is_active=True).exclude(kind=PayrollItem.EARNING)]
    # Defaults are only used to pre-fill the blank form; once posted, every row counts as entered data.
    if request.method == "POST":
        formset = EmployeeItemFormSet(request.POST, instance=employee or Employee(), prefix="items")
    else:
        formset = EmployeeItemFormSet(instance=employee or Employee(), prefix="items", initial=initial or None)
        formset.extra = len(initial)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            employee = form.save()
            formset.instance = employee
            formset.save()
        messages.success(request, f"{employee} saved.")
        return redirect(employee.get_absolute_url())
    return render(request, "payroll/employee_form.html", {"form": form, "formset": formset, "employee": employee})


# --------------------------------------------------------------------- items

@require_cap("view_payroll")
def item_list(request):
    items = PayrollItem.objects.select_related("expense_account", "liability_account")
    return render(request, "payroll/item_list.html", {"items": items})


@require_cap("manage_payroll")
def item_edit(request, pk=None):
    item = get_object_or_404(PayrollItem, pk=pk) if pk else None
    form = PayrollItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Pay type saved.")
        return redirect("payroll:item_list")
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit {item}" if item else "New pay or deduction type",
        "subtitle": "Set rates to match your local tax and pension rules. Each person's rate can be overridden on their record.",
        "cancel_url": reverse("payroll:item_list"),
    })
