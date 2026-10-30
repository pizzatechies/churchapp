from django import template
from django.conf import settings

from core.demo import member_logins, staff_logins

register = template.Library()


@register.inclusion_tag("includes/demo_logins.html")
def demo_logins(kind):
    """One-click sign-in buttons on the login page of a public demo server."""
    if not settings.DEMO_MODE:
        return {"logins": []}
    return {"logins": staff_logins() if kind == "staff" else member_logins(), "password": settings.DEMO_PASSWORD}
