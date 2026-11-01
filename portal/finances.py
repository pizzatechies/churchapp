"""
What the members app shows about money.

Church settings switch on two things separately:

* **My giving**: a member sees their own gifts, pledges and yearly statements.
  Nothing about anyone else.
* **Church finances**: a summary for financial accountability. Totals only: income
  by category, spending by area, fund balances, budget and campaign progress, and
  the controls that protect the money. It never shows who gave what, and every
  staff cost is folded into one "Staff & personnel" figure, so nobody's pay can be
  worked out from it.

Everything comes from posted journal lines and posted offering batches, the same
figures the finance team's reports use, up to a cut-off date the church chooses.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count
from django.db.models.functions import TruncMonth

from core.models import ChurchProfile
from core.utils import ZERO, MoneySum, fiscal_months, fiscal_year_label, fiscal_year_of, fiscal_year_range, today
from giving.models import Campaign, Contribution, ContributionBatch
from ledger import services
from ledger.models import Account, Budget, Fund, Reconciliation

HUNDRED = Decimal(100)

# Spending areas as members see them. Personnel is deliberately one line.
AREA_LABELS = {
    "personnel": "Staff & personnel",
    "facilities": "Buildings & facilities",
    "ministry": "Ministries & programmes",
    "missions": "Missions, outreach & benevolence",
    "administration": "Administration",
    "other_expense": "Other spending",
}
AREA_ORDER = list(AREA_LABELS)


def _pct(part, whole):
    if not whole:
        return None
    return float((part / whole * HUNDRED).quantize(Decimal("0.1")))


def giving_enabled(profile=None):
    profile = profile or ChurchProfile.cached()
    return profile.members_see_own_giving or profile.members_see_finances


def cutoff_date(profile=None):
    """Last day included in the church summary, or None if nothing may be shown yet."""
    profile = profile or ChurchProfile.get()
    t = today()
    if profile.member_finance_period == ChurchProfile.MEMBER_FINANCE_LIVE:
        return t
    if profile.member_finance_period == ChurchProfile.MEMBER_FINANCE_CLOSED:
        return min(profile.lock_date, t) if profile.lock_date else None
    return t.replace(day=1) - timedelta(days=1)


def _same_day_last_year(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28)


def _income_expense(start, end):
    totals = services.totals_by(
        "account__type", start=start, end=end,
        extra_filter={"account__type__in": [Account.INCOME, Account.EXPENSE]},
    )
    dr, cr = totals.get(Account.INCOME, (ZERO, ZERO))
    income = cr - dr
    dr, cr = totals.get(Account.EXPENSE, (ZERO, ZERO))
    return income, dr - cr


def _monthly(start, end):
    """[{label, income, expense}] for each fiscal month from start to end."""
    rows = (
        services.posted_lines(start=start, end=end)
        .filter(account__type__in=[Account.INCOME, Account.EXPENSE])
        .annotate(month=TruncMonth("entry__date"))
        .values("month", "account__type")
        .annotate(dr=MoneySum("debit"), cr=MoneySum("credit"))
    )
    by_month = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
    for r in rows:
        m = r["month"].date() if hasattr(r["month"], "date") else r["month"]
        dr, cr = r["dr"] or ZERO, r["cr"] or ZERO
        if r["account__type"] == Account.INCOME:
            by_month[m]["income"] += cr - dr
        else:
            by_month[m]["expense"] += dr - cr
    months = []
    for _, first, _last in fiscal_months(fiscal_year_of(start)):
        if first > end:
            break
        v = by_month.get(first, {"income": ZERO, "expense": ZERO})
        months.append({"label": f"{first:%b %Y}", "short": f"{first:%b}", "income": v["income"], "expense": v["expense"]})
    return months


def _budget(fy, cutoff, accounts):
    """Approved budgets only, year to date through the cut-off month."""
    budgets = list(Budget.objects.filter(fiscal_year=fy, status=Budget.APPROVED).select_related("fund").prefetch_related("lines__account"))
    if not budgets:
        return None
    start, _ = fiscal_year_range(fy)
    month_index = next((i for i, first, last in fiscal_months(fy) if first <= cutoff <= last), 11)
    plan = {"income": ZERO, "expense": ZERO, "annual_income": ZERO, "annual_expense": ZERO}
    for b in budgets:
        for line in b.lines.all():
            amounts = line.month_amounts
            key = "income" if line.account.type == Account.INCOME else "expense"
            plan[key] += sum(amounts[: month_index + 1], ZERO)
            plan["annual_" + key] += sum(amounts, ZERO)
    actual = services.account_balances(start=start, end=cutoff, funds=[b.fund for b in budgets])
    actual_income = sum((v for k, v in actual.items() if accounts[k].type == Account.INCOME), ZERO)
    actual_expense = sum((v for k, v in actual.items() if accounts[k].type == Account.EXPENSE), ZERO)
    return {
        "funds": ", ".join(b.fund.name for b in budgets),
        "income": plan["income"], "expense": plan["expense"],
        "annual_income": plan["annual_income"], "annual_expense": plan["annual_expense"],
        "actual_income": actual_income, "actual_expense": actual_expense,
        "income_pct": _pct(actual_income, plan["income"]),
        "expense_pct": _pct(actual_expense, plan["expense"]),
    }


def _campaigns(cutoff):
    result = []
    for c in Campaign.objects.filter(is_active=True, start_date__lte=cutoff).select_related("fund"):
        received = c.contributions().filter(date__lte=cutoff).aggregate(t=MoneySum("amount"))["t"] or ZERO
        pledges = c.pledges.aggregate(t=MoneySum("amount"), n=Count("id"))
        result.append({
            "name": c.name, "description": c.description, "fund": c.fund.name, "goal": c.goal,
            "received": received, "pledged": pledges["t"] or ZERO, "pledgers": pledges["n"],
            "percent": min(100.0, _pct(received, c.goal)) if c.goal else None,
            "end_date": c.end_date,
        })
    return result


def _safeguards(profile):
    """How the money is protected: dates and rules only, no amounts."""
    reconciled = []
    for a in Account.objects.filter(subtype="bank", is_active=True).order_by("number"):
        last = a.reconciliations.filter(status=Reconciliation.COMPLETED).order_by("-statement_date").first()
        if last:
            reconciled.append((a.name, last.statement_date))
    approved_budget = Budget.objects.filter(status=Budget.APPROVED, approved_at__isnull=False).order_by("-approved_at").first()
    return {
        "approval_threshold": profile.expense_approval_threshold,
        "separate_approver": profile.require_separate_approver,
        "lock_date": profile.lock_date,
        # Bank accounts and the date each was last reconciled to a bank statement (no balances).
        "reconciled": reconciled,
        "budget_approved": approved_budget,
        "treasurer": profile.treasurer_name,
    }


def church_summary(cutoff, profile=None):
    profile = profile or ChurchProfile.get()
    fy = fiscal_year_of(cutoff)
    start, fy_end = fiscal_year_range(fy)
    accounts = {a.pk: a for a in Account.objects.all()}
    balances = services.account_balances(start=start, end=cutoff)

    income_rows, areas = [], defaultdict(lambda: {"total": ZERO, "items": []})
    for account_id, amount in balances.items():
        a = accounts[account_id]
        if not amount:
            continue
        if a.type == Account.INCOME:
            income_rows.append({"name": a.name, "amount": amount})
        elif a.type == Account.EXPENSE:
            area = a.subtype if a.subtype in AREA_LABELS else "other_expense"
            areas[area]["total"] += amount
            if area != "personnel":
                areas[area]["items"].append({"name": a.name, "amount": amount})
    income = sum((r["amount"] for r in income_rows), ZERO)
    expense = sum((v["total"] for v in areas.values()), ZERO)
    income_rows.sort(key=lambda r: -r["amount"])
    for r in income_rows:
        r["share"] = _pct(r["amount"], income)
    spending = []
    for code in AREA_ORDER:
        if code in areas and areas[code]["total"]:
            v = areas[code]
            v["items"].sort(key=lambda r: -r["amount"])
            spending.append({"code": code, "label": AREA_LABELS[code], "total": v["total"], "share": _pct(v["total"], expense), "items": v["items"]})

    ly_income, ly_expense = _income_expense(_same_day_last_year(start), _same_day_last_year(cutoff))

    fund_bal = services.fund_balances(end=cutoff)
    funds = [
        {"name": f.name, "description": f.description, "restricted": f.has_donor_restrictions,
         "restriction": f.get_restriction_display(), "balance": fund_bal.get(f.pk, ZERO)}
        for f in Fund.objects.filter(is_active=True)
    ]

    months = _monthly(start, cutoff)
    return {
        "cutoff": cutoff, "start": start, "fy_label": fiscal_year_label(fy), "fy_end": fy_end,
        "income": income, "expense": expense, "net": income - expense,
        "ly_income": ly_income, "ly_expense": ly_expense,
        "income_change": _pct(income - ly_income, ly_income),
        "expense_change": _pct(expense - ly_expense, ly_expense),
        "income_rows": income_rows, "spending": spending,
        "months": months,
        "chart": {
            "labels": [m["short"] for m in months],
            "income": [float(m["income"]) for m in months],
            "expense": [float(m["expense"]) for m in months],
        },
        "funds": funds,
        "funds_total": sum((f["balance"] for f in funds), ZERO),
        "budget": _budget(fy, cutoff, accounts),
        "campaigns": _campaigns(cutoff),
        "safeguards": _safeguards(profile),
    }


# ------------------------------------------------------------------ my giving

def _posted(donor):
    return Contribution.objects.filter(donor=donor, batch__status=ContributionBatch.POSTED)


def giving_years(donor):
    years = {d.year for d in _posted(donor).dates("date", "year")}
    years.add(today().year)
    return sorted(years, reverse=True)


def member_giving(member, year):
    """The member's own giving for a calendar year, or None if they aren't linked to a giving record."""
    donor = member.donor
    if donor is None:
        return None
    start, end = date(year, 1, 1), date(year, 12, 31)
    gifts = list(_posted(donor).filter(date__gte=start, date__lte=end).select_related("fund").order_by("-date", "-id"))
    total = sum((g.amount for g in gifts), ZERO)
    by_fund = defaultdict(lambda: ZERO)
    by_month = [ZERO] * 12
    for g in gifts:
        by_fund[g.fund.name] += g.amount
        by_month[g.date.month - 1] += g.amount
    last_year = _posted(donor).filter(date__gte=date(year - 1, 1, 1), date__lte=date(year - 1, 12, 31)).aggregate(t=MoneySum("amount"))["t"] or ZERO
    pledges = []
    for p in donor.pledges.select_related("campaign", "campaign__fund").order_by("-pledge_date"):
        pledges.append({
            "campaign": p.campaign.name, "fund": p.campaign.fund.name, "amount": p.amount,
            "fulfilled": p.fulfilled, "remaining": p.remaining, "percent": float(p.percent),
            "frequency": p.get_frequency_display(), "active": p.campaign.is_active,
        })
    current_month = today().month if year == today().year else 12
    return {
        "donor": donor, "year": year, "gifts": gifts, "total": total, "count": len(gifts),
        "last_year": last_year,
        "by_fund": sorted(by_fund.items(), key=lambda kv: -kv[1]),
        "chart": {
            "labels": [date(year, m, 1).strftime("%b") for m in range(1, 13)][:current_month],
            "amounts": [float(v) for v in by_month][:current_month],
        },
        "pledges": pledges,
        "years": giving_years(donor),
    }
