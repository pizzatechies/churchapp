from django.shortcuts import render

from core.permissions import require_cap
from core.utils import (
    PERIOD_CHOICES, fiscal_months, fiscal_year_choices, fiscal_year_of, period_from_request, parse_date, to_decimal, today,
)
from ledger.models import Account, Fund

from . import builders

REPORT_GROUPS = [
    ("Financial statements", "bi-file-earmark-text", [
        ("reports:balance_sheet", "Statement of financial position", "Balance sheet: what the church owns and owes, and net assets by fund."),
        ("reports:activities", "Statement of activities", "Income statement: revenue, expenses and the change in net assets."),
        ("reports:functional_expenses", "Statement of functional expenses", "Expenses split between ministry programs, administration and fundraising."),
        ("reports:fund_activity", "Fund activity", "Beginning balance, income, spending, transfers and ending balance of every fund."),
        ("reports:cash_summary", "Cash receipts & disbursements", "Money in and out of the bank each month."),
    ]),
    ("Budgets & trends", "bi-graph-up", [
        ("reports:budget_vs_actual", "Budget vs. actual", "Year-to-date results against the approved budget, with variances."),
        ("reports:monthly_trend", "Income & expenses by month", "Twelve-month view of every income and expense account."),
    ]),
    ("Giving", "bi-heart", [
        ("reports:giving_summary", "Giving summary", "Totals by fund, category, method and month."),
        ("reports:donor_giving", "Giving by donor", "Each donor's giving compared with last year (confidential)."),
        ("reports:lapsed_donors", "Lapsed donors", "People who gave last year but not this year (confidential)."),
        ("giving:statements", "Contribution statements", "Year-end giving statements for donors' tax records."),
    ]),
    ("Spending & payables", "bi-receipt", [
        ("reports:ap_aging", "Unpaid bills (aging)", "What the church owes and how overdue it is."),
        ("reports:payments_by_payee", "Payments by payee", "Cash paid to each vendor or person."),
        ("reports:tax_form_payees", "Year-end tax form payees", "Contractors who may need a 1099 or similar tax form."),
    ]),
    ("Payroll", "bi-people", [
        ("reports:payroll_summary", "Payroll summary", "Annual pay, deductions and employer costs per person (confidential)."),
        ("reports:payroll_liabilities", "Payroll liabilities", "Withholdings and employer taxes not yet paid over."),
    ]),
    ("Accounting", "bi-journal-check", [
        ("reports:trial_balance", "Trial balance", "Debit and credit balance of every account — for your accountant or auditor."),
        ("reports:general_ledger", "General ledger detail", "Every transaction by account with running balances."),
    ]),
]

REPORT_CAPS = {
    "reports:donor_giving": "view_donors", "reports:lapsed_donors": "view_donors", "giving:statements": "view_donors",
    "reports:payroll_summary": "view_payroll",
}


@require_cap("view_finance")
def index(request):
    from core.permissions import has_cap

    groups = []
    for title, icon, reports in REPORT_GROUPS:
        visible = [r for r in reports if r[0] not in REPORT_CAPS or has_cap(request.user, REPORT_CAPS[r[0]])]
        if visible:
            groups.append((title, icon, visible))
    return render(request, "reports/index.html", {"groups": groups})


# ------------------------------------------------------------- filter helpers

def f_period(request, default="fytd"):
    start, end, period = period_from_request(request, default)
    controls = [
        {"name": "period", "label": "Period", "type": "period", "value": period,
         "options": PERIOD_CHOICES + ([("custom", "Custom dates")] if period == "custom" else [])},
        {"name": "start", "label": "From", "type": "date", "value": start},
        {"name": "end", "label": "To", "type": "date", "value": end},
    ]
    return start, end, controls


def f_as_of(request):
    as_of = parse_date(request.GET.get("end")) or today()
    return as_of, [{"name": "end", "label": "As of", "type": "date", "value": as_of}]


def f_select(request, name, label, options, default=""):
    value = request.GET.get(name, default)
    return value, {"name": name, "label": label, "type": "select", "value": str(value), "options": [(str(k), v) for k, v in options]}


def f_year(request):
    year = int(request.GET.get("year") or fiscal_year_of(today()))
    return year, {"name": "year", "label": "Fiscal year", "type": "select", "value": str(year),
                  "options": [(str(k), v) for k, v in fiscal_year_choices()]}


def f_fund(request, all_label="All funds"):
    fund = Fund.objects.filter(pk=request.GET.get("fund")).first() if request.GET.get("fund") else None
    return fund, {"name": "fund", "label": "Fund", "type": "select", "value": str(fund.pk) if fund else "",
                  "options": [("", all_label)] + [(str(f.pk), f.name) for f in Fund.objects.all()]}


COLUMN_MODES = [("total", "Total only"), ("restriction", "By restriction"), ("fund", "By fund")]


def render_report(request, report, controls, slug):
    if request.GET.get("export") == "csv":
        return report.to_csv(f"{slug}.csv")
    return render(request, "reports/report.html", {"report": report, "controls": controls})


