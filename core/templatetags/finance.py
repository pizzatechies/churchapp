from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.models import ChurchProfile

register = template.Library()


def _to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format(amount, symbol=True):
    sym = ChurchProfile.cached().currency_symbol if symbol else ""
    return f"{sym}{abs(amount):,.2f}"


@register.filter
def money(value, show_symbol=True):
    """1234.5 -> $1,234.50 ; -20 -> -$20.00"""
    amount = _to_decimal(value)
    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    return f"{sign}{_format(amount, show_symbol)}"


@register.filter
def acct(value, show_symbol=False):
    """Accounting style: negatives in parentheses, zero as a dash."""
    amount = _to_decimal(value)
    if amount is None:
        return ""
    if amount == 0:
        return mark_safe('<span class="text-body-tertiary">–</span>')
    text = _format(amount, show_symbol)
    if amount < 0:
        return format_html('<span class="text-danger">({})</span>', text)
    return text


@register.filter
def pct(value, places=0):
    amount = _to_decimal(value)
    if amount is None:
        return ""
    return f"{amount:.{int(places)}f}%"


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        try:
            return mapping[key]
        except (KeyError, IndexError, TypeError):
            return None


@register.filter
def can(caps, name):
    return bool(caps and caps.get(name))


STATUS_STYLES = {
    "draft": "secondary",
    "open": "info",
    "pending": "warning",
    "approved": "primary",
    "partial": "info",
    "paid": "success",
    "posted": "success",
    "completed": "success",
    "in_progress": "warning",
    "rejected": "danger",
    "void": "dark",
    "active": "success",
    "disposed": "secondary",
    "inactive": "secondary",
}


@register.simple_tag
def status_badge(status, label=None):
    style = STATUS_STYLES.get(status, "secondary")
    return format_html('<span class="badge rounded-pill text-bg-{}">{}</span>', style, label or str(status).replace("_", " ").title())


@register.simple_tag
def currency_symbol():
    return ChurchProfile.cached().currency_symbol
