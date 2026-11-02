"""Inside a church's admin app: a super admin arriving from the console, and leaving again."""

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import User
from django.core import signing
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_tenants.utils import get_public_schema_name, schema_context

from core.models import AuditLog

from .middleware import current_church
from .models import SupportSession

TOKEN_MAX_AGE = 120  # seconds


@login_not_required
def support_enter(request, token):
    church = current_church()
    if church is None:
        return HttpResponseForbidden("Not a church address.")
    try:
        data = signing.loads(token, salt=f"support:{church.schema_name}", max_age=TOKEN_MAX_AGE)
        # Platform records (and the super admin's own login) live in the shared schema: read them there, not
        # through this church's schema, where "auth_user" is the church's own list of logins.
        with schema_context(get_public_schema_name()):
            session = SupportSession.objects.select_related("platform_user").get(
                pk=data["s"], nonce=data["n"], church_id=church.pk, used_at__isnull=True)
            admin = session.platform_user
            allowed = admin.is_active and admin.is_superuser
            admin_name, admin_username, church_username = admin.get_full_name() or admin.username, admin.username, session.church_username
            if allowed:
                SupportSession.objects.filter(pk=session.pk).update(used_at=timezone.now())
    except (signing.BadSignature, SupportSession.DoesNotExist, KeyError, TypeError):
        return HttpResponseForbidden("This sign-in link has expired or was already used. Start again from the console.")
    if not allowed:
        return HttpResponseForbidden("This super admin can no longer sign in.")
    user = User.objects.get(username=church_username)
    if request.user.is_authenticated:
        logout(request)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["support_session"] = session.pk
    request.session["support_from"] = f"/platform/churches/{church.pk}/"
    AuditLog.objects.create(
        user=user, action=AuditLog.UPDATE, model="support access", object_id=str(session.pk),
        object_repr=f"Ecclesia support signed in: {admin_name}"[:200],
        changes={"super_admin": admin_username, "reason": session.reason},
    )
    messages.info(request, f"You're in {church.name} as an administrator. Everything you change is recorded under your name.")
    return redirect("dashboard")


@require_POST
def support_leave(request):
    session_pk = request.session.get("support_session")
    back = request.session.get("support_from", "/platform/")
    if session_pk:
        SupportSession.objects.filter(pk=session_pk, ended_at__isnull=True).update(ended_at=timezone.now())
    logout(request)
    return redirect(back if back.startswith("/platform/") else "/platform/")
