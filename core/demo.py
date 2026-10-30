"""
Public demo mode (ECCLESIA_DEMO_MODE=1): for a demo server anyone can try from the website.

Visitors get one-click demo logins and a banner, and may change anything except the
logins themselves, so one visitor can't lock the next one out. `manage.py reset_demo`
puts the sample church back; it refuses to run unless demo mode is on.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import redirect

# Views that change logins: password changes and user accounts.
BLOCKED_VIEWS = {"password_change", "user_create", "user_edit", "password"}


class DemoModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not settings.DEMO_MODE or request.method != "POST":
            return None
        name = request.resolver_match.url_name if request.resolver_match else None
        if name in BLOCKED_VIEWS or request.path.startswith("/django-admin/"):
            messages.warning(request, "This is a public demo, so passwords and logins can't be changed. Everything else is yours to try.")
            return redirect(request.META.get("HTTP_REFERER") or "/")
        return None


def staff_logins():
    from core.management.commands.load_demo_data import STAFF_USERS

    existing = set(User.objects.filter(username__in=[u[0] for u in STAFF_USERS], is_active=True).values_list("username", flat=True))
    return [{"username": username, "role": role} for username, _, _, role, _ in STAFF_USERS if username in existing]


def member_logins(limit=4):
    from members.models import Member

    # Show women and men, so visitors see the gender-specific fellowships from both sides.
    picked = []
    for gender in (Member.FEMALE, Member.MALE):
        members = Member.objects.filter(gender=gender, user__is_active=True, status__in=Member.CURRENT).order_by("pk")
        picked += [{"username": m.user.username, "role": m.full_name} for m in members.select_related("user")[: limit // 2]]
    return picked
