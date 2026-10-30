from datetime import timedelta

from django.db.models import Count
from django.shortcuts import render

from core.utils import (
    ZERO,
    MoneySum,
    fiscal_months,
    fiscal_year_label,
    fiscal_year_of,
    fiscal_year_range,
    today,
)

from .permissions import has_cap


def _giving_by_fiscal_month(year):
    from giving.models import Contribution, ContributionBatch

    totals = []
    for _, first, last in fiscal_months(year):
        if first > today():
            totals.append(None)
            continue
        amount = Contribution.objects.filter(
            batch__status=ContributionBatch.POSTED, date__gte=first, date__lte=last,
        ).aggregate(t=MoneySum("amount"))["t"]
        totals.append(float(amount or 0))
    return totals


def dashboard(request):
    from expenses.models import Expense
    from expenses.services import total_outstanding
    from giving.models import Contribution, ContributionBatch
    from ledger import services
    from ledger.models import Account, Budget, Fund, JournalEntry
    from reports.builders import dashboard_months

    user = request.user
    t = today()
    context = {"today": t}
    context["open_batches"] = (
        ContributionBatch.objects.filter(status=ContributionBatch.OPEN)
        .annotate(amount=MoneySum("contributions__amount"), gifts=Count("contributions"))
        .order_by("-date")[:8]
        if has_cap(user, "manage_giving") else []
    )
    if not has_cap(user, "view_finance"):
        return render(request, "core/dashboard_limited.html", context)

    fy = fiscal_year_of(t)
    fy_start, fy_end = fiscal_year_range(fy)
    month_start = t.replace(day=1)
    last_year_month_start = month_start.replace(year=month_start.year - 1)
    last_year_same_day = t.replace(year=t.year - 1) if not (t.month == 2 and t.day == 29) else t.replace(year=t.year - 1, day=28)

    posted = Contribution.objects.filter(batch__status=ContributionBatch.POSTED)
    giving_month = posted.filter(date__gte=month_start, date__lte=t).aggregate(s=MoneySum("amount"))["s"] or ZERO
    giving_month_ly = posted.filter(date__gte=last_year_month_start, date__lte=last_year_same_day).aggregate(s=MoneySum("amount"))["s"] or ZERO
    giving_fytd = posted.filter(date__gte=fy_start, date__lte=t).aggregate(s=MoneySum("amount"))["s"] or ZERO

    balances = services.account_balances(start=fy_start, end=t)
    accounts = {a.pk: a for a in Account.objects.all()}
    income = sum((v for k, v in balances.items() if accounts[k].type == Account.INCOME), ZERO)
    expense = sum((v for k, v in balances.items() if accounts[k].type == Account.EXPENSE), ZERO)

    cash = services.cash_balances(end=t)
    bank_rows = [(a, bal, services.last_reconciled(a)) for a, bal in cash]

    # Budget progress, year to date through the current month, for the funds that have a budget
    budget_income = budget_expense = annual_income = annual_expense = ZERO
    month_index = next((i for i, first, last in fiscal_months(fy) if first <= t <= last), 11)
    budgets = Budget.objects.filter(fiscal_year=fy).prefetch_related("lines__account")
    budget_funds = [b.fund for b in budgets]
    budget_actual = services.account_balances(start=fy_start, end=t, funds=budget_funds) if budget_funds else {}
    budget_actual_income = sum((v for k, v in budget_actual.items() if accounts[k].type == Account.INCOME), ZERO)
    budget_actual_expense = sum((v for k, v in budget_actual.items() if accounts[k].type == Account.EXPENSE), ZERO)
    for b in budgets:
        for line in b.lines.all():
            amounts = line.month_amounts
            ytd = sum(amounts[: month_index + 1], ZERO)
            if line.account.type == Account.INCOME:
                budget_income += ytd
                annual_income += sum(amounts, ZERO)
            else:
                budget_expense += ytd
                annual_expense += sum(amounts, ZERO)

    # Charts
    months = dashboard_months(12)
    chart_income, chart_expense = [], []
    for first, last in months:
        bal = services.account_balances(start=first, end=last)
        chart_income.append(float(sum((v for k, v in bal.items() if accounts[k].type == Account.INCOME), ZERO)))
        chart_expense.append(float(sum((v for k, v in bal.items() if accounts[k].type == Account.EXPENSE), ZERO)))

    fund_bal = services.fund_balances(end=t)
    funds = [(f, fund_bal.get(f.pk, ZERO)) for f in Fund.objects.filter(is_active=True)]

    due_soon = (
        Expense.objects.filter(status__in=Expense.OPEN_BALANCE, due_date__lte=t + timedelta(days=14))
        .select_related("vendor").order_by("due_date")[:8]
    )
    context.update({
        "fy_label": fiscal_year_label(fy),
        "cash_total": sum((b for _, b in cash), ZERO),
        "bank_rows": bank_rows,
        "giving_month": giving_month,
        "giving_month_ly": giving_month_ly,
        "giving_change": ((giving_month - giving_month_ly) / giving_month_ly * 100) if giving_month_ly else None,
        "giving_fytd": giving_fytd,
        "income": income, "expense": expense, "surplus": income - expense,
        "outstanding": total_outstanding(),
        "overdue": Expense.objects.filter(status__in=Expense.OPEN_BALANCE, due_date__lt=t).count(),
        "pending_approvals": Expense.objects.filter(status=Expense.PENDING).count(),
        "budget": {
            "income": budget_income, "expense": budget_expense, "annual_income": annual_income, "annual_expense": annual_expense,
            "actual_income": budget_actual_income, "actual_expense": budget_actual_expense,
            "funds": ", ".join(f.name for f in budget_funds),
            "income_pct": float(budget_actual_income / budget_income * 100) if budget_income else None,
            "expense_pct": float(budget_actual_expense / budget_expense * 100) if budget_expense else None,
        },
        "funds": funds,
        "due_soon": due_soon,
        "recent": JournalEntry.objects.filter(status=JournalEntry.POSTED).annotate(amount=MoneySum("lines__debit")).order_by("-date", "-id")[:8],
        "chart_months": {
            "labels": [f"{first:%b %Y}" for first, _ in months],
            "income": chart_income,
            "expense": chart_expense,
        },
        "chart_giving": {
            "labels": [f"{first:%b}" for _, first, _ in fiscal_months(fy)],
            "current": _giving_by_fiscal_month(fy),
            "previous": _giving_by_fiscal_month(fy - 1),
            "current_label": fiscal_year_label(fy),
            "previous_label": fiscal_year_label(fy - 1),
        },
    })
    return render(request, "core/dashboard.html", context)
