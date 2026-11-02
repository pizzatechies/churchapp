"""Onboarding churches, recording their payments, and measuring how they use Ecclesia."""

import secrets
import string
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.db import connection, transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone
from django_tenants.utils import schema_context, tenant_context

from .models import Church, Payment

TRIAL_DAYS = 14


class PlatformError(Exception):
    pass


def temporary_password(length=12):
    """Easy to read out over the phone: no 0/O or 1/l/I."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw


def create_church_admin(username, email, password=None, first_name="", last_name=""):
    """In the current church schema: an Administrator login that must choose its own password on first sign-in."""
    from core.models import AccountProfile
    from core.permissions import ADMINISTRATOR

    if User.objects.filter(username__iexact=username).exists():
        raise PlatformError(f"There is already a login called “{username}” in this church.")
    password = password or temporary_password()
    user = User.objects.create_user(username, email, password, first_name=first_name, last_name=last_name, is_staff=True)
    user.groups.add(Group.objects.get(name=ADMINISTRATOR))
    AccountProfile.password_set_by_someone_else(user)
    return user, password


def create_church(*, name, slug, plan, admin_username, admin_email="", admin_password=None, billing_cycle=Church.MONTHLY,
                  country="KE", trial_days=TRIAL_DAYS, paid_until=None, contact_name="", contact_email="", contact_phone="",
                  notes="", created_by=None, is_default=False):
    """Create the church's own schema, its default chart of accounts, and its first administrator."""
    from core.setup import setup_church

    if Church.objects.filter(slug=slug).exists():
        raise PlatformError("That web address name is already taken.")
    connection.set_schema_to_public()
    church = Church(
        schema_name=Church.schema_for(slug), name=name, slug=slug, plan=plan, billing_cycle=billing_cycle, country=country,
        status=Church.ACTIVE if paid_until else Church.TRIAL,
        trial_ends=None if paid_until else timezone.localdate() + timedelta(days=trial_days),
        paid_until=paid_until, contact_name=contact_name, contact_email=contact_email or admin_email,
        contact_phone=contact_phone, notes=notes, created_by=created_by, is_default=is_default,
    )
    church.save(verbosity=0)  # creates the schema and runs every church migration
    user = password = None
    with tenant_context(church):
        setup_church(church_name=name, country=country)
        if admin_username:
            first, _, last = (contact_name or "").partition(" ")
            user, password = create_church_admin(admin_username, admin_email, admin_password, first_name=first, last_name=last)
    connection.set_schema_to_public()
    return church, user, password


@transaction.atomic
def record_payment(church, *, amount, months, method=Payment.MPESA, reference="", paid_on=None, notes="", user=None):
    church = Church.objects.select_for_update().get(pk=church.pk)
    start, end = church.extend(months)
    if church.status in (Church.SUSPENDED,) and church.suspended_reason.startswith("Overdue"):
        church.status, church.suspended_reason = Church.ACTIVE, ""
    church.save(update_fields=["paid_until", "status", "suspended_reason"])
    return Payment.objects.create(
        church=church, amount=amount, months=months, method=method, reference=reference, paid_on=paid_on or timezone.localdate(),
        covers_from=start, covers_to=end, notes=notes, recorded_by=user,
    )


def church_admins(church):
    from core.permissions import ADMINISTRATOR

    with tenant_context(church):
        return list(User.objects.filter(groups__name=ADMINISTRATOR, is_active=True).order_by("username").values("id", "username", "email", "last_login"))


def reset_admin_password(church, user_id):
    return reset_login_password(church, user_id)


# ------------------------------------------------------------------ usage

def _schema_size(schema):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(SUM(pg_total_relation_size(format('%%I.%%I', schemaname, tablename))), 0) FROM pg_tables WHERE schemaname = %s",
            [schema],
        )
        return int(cursor.fetchone()[0])


