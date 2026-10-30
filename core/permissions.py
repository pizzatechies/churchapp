"""
Role-based access control.

Each user is given one or more roles (stored as Django groups). Roles grant
capabilities; views and templates check capabilities, never role names, so the
matrix below is the single place that decides who can do what.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

ADMINISTRATOR = "Administrator"
TREASURER = "Treasurer"
BOOKKEEPER = "Bookkeeper"
FINANCE_COMMITTEE = "Finance Committee"
OFFERING_COUNTER = "Offering Counter"
VIEWER = "Pastor / Viewer"

ROLES = [ADMINISTRATOR, TREASURER, BOOKKEEPER, FINANCE_COMMITTEE, OFFERING_COUNTER, VIEWER]

ROLE_DESCRIPTIONS = {
    ADMINISTRATOR: "Full access, including users, settings, backups and closing the books.",
    TREASURER: "Manages all finances: giving, expenses, payroll, budgets, approvals and settings.",
    BOOKKEEPER: "Day-to-day entry: giving, expenses, payments, journal entries and reconciliations.",
    FINANCE_COMMITTEE: "Reviews reports, approves expenses and sets budgets.",
    OFFERING_COUNTER: "Counts and records offerings and maintains donor records. No access to reports.",
    VIEWER: "Read-only access to financial reports and the dashboard (no individual giving or payroll).",
}

_FULL = [ADMINISTRATOR, TREASURER]
_STAFF = [ADMINISTRATOR, TREASURER, BOOKKEEPER]

CAPABILITIES = {
    # Dashboard, ledger and financial reports (read-only).
    "view_finance": _STAFF + [FINANCE_COMMITTEE, VIEWER],
    # Individual donor records and giving history are confidential.
    "view_donors": _STAFF + [OFFERING_COUNTER],
    "manage_giving": _STAFF + [OFFERING_COUNTER],
    "post_giving": _STAFF,
    "manage_expenses": _STAFF,
    "approve_expenses": _FULL + [FINANCE_COMMITTEE],
    "pay_expenses": _STAFF,
    "manage_ledger": _STAFF,
    "manage_budget": _FULL + [FINANCE_COMMITTEE],
    "view_payroll": _FULL,
    "manage_payroll": _FULL,
    "manage_assets": _STAFF,
    "manage_settings": _FULL,
    "manage_users": [ADMINISTRATOR],
    "view_audit": _FULL,
}


def user_roles(user):
    if not user or not user.is_authenticated:
        return set()
    if not hasattr(user, "_role_cache"):
        user._role_cache = set(user.groups.values_list("name", flat=True))
    return user._role_cache


def has_cap(user, cap):
    if cap not in CAPABILITIES:
        raise KeyError(f"Unknown capability {cap!r}")
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return bool(user_roles(user) & set(CAPABILITIES[cap]))


def capabilities_for(user):
    return {cap: has_cap(user, cap) for cap in CAPABILITIES}


def require_cap(*caps):
    """View decorator: the user needs at least one of the listed capabilities."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not any(has_cap(request.user, cap) for cap in caps):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapper.required_caps = caps
        return wrapper

    return decorator


def check_cap(user, cap):
    if not has_cap(user, cap):
        raise PermissionDenied
