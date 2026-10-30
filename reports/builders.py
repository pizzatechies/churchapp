"""
Financial report calculations. Each function returns a `Report` built purely
from posted journal lines (or, for giving/payables/payroll detail, from the
sub-ledgers), so every figure ties back to the general ledger.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Min
from django.urls import reverse

from core.utils import (
    ZERO,
    MoneySum,
    add_months,
    fiscal_months,
    fiscal_year_label,
    fiscal_year_of,
    fiscal_year_range,
    month_end,
    today,
)
from expenses.models import Expense, ExpensePayment
from giving.models import Contribution, ContributionBatch
from ledger import services
from ledger.models import Account, Budget, Fund, JournalEntry, JournalLine
from payroll.models import PaycheckLine, PayrollItem, PayrollRun

from .base import Column, Report

HUNDRED = Decimal(100)


def _pct(part, whole):
    if not whole:
        return None
    return (part / whole * HUNDRED).quantize(Decimal("0.1"))


def _register_url(account, start, end, fund_ids=None):
    url = reverse("ledger:account_detail", args=[account.pk]) + f"?start={start:%Y-%m-%d}&end={end:%Y-%m-%d}"
    if fund_ids and len(fund_ids) == 1:
        url += f"&fund={next(iter(fund_ids))}"
    return url


def column_sets(mode):
    """[(label, set of fund ids or None for all)] for statement columns."""
    funds = list(Fund.objects.all())
    if mode == "fund":
        return [(f.name, {f.pk}) for f in funds] + [("Total", None)]
    if mode == "restriction":
        return [
            ("Without donor restrictions", {f.pk for f in funds if not f.has_donor_restrictions}),
            ("With donor restrictions", {f.pk for f in funds if f.has_donor_restrictions}),
            ("Total", None),
        ]
    return [("Total", None)]


def _sum_for(balances_by_fund, fundset):
    return sum((v for f, v in balances_by_fund.items() if fundset is None or f in fundset), ZERO)


def _by_account(afb):
    """{(account, fund): v} -> {account: {fund: v}}"""
    result = defaultdict(dict)
    for (a, f), v in afb.items():
        result[a][f] = v
    return result


GROUP_LABELS = {
    "bank": "Cash in bank", "cash": "Cash on hand", "receivable": "Receivables", "other_current_asset": "Other current assets",
    "investment": "Investments", "fixed_asset": "Property & equipment", "accumulated_depreciation": "Accumulated depreciation",
    "other_asset": "Other assets", "payable": "Accounts payable", "credit_card": "Credit cards",
    "payroll_liability": "Payroll liabilities", "other_current_liability": "Other current liabilities",
    "long_term_liability": "Long-term debt", "contributions": "Contributions", "program_income": "Program & ministry income",
    "other_income": "Other income", "personnel": "Personnel", "facilities": "Facilities", "ministry": "Ministries & programs",
    "missions": "Missions & benevolence", "administration": "Administration", "other_expense": "Other expenses",
}


def _subtype_groups(type_, accounts):
    order = [code for code, _ in Account.SUBTYPES[type_]]
    groups = defaultdict(list)
    for a in accounts:
        groups[a.subtype].append(a)
    return [(GROUP_LABELS.get(s, Account.SUBTYPE_LABELS[s]), groups[s]) for s in order if groups.get(s)]


# ---------------------------------------------------------------- statements

def balance_sheet(as_of, mode="total"):
    cols = column_sets(mode)
    report = Report(
        "Statement of Financial Position",
        f"As of {as_of:%B %d, %Y}",
        [Column("")] + [Column(label) for label, _ in cols],
        wide=len(cols) > 4,
    )
    by_acct = _by_account(services.account_fund_balances(end=as_of))
    fund_bal = services.fund_balances(end=as_of)
    fy_start = fiscal_year_range(fiscal_year_of(as_of))[0]
    totals = {}
    for type_, title in [(Account.ASSET, "Assets"), (Account.LIABILITY, "Liabilities")]:
        report.section(title)
        accounts = [a for a in Account.objects.filter(type=type_) if any(by_acct.get(a.pk, {}).values())]
        type_total = [ZERO] * len(cols)
        for label, group in _subtype_groups(type_, accounts):
            group_total = [ZERO] * len(cols)
            rows = []
            for a in group:
                values = [_sum_for(by_acct.get(a.pk, {}), fs) for _, fs in cols]
                rows.append((a, values))
                group_total = [x + y for x, y in zip(group_total, values)]
            if len(rows) > 1:
                report.group(label, level=1)
                for a, values in rows:
                    report.add([a.name] + values, level=2, url=_register_url(a, fy_start, as_of))
                report.add([f"Total {label.lower()}"] + group_total, kind="subtotal", level=1)
            else:
                a, values = rows[0]
                report.add([a.name] + values, level=1, url=_register_url(a, fy_start, as_of))
            type_total = [x + y for x, y in zip(type_total, group_total)]
        report.add([f"Total {title.lower()}"] + type_total, kind="total")
        totals[type_] = type_total
        report.spacer()

    report.section("Net assets")
    funds = list(Fund.objects.all())
    na_total = [ZERO] * len(cols)
    for label, members in [
        ("Without donor restrictions", [f for f in funds if not f.has_donor_restrictions]),
        ("With donor restrictions", [f for f in funds if f.has_donor_restrictions]),
    ]:
        members = [f for f in members if fund_bal.get(f.pk)]
        if not members:
            continue
        report.group(label, level=1)
        for f in members:
            values = [fund_bal.get(f.pk, ZERO) if fs is None or f.pk in fs else ZERO for _, fs in cols]
            report.add([f.name] + values, level=2, url=reverse("ledger:fund_detail", args=[f.pk]))
            na_total = [x + y for x, y in zip(na_total, values)]
    report.add(["Total net assets"] + na_total, kind="total")
    report.spacer()
    liab_na = [x + y for x, y in zip(totals[Account.LIABILITY], na_total)]
    report.add(["Total liabilities and net assets"] + liab_na, kind="grand")
    if any(a != b for a, b in zip(totals[Account.ASSET], liab_na)):
        report.warnings.append("Assets do not equal liabilities plus net assets. Please contact your administrator.")
    return report


def activities(start, end, mode="total", compare=False):
    if compare:
        prior_start, prior_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
        periods = [("This period", None, start, end), ("Prior year", None, prior_start, prior_end)]
    else:
        periods = [(label, fs, start, end) for label, fs in column_sets(mode)]
    labels = [p[0] for p in periods] + (["Change"] if compare else [])
    report = Report(
        "Statement of Activities",
        f"{start:%B %d, %Y} – {end:%B %d, %Y}" + (f" compared with {periods[1][2]:%b %d, %Y} – {periods[1][3]:%b %d, %Y}" if compare else ""),
        [Column("")] + [Column(l) for l in labels],
        wide=len(labels) > 4,
    )
    data = [_by_account(services.account_fund_balances(start=s, end=e)) for _, _, s, e in periods]

    def values_for(account_id):
        vals = [_sum_for(d.get(account_id, {}), fs) for d, (_, fs, _, _) in zip(data, periods)]
        if compare:
            vals.append(vals[0] - vals[1])
        return vals

    n = len(labels)
    section_totals = {}
    for type_, title in [(Account.INCOME, "Revenue and support"), (Account.EXPENSE, "Expenses")]:
        report.section(title)
        accounts = [a for a in Account.objects.filter(type=type_) if any(values_for(a.pk))]
        total = [ZERO] * n
        for label, group in _subtype_groups(type_, accounts):
            report.group(label, level=1)
            group_total = [ZERO] * n
            for a in group:
                vals = values_for(a.pk)
                report.add([a.name] + vals, level=2, url=_register_url(a, start, end))
                group_total = [x + y for x, y in zip(group_total, vals)]
            report.add([f"Total {label.lower()}"] + group_total, kind="subtotal", level=1)
            total = [x + y for x, y in zip(total, group_total)]
        if not accounts:
            report.add(["None"] + [None] * n, kind="note", level=1)
        report.add([f"Total {title.split()[0].lower()}"] + total, kind="total")
        section_totals[type_] = total
        report.spacer()

    change = [i - e for i, e in zip(section_totals[Account.INCOME], section_totals[Account.EXPENSE])]
    report.add(["Change in net assets from operations"] + change, kind="subtotal")
    equity_ids = list(Account.objects.filter(type=Account.EQUITY).values_list("pk", flat=True))
    other = [ZERO] * len(periods)
    for i, (d, (_, fs, _, _)) in enumerate(zip(data, periods)):
        other[i] = sum((_sum_for(d.get(a, {}), fs) for a in equity_ids), ZERO)
    if compare:
        other.append(other[0] - other[1])
    if any(other):
        report.add(["Transfers between funds and other changes"] + other, level=1)
    total_change = [x + y for x, y in zip(change, other)]
    report.add(["Change in net assets"] + total_change, kind="total")
    beginning = []
    for _, fs, s, _ in periods:
        beginning.append(_sum_for(services.fund_balances(end=s - timedelta(days=1)), fs))
    if compare:
        beginning.append(beginning[0] - beginning[1])
    report.add(["Net assets, beginning of period"] + beginning, level=1)
    report.add(["Net assets, end of period"] + [b + c for b, c in zip(beginning, total_change)], kind="grand")
    return report


def budget_vs_actual(year, fund=None, through_index=None):
    months = fiscal_months(year)
    fy_start, fy_end = fiscal_year_range(year)
    if through_index is None:
        t = today()
        through_index = 11 if t > fy_end else max(0, next((i for i, f, l in months if f <= t <= l), 11))
    through = months[through_index][2]
    budgets = Budget.objects.filter(fiscal_year=year)
    if fund:
        budgets = budgets.filter(fund=fund)
    budget_ytd, budget_annual = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for b in budgets.prefetch_related("lines"):
        for line in b.lines.all():
            amounts = line.month_amounts
            budget_ytd[line.account_id] += sum(amounts[: through_index + 1], ZERO)
            budget_annual[line.account_id] += sum(amounts, ZERO)
    actual = services.account_balances(start=fy_start, end=through, funds=[fund] if fund else None)
    scope = fund.name if fund else "All funds"
    report = Report(
        "Budget vs. Actual",
        f"{scope} · {fiscal_year_label(year)} · year to date through {through:%B %d, %Y}",
        [Column(""), Column("Actual YTD"), Column("Budget YTD"), Column("Variance"), Column("% of YTD budget", "percent"),
         Column("Annual budget"), Column("Remaining")],
    )
    if not budgets.exists():
        report.warnings.append("No budget has been entered for this fiscal year" + (f" and fund ({fund})." if fund else "."))
    sums = {}
    for type_, title in [(Account.INCOME, "Income"), (Account.EXPENSE, "Expenses")]:
        report.section(title)
        accounts = [a for a in Account.objects.filter(type=type_) if actual.get(a.pk) or budget_annual.get(a.pk)]
        t = [ZERO] * 4
        for a in accounts:
            act, bud, ann = actual.get(a.pk, ZERO), budget_ytd[a.pk], budget_annual[a.pk]
            var = act - bud if type_ == Account.INCOME else bud - act
            report.add([a.name, act, bud, var, _pct(act, bud), ann, ann - act], level=1, url=_register_url(a, fy_start, through))
            t = [t[0] + act, t[1] + bud, t[2] + var, t[3] + ann]
        report.add([f"Total {title.lower()}", t[0], t[1], t[2], _pct(t[0], t[1]), t[3], t[3] - t[0]], kind="total")
        sums[type_] = t
        report.spacer()
    inc, exp = sums[Account.INCOME], sums[Account.EXPENSE]
    report.add(["Net surplus / (deficit)", inc[0] - exp[0], inc[1] - exp[1], (inc[0] - exp[0]) - (inc[1] - exp[1]), None,
                inc[3] - exp[3], None], kind="grand")
    report.notes.append("Variance is positive when results are better than budget (more income or less spending).")
    return report, through_index


def trial_balance(as_of):
    fy_start = fiscal_year_range(fiscal_year_of(as_of))[0]
    report = Report("Trial Balance", f"As of {as_of:%B %d, %Y} (income and expenses for {fiscal_year_label(fiscal_year_of(as_of))} to date)",
                    [Column("Account"), Column("Debit"), Column("Credit")])
    bs = services.totals_by("account_id", end=as_of, extra_filter={"account__type__in": [Account.ASSET, Account.LIABILITY, Account.EQUITY]})
    pl = services.totals_by("account_id", start=fy_start, end=as_of, extra_filter={"account__type__in": [Account.INCOME, Account.EXPENSE]})
    totals = [ZERO, ZERO]
    for a in Account.objects.all():
        dr, cr = bs.get(a.pk) or pl.get(a.pk) or (ZERO, ZERO)
        net = dr - cr
        if not net:
            continue
        row = [str(a), net if net > 0 else None, -net if net < 0 else None]
        report.add(row, url=_register_url(a, fy_start, as_of))
        totals[0] += max(net, ZERO)
        totals[1] += max(-net, ZERO)
    prior = services.surplus(end=fy_start - timedelta(days=1))
    if prior:
        report.add(["Net assets — surplus from prior years", None if prior > 0 else -prior, prior if prior > 0 else None])
        totals[0] += max(-prior, ZERO)
        totals[1] += max(prior, ZERO)
    report.add(["Total"] + totals, kind="grand")
    if totals[0] != totals[1]:
        report.warnings.append("Debits and credits are not equal. Please contact your administrator.")
    report.notes.append("Income and expenses from prior fiscal years are shown as one accumulated surplus line, as if the books had been closed.")
    return report


def general_ledger(start, end, account=None, fund=None):
    title = "General Ledger" + (f" — {account}" if account else "")
    report = Report(title, f"{start:%B %d, %Y} – {end:%B %d, %Y}" + (f" · {fund}" if fund else ""),
                    [Column("Date", "date"), Column("Entry", "text"), Column("Description", "text"), Column("Fund", "text"),
                     Column("Debit"), Column("Credit"), Column("Balance")], wide=True)
    lines = (JournalLine.objects.filter(entry__status=JournalEntry.POSTED, entry__date__gte=start, entry__date__lte=end)
             .select_related("entry", "fund", "account").order_by("account__number", "entry__date", "entry_id", "id"))
    if account:
        lines = lines.filter(account=account)
    if fund:
        lines = lines.filter(fund=fund)
    current = None
    running = ZERO
    totals = [ZERO, ZERO]

    def close(acct):
        report.add([f"Total {acct.number} · {acct.name}", None, None, None, totals[0], totals[1], running], kind="subtotal")
        report.spacer()

    for line in lines:
        if line.account_id != (current.pk if current else None):
            if current:
                close(current)
            current = line.account
            opening = current.balance(end=start - timedelta(days=1), fund=fund) if current.is_balance_sheet else ZERO
            running = opening
            totals = [ZERO, ZERO]
            report.group(f"{current.number} · {current.name}")
            report.add([start, "", "Opening balance", "", None, None, opening], kind="note", level=1)
        running += current.signed(line.debit, line.credit)
        totals[0] += line.debit
        totals[1] += line.credit
        report.add([line.entry.date, line.entry.number, line.description or line.entry.memo, line.fund.code,
                    line.debit or None, line.credit or None, running], level=1, url=line.entry.get_absolute_url())
    if current:
        close(current)
    if not report.rows:
        report.add(["", "", "No posted transactions in this period.", "", None, None, None], kind="note")
    return report


def fund_activity(start, end):
    report = Report("Fund Activity", f"{start:%B %d, %Y} – {end:%B %d, %Y}",
                    [Column("Fund"), Column("Beginning balance"), Column("Income"), Column("Expenses"),
                     Column("Transfers & other"), Column("Ending balance")])
    begin = services.fund_balances(end=start - timedelta(days=1))
    ending = services.fund_balances(end=end)
    activity = services.totals_by("fund_id", "account__type", start=start, end=end)
    totals = [ZERO] * 5
    for label, restricted in [("Without donor restrictions", False), ("With donor restrictions", True)]:
        funds = [f for f in Fund.objects.all() if f.has_donor_restrictions == restricted]
        if not funds:
            continue
        report.section(label)
        for f in funds:
            inc_dr, inc_cr = activity.get((f.pk, Account.INCOME), (ZERO, ZERO))
            exp_dr, exp_cr = activity.get((f.pk, Account.EXPENSE), (ZERO, ZERO))
            eq_dr, eq_cr = activity.get((f.pk, Account.EQUITY), (ZERO, ZERO))
            row = [begin.get(f.pk, ZERO), inc_cr - inc_dr, exp_dr - exp_cr, eq_cr - eq_dr, ending.get(f.pk, ZERO)]
            if not any(row):
                continue
            report.add([f.name] + row, level=1, url=reverse("ledger:fund_detail", args=[f.pk]) + f"?start={start}&end={end}")
            totals = [x + y for x, y in zip(totals, row)]
    report.add(["All funds"] + totals, kind="grand")
    return report


def functional_expenses(start, end):
    functions = Account.FUNCTION_CHOICES
    report = Report("Statement of Functional Expenses", f"{start:%B %d, %Y} – {end:%B %d, %Y}",
                    [Column("")] + [Column(label.split(" (")[0]) for _, label in functions] + [Column("Unassigned"), Column("Total")])
    balances = services.account_balances(start=start, end=end)
    accounts = [a for a in Account.objects.filter(type=Account.EXPENSE) if balances.get(a.pk)]
    grand = [ZERO] * (len(functions) + 2)
    for label, group in _subtype_groups(Account.EXPENSE, accounts):
        report.group(label)
        sub = [ZERO] * (len(functions) + 2)
        for a in group:
            amount = balances[a.pk]
            row = [amount if a.function == code else ZERO for code, _ in functions]
            row.append(ZERO if a.function else amount)
            row.append(amount)
            report.add([a.name] + row, level=1, url=_register_url(a, start, end))
            sub = [x + y for x, y in zip(sub, row)]
        report.add([f"Total {label.lower()}"] + sub, kind="subtotal")
        grand = [x + y for x, y in zip(grand, sub)]
    report.add(["Total expenses"] + grand, kind="grand")
    if grand[-1]:
        report.add(["Percent of total"] + [_pct(v, grand[-1]) for v in grand], kind="note")
    report.notes.append("Each expense account is assigned to one function in the chart of accounts. Edit an account to change its function.")
    return report


def monthly_trend(year, fund=None):
    months = fiscal_months(year)
    report = Report("Income & Expenses by Month", f"{fiscal_year_label(year)}" + (f" · {fund}" if fund else " · all funds"),
                    [Column("")] + [Column(f"{first:%b}") for _, first, _ in months] + [Column("Total")], wide=True)
    per_month = [services.account_balances(start=f, end=l, funds=[fund] if fund else None) for _, f, l in months]
    sums = {}
    for type_, title in [(Account.INCOME, "Income"), (Account.EXPENSE, "Expenses")]:
        report.section(title)
        totals = [ZERO] * 13
        for a in Account.objects.filter(type=type_):
            vals = [m.get(a.pk, ZERO) for m in per_month]
            if not any(vals):
                continue
            vals.append(sum(vals, ZERO))
            report.add([a.name] + vals, level=1)
            totals = [x + y for x, y in zip(totals, vals)]
        report.add([f"Total {title.lower()}"] + totals, kind="total")
        sums[type_] = totals
    report.add(["Surplus / (deficit)"] + [i - e for i, e in zip(sums[Account.INCOME], sums[Account.EXPENSE])], kind="grand")
    return report


def cash_summary(year):
    months = fiscal_months(year)
    cash_ids = list(Account.objects.filter(subtype__in=Account.CASH_SUBTYPES).values_list("pk", flat=True))
    report = Report("Cash Receipts & Disbursements", f"{fiscal_year_label(year)} · bank and cash accounts",
                    [Column("Month"), Column("Beginning cash"), Column("Money in"), Column("Money out"), Column("Ending cash")])
    fy_start = months[0][1]
    opening = sum((services.account_balances(end=fy_start - timedelta(days=1)).get(a, ZERO) for a in cash_ids), ZERO)
    balance = opening
    tin = tout = ZERO
    base = JournalLine.objects.filter(entry__status=JournalEntry.POSTED, account_id__in=cash_ids).exclude(entry__source_type=JournalEntry.SOURCE_TRANSFER)
    transfers = JournalLine.objects.filter(entry__status=JournalEntry.POSTED, account_id__in=cash_ids, entry__source_type=JournalEntry.SOURCE_TRANSFER)
    for _, first, last in months:
        if first > today():
            break
        agg = base.filter(entry__date__gte=first, entry__date__lte=last).aggregate(dr=MoneySum("debit"), cr=MoneySum("credit"))
        tr = transfers.filter(entry__date__gte=first, entry__date__lte=last).aggregate(dr=MoneySum("debit"), cr=MoneySum("credit"))
        money_in, money_out = agg["dr"] or ZERO, agg["cr"] or ZERO
        ending = balance + money_in - money_out + (tr["dr"] or ZERO) - (tr["cr"] or ZERO)
        report.add([f"{first:%B %Y}", balance, money_in, money_out, ending])
        balance = ending
        tin += money_in
        tout += money_out
    report.add(["Year to date", opening, tin, tout, balance], kind="grand")
    report.notes.append("Transfers between the church's own bank and cash accounts are excluded from money in and out.")
    return report


# ------------------------------------------------------------------- giving

def giving_summary(start, end):
    qs = Contribution.objects.filter(batch__status=ContributionBatch.POSTED, date__gte=start, date__lte=end)
    total = qs.aggregate(t=MoneySum("amount"))["t"] or ZERO
    report = Report("Giving Summary", f"{start:%B %d, %Y} – {end:%B %d, %Y}",
                    [Column(""), Column("Gifts", "number"), Column("Givers", "number"), Column("Amount"), Column("% of total", "percent")])

    def block(title, rows):
        report.section(title)
        for label, n, d, amt in rows:
            report.add([label, n, d, amt, _pct(amt, total)], level=1)

    block("By fund", [(r["fund__name"], r["n"], r["d"], r["t"]) for r in
                      qs.values("fund__name").annotate(n=Count("id"), d=Count("donor", distinct=True), t=MoneySum("amount")).order_by("-t")])
    block("By category", [(r["account__name"], r["n"], r["d"], r["t"]) for r in
                          qs.values("account__name").annotate(n=Count("id"), d=Count("donor", distinct=True), t=MoneySum("amount")).order_by("-t")])
    labels = dict(Contribution.METHOD_CHOICES)
    block("By method", [(labels.get(r["method"], r["method"]), r["n"], r["d"], r["t"]) for r in
                        qs.values("method").annotate(n=Count("id"), d=Count("donor", distinct=True), t=MoneySum("amount")).order_by("-t")])
    monthly = defaultdict(lambda: [0, set(), ZERO])
    for c in qs.values("date", "donor_id", "amount"):
        key = c["date"].replace(day=1)
        monthly[key][0] += 1
        if c["donor_id"]:
            monthly[key][1].add(c["donor_id"])
        monthly[key][2] += c["amount"]
    block("By month", [(f"{k:%B %Y}", v[0], len(v[1]), v[2]) for k, v in sorted(monthly.items())])
    report.spacer()
    report.add(["Total giving", qs.count(), qs.exclude(donor=None).values("donor").distinct().count(), total, None], kind="grand")
    anon = qs.filter(donor=None).aggregate(t=MoneySum("amount"))["t"] or ZERO
    if anon:
        report.notes.append(f"Includes {anon:,.2f} of anonymous / loose offerings (not counted as givers).")
    return report


def donor_giving(start, end, lapsed_only=False, minimum=None):
    prior_start, prior_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
    posted = Contribution.objects.filter(batch__status=ContributionBatch.POSTED, donor__isnull=False)
    current = {r["donor"]: r for r in posted.filter(date__gte=start, date__lte=end).values("donor").annotate(
        t=MoneySum("amount"), n=Count("id"), first=Min("date"))}
    prior = {r["donor"]: r["t"] for r in posted.filter(date__gte=prior_start, date__lte=prior_end).values("donor").annotate(t=MoneySum("amount"))}
    from giving.models import Donor

    donor_ids = set(current) | set(prior)
    donors = Donor.objects.in_bulk(donor_ids)
    title = "Lapsed Donors" if lapsed_only else "Giving by Donor"
    report = Report(title, f"{start:%b %d, %Y} – {end:%b %d, %Y} compared with the same period a year earlier",
                    [Column("Donor", "text"), Column("Envelope", "text"), Column("Gifts", "number"), Column("This period"),
                     Column("Prior year"), Column("Change")])
    rows = []
    for pk in donor_ids:
        cur = current.get(pk, {}).get("t") or ZERO
        pri = prior.get(pk) or ZERO
        if lapsed_only and (cur or not pri):
            continue
        if minimum and cur < minimum:
            continue
        d = donors[pk]
        rows.append((d.sort_name, [d.display_name, d.envelope_number or "", current.get(pk, {}).get("n", 0), cur, pri, cur - pri], d.get_absolute_url()))
    rows.sort(key=lambda r: (-r[1][3], r[0]) if not lapsed_only else (-r[1][4], r[0]))
    for _, cells, url in rows:
        report.add(cells, url=url)
    report.add(["Total", "", sum(r[1][2] for r in rows), sum((r[1][3] for r in rows), ZERO), sum((r[1][4] for r in rows), ZERO),
                sum((r[1][5] for r in rows), ZERO)], kind="grand")
    if lapsed_only:
        report.notes.append("People who gave in the prior-year period but not in this period — consider a pastoral follow-up.")
    return report


# ----------------------------------------------------------------- payables

def ap_aging(as_of):
    report = Report("Unpaid Bills (Accounts Payable Aging)", f"As of {as_of:%B %d, %Y}",
                    [Column("Payee"), Column("Not yet due"), Column("1–30 days"), Column("31–60 days"), Column("61–90 days"),
                     Column("Over 90 days"), Column("Total")])
    by_vendor = defaultdict(lambda: [ZERO] * 6)
    vendors = {}
    for e in Expense.objects.filter(status__in=Expense.OPEN_BALANCE, date__lte=as_of).select_related("vendor"):
        due = e.due_date or e.date
        days = (as_of - due).days
        bucket = 0 if days <= 0 else 1 if days <= 30 else 2 if days <= 60 else 3 if days <= 90 else 4
        bal = e.balance_due
        by_vendor[e.vendor_id][bucket] += bal
        by_vendor[e.vendor_id][5] += bal
        vendors[e.vendor_id] = e.vendor
    totals = [ZERO] * 6
    for vid, vals in sorted(by_vendor.items(), key=lambda x: vendors[x[0]].name):
        report.add([vendors[vid].name] + vals, url=reverse("expenses:vendor_detail", args=[vid]))
        totals = [x + y for x, y in zip(totals, vals)]
    report.add(["Total"] + totals, kind="grand")
    ledger_ap = Account.system(Account.SYS_AP).balance(end=as_of)
    if ledger_ap != totals[5]:
        report.notes.append(f"The accounts payable balance in the ledger is {ledger_ap:,.2f}; differences come from manual journal entries to that account.")
    return report


def payments_by_payee(start, end, tax_forms_only=False):
    payments = ExpensePayment.objects.filter(is_void=False, date__gte=start, date__lte=end)
    if tax_forms_only:
        payments = payments.filter(expense__vendor__is_1099=True)
    rows = payments.values("expense__vendor", "expense__vendor__name", "expense__vendor__is_1099", "expense__vendor__tax_id").annotate(
        n=Count("id"), t=MoneySum("amount")).order_by("-t")
    report = Report("Year-End Tax Form Payees" if tax_forms_only else "Payments by Payee",
                    f"Cash paid {start:%B %d, %Y} – {end:%B %d, %Y}",
                    [Column("Payee", "text"), Column("Tax ID", "text"), Column("Needs tax form", "text"), Column("Payments", "number"), Column("Total paid")])
    total = ZERO
    for r in rows:
        report.add([r["expense__vendor__name"], r["expense__vendor__tax_id"], "Yes" if r["expense__vendor__is_1099"] else "",
                    r["n"], r["t"]], url=reverse("expenses:vendor_detail", args=[r["expense__vendor"]]))
        total += r["t"]
    report.add(["Total", "", "", sum(r["n"] for r in rows), total], kind="grand")
    if tax_forms_only:
        report.notes.append("In the US, contractors paid $600 or more in a calendar year generally need a Form 1099-NEC. Check your local rules.")
    return report


# ------------------------------------------------------------------- payroll

def payroll_summary(year):
    lines = PaycheckLine.objects.filter(paycheck__run__status=PayrollRun.POSTED, paycheck__run__pay_date__year=year).select_related("item", "paycheck__employee")
    items = sorted({l.item for l in lines}, key=lambda i: (i.sort_order, i.name))
    data = defaultdict(lambda: defaultdict(lambda: ZERO))
    employees = {}
    for l in lines:
        data[l.paycheck.employee_id][l.item.pk] += l.amount
        employees[l.paycheck.employee_id] = l.paycheck.employee
    cols = [Column("Employee", "text")] + [Column(i.name) for i in items] + [Column("Gross pay"), Column("Net pay"), Column("Total cost")]
    report = Report("Payroll Summary", f"Calendar year {year} · posted payrolls", cols, wide=True)
    totals = [ZERO] * (len(items) + 3)
    for eid, emp in sorted(employees.items(), key=lambda x: (x[1].last_name, x[1].first_name)):
        vals = [data[eid][i.pk] for i in items]
        gross = sum((data[eid][i.pk] for i in items if i.kind == PayrollItem.EARNING), ZERO)
        ded = sum((data[eid][i.pk] for i in items if i.kind == PayrollItem.DEDUCTION), ZERO)
        emp_cost = sum((data[eid][i.pk] for i in items if i.kind == PayrollItem.EMPLOYER), ZERO)
        vals += [gross, gross - ded, gross + emp_cost]
        report.add([emp.full_name] + vals, url=reverse("payroll:employee_detail", args=[eid]) + f"?year={year}")
        totals = [x + y for x, y in zip(totals, vals)]
    report.add(["Total"] + totals, kind="grand")
    report.notes.append("Use these totals to prepare year-end employee tax forms (e.g. W-2 / P60) and to reconcile payroll liability accounts.")
    return report


def payroll_liabilities(as_of):
    report = Report("Payroll Liabilities", f"Owed to tax authorities and providers as of {as_of:%B %d, %Y}",
                    [Column("Liability account"), Column("Balance owed")])
    total = ZERO
    for a in Account.objects.filter(subtype="payroll_liability"):
        bal = a.balance(end=as_of)
        if bal:
            report.add([str(a), bal], url=_register_url(a, fiscal_year_range(fiscal_year_of(as_of))[0], as_of))
            total += bal
    report.add(["Total owed", total], kind="grand")
    report.notes.append("Pay these by entering an expense to the tax authority or provider, charged to the liability account.")
    return report


def dashboard_months(n=12):
    """[(first, last)] for the last n calendar months including the current one."""
    t = today().replace(day=1)
    return [(add_months(t, -i), month_end(add_months(t, -i))) for i in range(n - 1, -1, -1)]