def collect_usage(church):
    """Counts only, never amounts or names: how big the church is and how actively it uses Ecclesia."""
    from core.models import AuditLog, Document
    from giving.models import Contribution
    from ledger.models import JournalEntry
    from members.models import Member, Sermon

    month_start = timezone.localdate().replace(day=1)
    with tenant_context(church):
        staff = (User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__isnull=False))
                 .exclude(username__startswith="support.").distinct())
        files = Document.objects.aggregate(t=Sum("size"))["t"] or 0
        sermon_bytes = 0
        for s in Sermon.objects.exclude(audio_file="", video_file="", notes_file=""):
            for f in (s.audio_file, s.video_file, s.notes_file):
                if f:
                    try:
                        sermon_bytes += f.size
                    except Exception:
                        pass
        usage = {
            "members": Member.objects.filter(status__in=Member.CURRENT).count(),
            "member_logins": User.objects.filter(is_active=True, member_profile__isnull=False).count(),
            "staff": staff.count(),
            "entries_this_month": JournalEntry.objects.filter(date__gte=month_start).count(),
            "gifts_this_month": Contribution.objects.filter(date__gte=month_start).count(),
            "sermons": Sermon.objects.count(),
            "last_staff_login": _iso(User.objects.filter(member_profile__isnull=True).exclude(username__startswith="support.")
                                     .aggregate(m=Max("last_login"))["m"]),
            "last_member_login": _iso(User.objects.filter(member_profile__isnull=False).aggregate(m=Max("last_login"))["m"]),
            "last_activity": _iso(AuditLog.objects.aggregate(m=Max("timestamp"))["m"]),
            "files_bytes": int(files) + sermon_bytes,
        }
    usage["database_bytes"] = _schema_size(church.schema_name)
    usage["storage_bytes"] = usage["files_bytes"] + usage["database_bytes"]
    connection.set_schema_to_public()
    Church.objects.filter(pk=church.pk).update(usage=usage, usage_updated_at=timezone.now())
    church.usage, church.usage_updated_at = usage, timezone.now()
    return usage


def _iso(value):
    return value.isoformat() if value else None


def usage_is_stale(church, minutes=30):
    return not church.usage_updated_at or timezone.now() - church.usage_updated_at > timedelta(minutes=minutes)


def limits(church):
    """[(label, used, allowed or None, over?)] for the plan's limits."""
    u, p = church.usage or {}, church.plan
    rows = [
        ("Members", u.get("members", 0), p.max_members),
        ("Staff logins", u.get("staff", 0), p.max_staff),
        ("Storage (GB)", round((u.get("storage_bytes", 0) or 0) / 1024 ** 3, 2), p.storage_gb),
    ]
    return [(label, used, allowed, allowed is not None and used > allowed) for label, used, allowed in rows]


def schema_has_church_tables(schema):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'core_churchprofile'", [schema])
        return cursor.fetchone() is not None


def in_public(fn):
    def wrapper(*args, **kwargs):
        with schema_context("public"):
            return fn(*args, **kwargs)
    return wrapper


# ------------------------------------------------------- super admin powers

def start_support_session(church, platform_user, reason="", ip=None):
    """Prepare a one-time, two-minute sign-in to the church as an administrator. Returns the signed token."""
    from django.core import signing

    from .models import SupportSession

    if not church.is_accessible:
        raise PlatformError(f"{church.name} is {church.get_status_display().lower()}. Reactivate it first.")
    session = SupportSession.objects.create(church=church, platform_user=platform_user, reason=reason[:200],
                                            nonce=secrets.token_urlsafe(32), ip=ip)
    with tenant_context(church):
        _support_user(church, platform_user)
    connection.set_schema_to_public()
    return signing.dumps({"s": session.pk, "n": session.nonce}, salt=f"support:{church.schema_name}")


def _support_user(church, platform_user):
    """In the church's schema: the super admin's own administrator login. It has no password, so it can only be
    reached from the console, and every change made with it is attributed to them by name in the audit trail."""
    from .models import SUPPORT_USERNAME_PREFIX

    username = f"{SUPPORT_USERNAME_PREFIX}{platform_user.username}"[:150]
    user, _ = User.objects.get_or_create(username=username)
    user.first_name = (platform_user.get_full_name() or platform_user.username)[:150]
    user.last_name = "(Ecclesia support)"
    user.email = ""
    user.is_active = user.is_staff = user.is_superuser = True
    user.set_unusable_password()
    user.save()
    return user


def is_support_login(user):
    from .models import SUPPORT_USERNAME_PREFIX

    return bool(user and user.username.startswith(SUPPORT_USERNAME_PREFIX))


