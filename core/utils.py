import calendar
import csv
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def q2(value):
    """Round to cents (banker-friendly half-up rounding)."""
    if value is None:
        return ZERO
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(value, default=ZERO):
    if value in (None, ""):
        return default
    try:
        return q2(Decimal(str(value).replace(",", "")))
    except (InvalidOperation, ValueError):
        return default


def today():
    return timezone.localdate()


def parse_date(value, default=None):
    if not value:
        return default
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return default


def month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start, end):
    """Number of calendar months from start's month to end's month inclusive."""
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


# ---------------------------------------------------------------- fiscal years

def fiscal_start_month():
    from .models import ChurchProfile

    return ChurchProfile.cached().fiscal_year_start_month


def fiscal_year_of(d, start_month=None):
    """Fiscal years are identified by the calendar year in which they start."""
    start_month = start_month or fiscal_start_month()
    return d.year if d.month >= start_month else d.year - 1


def fiscal_year_range(year, start_month=None):
    start_month = start_month or fiscal_start_month()
    start = date(year, start_month, 1)
    end = add_months(start, 12) - timedelta(days=1)
    return start, end


def fiscal_year_label(year, start_month=None):
    start_month = start_month or fiscal_start_month()
    if start_month == 1:
        return f"FY {year}"
    return f"FY {year}–{str(year + 1)[-2:]}"


def fiscal_months(year, start_month=None):
    """List of (index 0-11, first day, last day) for each month of a fiscal year."""
    start, _ = fiscal_year_range(year, start_month)
    months = []
    for i in range(12):
        first = add_months(start, i)
        months.append((i, first, month_end(first)))
    return months


def fiscal_year_choices(span_back=6, span_forward=1):
    current = fiscal_year_of(today())
    return [(y, fiscal_year_label(y)) for y in range(current + span_forward, current - span_back - 1, -1)]


def period_from_request(request, default="fytd"):
    """
    Read a reporting period from GET parameters.

    Supports explicit ?start=&end= dates or a named ?period= preset.
    Returns (start, end, period_key).
    """
    d = today()
    key = request.GET.get("period") or default
    start = parse_date(request.GET.get("start"))
    end = parse_date(request.GET.get("end"))
    if start or end:
        key = "custom"
        fy_start, _ = fiscal_year_range(fiscal_year_of(d))
        return start or fy_start, end or d, key
    fy = fiscal_year_of(d)
    fy_start, fy_end = fiscal_year_range(fy)
    if key == "month":
        return d.replace(day=1), month_end(d), key
    if key == "last_month":
        last = d.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last, key
    if key == "quarter":
        q_start_month = ((d.month - 1) // 3) * 3 + 1
        q_start = date(d.year, q_start_month, 1)
        return q_start, month_end(add_months(q_start, 2)), key
    if key == "fy":
        return fy_start, fy_end, key
    if key == "last_fy":
        return fiscal_year_range(fy - 1) + (key,)
    if key == "ytd":
        return date(d.year, 1, 1), d, key
    if key == "last_year":
        return date(d.year - 1, 1, 1), date(d.year - 1, 12, 31), key
    return fy_start, d, "fytd"


PERIOD_CHOICES = [
    ("month", "This month"),
    ("last_month", "Last month"),
    ("quarter", "This quarter"),
    ("fytd", "Fiscal year to date"),
    ("fy", "This fiscal year"),
    ("last_fy", "Last fiscal year"),
    ("ytd", "Calendar year to date"),
    ("last_year", "Last calendar year"),
]


def csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return response


class MoneySum(Sum):
    """Sum of a money column, always returned as an exact two-decimal Decimal (SQLite returns floats)."""

    def get_db_converters(self, connection):
        return super().get_db_converters(connection) + [self._to_cents]

    @staticmethod
    def _to_cents(value, expression, connection):
        return q2(value) if value is not None else None
