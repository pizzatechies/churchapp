"""The church's plan limits (members and staff logins), checked where records are added."""

from django.contrib.auth.models import User
from django.db.models import Q


def current_plan():
    from tenants.middleware import current_church

    church = current_church()
    return church.plan if church else None


def member_limit_message(adding=1):
    from members.models import Member

    plan = current_plan()
    if plan is None or plan.max_members is None:
        return None
    current = Member.objects.filter(status__in=Member.CURRENT).count()
    if current + adding > plan.max_members:
        return (f"Your {plan.name} plan includes up to {plan.max_members:,} members, and you have {current:,}. "
                "Ask Pizza Technologies about moving to a bigger plan.")
    return None


def staff_count():
    # Ecclesia support logins (super admins helping the church) never use up the church's staff logins.
    return (User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__isnull=False))
            .exclude(username__startswith="support.").distinct().count())


def staff_limit_message(adding=1):
    plan = current_plan()
    if plan is None or plan.max_staff is None:
        return None
    current = staff_count()
    if current + adding > plan.max_staff:
        return (f"Your {plan.name} plan includes {plan.max_staff} staff logins, and {current} are in use. "
                "Deactivate one you no longer need, or ask Pizza Technologies about a bigger plan.")
    return None