def church_logins(church):
    """Every staff login in a church (not member-only logins, not support logins)."""
    from .models import SUPPORT_USERNAME_PREFIX

    with tenant_context(church):
        users = (User.objects.filter(Q(is_superuser=True) | Q(groups__isnull=False)).exclude(username__startswith=SUPPORT_USERNAME_PREFIX)
                 .distinct().prefetch_related("groups").order_by("-is_active", "username"))
        rows = [{"id": u.pk, "username": u.username, "name": u.get_full_name(), "email": u.email, "is_active": u.is_active,
                 "last_login": u.last_login, "roles": sorted(g.name for g in u.groups.all()) or (["Superuser"] if u.is_superuser else [])}
                for u in users]
    connection.set_schema_to_public()
    return rows


def add_church_login(church, username, email, role, first_name="", last_name=""):
    from core.limits import staff_limit_message
    from core.models import AccountProfile

    with tenant_context(church):
        if User.objects.filter(username__iexact=username).exists():
            raise PlatformError(f"{church.name} already has a login called “{username}”.")
        limit = staff_limit_message()
        if limit:
            raise PlatformError(limit)
        password = temporary_password()
        user = User.objects.create_user(username, email, password, first_name=first_name, last_name=last_name,
                                        is_staff=role == "Administrator")
        user.groups.add(Group.objects.get(name=role))
        AccountProfile.password_set_by_someone_else(user)
    connection.set_schema_to_public()
    return user, password


def set_login_active(church, user_id, active):
    from core.limits import staff_limit_message

    with tenant_context(church):
        user = User.objects.get(pk=user_id)
        if active and not user.is_active:
            limit = staff_limit_message()
            if limit:
                raise PlatformError(limit)
        user.is_active = active
        user.save(update_fields=["is_active"])
        username = user.username
    connection.set_schema_to_public()
    return username


def set_login_role(church, user_id, role):
    with tenant_context(church):
        user = User.objects.get(pk=user_id)
        user.groups.set([Group.objects.get(name=role)])
        user.is_staff = role == "Administrator"
        user.save(update_fields=["is_staff"])
        username = user.username
    connection.set_schema_to_public()
    return username


def find_people(query, limit_per_church=10):
    """Logins matching a username, name or email, in every church. For support: "which church is this person in?"."""
    from .models import SUPPORT_USERNAME_PREFIX

    query = query.strip()
    results = []
    if len(query) < 2:
        return results
    for church in Church.objects.select_related("plan").order_by("name"):
        with tenant_context(church):
            users = (User.objects.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(first_name__icontains=query)
                                         | Q(last_name__icontains=query))
                     .exclude(username__startswith=SUPPORT_USERNAME_PREFIX).prefetch_related("groups")[:limit_per_church])
            for u in users:
                member = getattr(u, "member_profile", None)
                results.append({"church": church, "id": u.pk, "username": u.username, "name": u.get_full_name(), "email": u.email,
                                "is_active": u.is_active, "last_login": u.last_login,
                                "kind": "Staff" if (u.is_superuser or u.groups.exists()) else ("Member" if member else "Login"),
                                "roles": ", ".join(sorted(g.name for g in u.groups.all()))})
    connection.set_schema_to_public()
    return results


def reset_login_password(church, user_id):
    """A new temporary password for any login in the church (staff or member)."""
    from core.models import AccountProfile

    with tenant_context(church):
        user = User.objects.get(pk=user_id)
        if is_support_login(user):
            raise PlatformError("Support logins don't have passwords.")
        password = temporary_password()
        user.set_password(password)
        user.save(update_fields=["password"])
        AccountProfile.password_set_by_someone_else(user)
        username = user.username
    connection.set_schema_to_public()
    return username, password


def current_announcements(church, members_app=False):
    """Platform notices for this church and app, cached for a minute."""
    from django.core.cache import cache

    from .models import Announcement

    key = f"announcements:{'members' if members_app else 'staff'}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    now = timezone.now()
    audiences = [Announcement.EVERYONE, Announcement.MEMBERS if members_app else Announcement.STAFF]
    qs = (Announcement.objects.filter(is_active=True, starts_at__lte=now, audience__in=audiences)
          .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
          .filter(Q(churches__isnull=True) | Q(churches=church)).distinct())
    items = [{"message": a.message, "level": a.level} for a in qs[:3]]
    cache.set(key, items, 60)
    return items