# ------------------------------------------------------------------- reports

@require_cap("view_finance")
def balance_sheet(request):
    as_of, controls = f_as_of(request)
    mode, c = f_select(request, "columns", "Columns", COLUMN_MODES, "restriction")
    return render_report(request, builders.balance_sheet(as_of, mode), controls + [c], "statement-of-financial-position")


@require_cap("view_finance")
def activities(request):
    start, end, controls = f_period(request)
    mode, c = f_select(request, "columns", "Columns", COLUMN_MODES + [("compare", "Compare to prior year")], "total")
    report = builders.activities(start, end, mode="total" if mode == "compare" else mode, compare=mode == "compare")
    return render_report(request, report, controls + [c], "statement-of-activities")


@require_cap("view_finance")
def budget_vs_actual(request):
    year, cy = f_year(request)
    if "fund" not in request.GET:
        # Default to the general fund (budgets are per fund); "All funds" is still one click away.
        request.GET = request.GET.copy()
        request.GET["fund"] = str(Fund.default().pk) if Fund.default() else ""
    fund, cf = f_fund(request)
    through = request.GET.get("through")
    report, idx = builders.budget_vs_actual(year, fund, int(through) if through not in (None, "") else None)
    months = [(str(i), f"{last:%B %Y}") for i, first, last in fiscal_months(year)]
    ct = {"name": "through", "label": "Through", "type": "select", "value": str(idx), "options": months}
    return render_report(request, report, [cy, cf, ct], "budget-vs-actual")


@require_cap("view_finance")
def trial_balance(request):
    as_of, controls = f_as_of(request)
    return render_report(request, builders.trial_balance(as_of), controls, "trial-balance")


@require_cap("view_finance")
def general_ledger(request):
    start, end, controls = f_period(request, "month")
    account = Account.objects.filter(pk=request.GET.get("account")).first() if request.GET.get("account") else None
    fund, cf = f_fund(request)
    ca = {"name": "account", "label": "Account", "type": "select", "value": str(account.pk) if account else "",
          "options": [("", "All accounts")] + [(str(a.pk), str(a)) for a in Account.objects.all()]}
    return render_report(request, builders.general_ledger(start, end, account, fund), controls + [ca, cf], "general-ledger")


@require_cap("view_finance")
def fund_activity(request):
    start, end, controls = f_period(request)
    return render_report(request, builders.fund_activity(start, end), controls, "fund-activity")


@require_cap("view_finance")
def functional_expenses(request):
    start, end, controls = f_period(request)
    return render_report(request, builders.functional_expenses(start, end), controls, "functional-expenses")


@require_cap("view_finance")
def monthly_trend(request):
    year, cy = f_year(request)
    fund, cf = f_fund(request)
    return render_report(request, builders.monthly_trend(year, fund), [cy, cf], "income-expense-by-month")


@require_cap("view_finance")
def cash_summary(request):
    year, cy = f_year(request)
    return render_report(request, builders.cash_summary(year), [cy], "cash-summary")


@require_cap("view_finance")
def giving_summary(request):
    start, end, controls = f_period(request)
    return render_report(request, builders.giving_summary(start, end), controls, "giving-summary")


@require_cap("view_donors")
def donor_giving(request):
    start, end, controls = f_period(request)
    minimum = to_decimal(request.GET.get("minimum"), None)
    controls.append({"name": "minimum", "label": "Minimum given", "type": "number", "value": request.GET.get("minimum", "")})
    return render_report(request, builders.donor_giving(start, end, minimum=minimum), controls, "giving-by-donor")


@require_cap("view_donors")
def lapsed_donors(request):
    start, end, controls = f_period(request)
    return render_report(request, builders.donor_giving(start, end, lapsed_only=True), controls, "lapsed-donors")


@require_cap("view_finance")
def ap_aging(request):
    as_of, controls = f_as_of(request)
    return render_report(request, builders.ap_aging(as_of), controls, "accounts-payable-aging")


@require_cap("view_finance")
def payments_by_payee(request):
    start, end, controls = f_period(request)
    return render_report(request, builders.payments_by_payee(start, end), controls, "payments-by-payee")


@require_cap("view_finance")
def tax_form_payees(request):
    start, end, controls = f_period(request, "last_year" if today().month <= 3 else "ytd")
    return render_report(request, builders.payments_by_payee(start, end, tax_forms_only=True), controls, "tax-form-payees")


@require_cap("view_payroll")
def payroll_summary(request):
    year = int(request.GET.get("year") or today().year)
    cy = {"name": "year", "label": "Calendar year", "type": "select", "value": str(year),
          "options": [(str(y), str(y)) for y in range(today().year, today().year - 7, -1)]}
    return render_report(request, builders.payroll_summary(year), [cy], "payroll-summary")


@require_cap("view_finance")
def payroll_liabilities(request):
    as_of, controls = f_as_of(request)
    return render_report(request, builders.payroll_liabilities(as_of), controls, "payroll-liabilities")
