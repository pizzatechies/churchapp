from datetime import datetime

from django import template
from django.utils.html import format_html

register = template.Library()

STATE_STYLES = {"active": "success", "trial": "info", "overdue": "warning", "suspended": "danger", "cancelled": "secondary"}


@register.simple_tag
def state_badge(code, label):
    return format_html('<span class="badge rounded-pill text-bg-{}">{}</span>', STATE_STYLES.get(code, "secondary"), label)


@register.filter
def iso_date(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


@register.filter
def filesize(value):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
