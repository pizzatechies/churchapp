import io
import mimetypes

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core import management
from django.core.exceptions import PermissionDenied
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ChurchProfileForm, DocumentForm, LockDateForm, UserForm
from .models import AuditLog, ChurchProfile, Document
from .permissions import ROLE_DESCRIPTIONS, has_cap, require_cap

# Which capability is needed to view / add attachments, per model.
DOCUMENT_CAPS = {
    "ledger.journalentry": ("view_finance", "manage_ledger"),
    "ledger.reconciliation": ("view_finance", "manage_ledger"),
    "giving.contributionbatch": ("manage_giving", "manage_giving"),
    "expenses.expense": ("manage_expenses", "manage_expenses"),
    "expenses.vendor": ("manage_expenses", "manage_expenses"),
    "fixedassets.fixedasset": ("view_finance", "manage_assets"),
    "payroll.employee": ("view_payroll", "manage_payroll"),
}


def document_context(obj, user):
    """Template context for includes/documents.html."""
    label = obj._meta.label_lower
    view_cap, edit_cap = DOCUMENT_CAPS.get(label, ("manage_settings", "manage_settings"))
    return {
        "content_type_id": ContentType.objects.get_for_model(obj).pk,
        "can_attach": has_cap(user, edit_cap),
    }


def _document_caps(content_type):
    return DOCUMENT_CAPS.get(f"{content_type.app_label}.{content_type.model}", ("manage_settings", "manage_settings"))


@require_POST
def document_upload(request, content_type_id, object_id):
    content_type = get_object_or_404(ContentType, pk=content_type_id)
    _, edit_cap = _document_caps(content_type)
    if not has_cap(request.user, edit_cap):
        raise PermissionDenied
    obj = get_object_or_404(content_type.model_class(), pk=object_id)
    form = DocumentForm(request.POST, request.FILES)
    if form.is_valid():
        form.save(obj, request.user)
        messages.success(request, "File attached.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(request.META.get("HTTP_REFERER") or obj.get_absolute_url())


def document_download(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    view_cap, _ = _document_caps(doc.content_type)
    if not has_cap(request.user, view_cap):
        raise PermissionDenied
    if not isinstance(doc.file.storage, FileSystemStorage):
        return HttpResponseRedirect(doc.file.url)
    try:
        handle = doc.file.open("rb")
    except FileNotFoundError:
        raise Http404("The file is missing from storage.")
    content_type = mimetypes.guess_type(doc.original_name)[0] or "application/octet-stream"
    inline = content_type.startswith("image/") or content_type == "application/pdf"
    return FileResponse(handle, as_attachment=not inline, filename=doc.original_name, content_type=content_type)


@require_POST
def document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    _, edit_cap = _document_caps(doc.content_type)
    if not has_cap(request.user, edit_cap):
        raise PermissionDenied
    doc.file.delete(save=False)
    doc.delete()
    messages.success(request, "Attachment deleted.")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard")


# ------------------------------------------------------------------ settings

@require_cap("manage_settings")
def settings_view(request):
    profile = ChurchProfile.get()
    form = ChurchProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Church settings saved.")
        return redirect("settings")
    from members.models import Member

    unlinked = Member.objects.filter(status__in=Member.CURRENT, donor__isnull=True, user__isnull=False, user__is_active=True).count()
    return render(request, "core/settings.html", {"form": form, "profile": profile, "unlinked_members": unlinked})


def support_visits(church):
    """Read from the shared schema: inside a church, "auth_user" means the church's own logins."""
    from django_tenants.utils import schema_context

    with schema_context("public"):
        return [{"when": s.used_at, "who": s.platform_user.get_full_name() or s.platform_user.username, "reason": s.reason}
                for s in church.support_sessions.filter(used_at__isnull=False).select_related("platform_user")[:10]]


@require_cap("manage_settings")
def subscription(request):
    from tenants.middleware import current_church
    from tenants.services import collect_usage, limits, usage_is_stale

    church = current_church()
    if church is None:
        raise Http404
    if usage_is_stale(church, minutes=10):
        collect_usage(church)
    return render(request, "core/subscription.html", {
        "account": church, "state": church.state, "limits": limits(church), "payments": church.payments.all()[:12],
        "support_visits": support_visits(church),
    })


@require_cap("manage_settings")
def close_books(request):
    profile = ChurchProfile.get()
    form = LockDateForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        if profile.lock_date:
            messages.success(request, f"The books are now closed through {profile.lock_date:%B %d, %Y}.")
        else:
            messages.success(request, "The books are open; no closing date is set.")
        return redirect("settings")
    return render(request, "core/close_books.html", {"form": form, "profile": profile})


# --------------------------------------------------------------------- users

@require_cap("manage_users")
def user_list(request):
    users = User.objects.prefetch_related("groups").order_by("-is_active", "username")
    return render(request, "core/user_list.html", {"users": users, "role_descriptions": ROLE_DESCRIPTIONS})


@require_cap("manage_users")
def user_edit(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        from .limits import staff_limit_message

        was_staff = bool(instance and instance.is_active and (instance.is_superuser or instance.groups.exists()))
        becomes_staff = form.cleaned_data["is_active"] and bool(form.cleaned_data["roles"])
        limit = staff_limit_message() if becomes_staff and not was_staff else None
        if instance and instance == request.user and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "You cannot deactivate your own account.")
        elif limit:
            form.add_error(None, limit)
        else:
            user = form.save(set_by=request.user)
            messages.success(request, f"User {user.username} saved." + (
                " They'll choose their own password when they first sign in." if form.cleaned_data.get("password") and user != request.user else ""))
            return redirect("user_list")
    return render(request, "core/user_form.html", {"form": form, "instance": instance})


# --------------------------------------------------------------------- audit

@require_cap("view_audit")
def audit_log(request):
    logs = AuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    model = request.GET.get("model", "")
    user_id = request.GET.get("user", "")
    if q:
        logs = logs.filter(Q(object_repr__icontains=q) | Q(object_id=q))
    if model:
        logs = logs.filter(model=model)
    if user_id:
        logs = logs.filter(user_id=user_id)
    page = Paginator(logs, 50).get_page(request.GET.get("page"))
    models = AuditLog.objects.order_by().values_list("model", flat=True).distinct()
    return render(request, "core/audit_log.html", {
        "page_obj": page, "models": sorted(set(models)), "users": User.objects.order_by("username"),
        "q": q, "model": model, "user_id": user_id,
    })


# -------------------------------------------------------------------- backup

BACKUP_APPS = ["auth.user", "auth.group", "core", "ledger", "giving", "expenses", "payroll", "fixedassets", "members", "bankfeeds"]


@require_cap("manage_users")
def backup(request):
    if request.method == "POST":
        buffer = io.StringIO()
        management.call_command(
            "dumpdata", *BACKUP_APPS, "--natural-foreign", "--indent", "1", stdout=buffer,
        )
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        response = HttpResponse(buffer.getvalue(), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="ecclesia-backup-{stamp}.json"'
        return response
    counts = []
    for label in ["ledger.JournalEntry", "giving.Contribution", "giving.Donor", "expenses.Expense",
                  "payroll.Paycheck", "fixedassets.FixedAsset", "members.Member", "members.Group",
                  "members.Sermon", "core.Document"]:
        model = apps.get_model(label)
        counts.append((model._meta.verbose_name_plural.title(), model.objects.count()))
    return render(request, "core/backup.html", {"counts": counts})


@login_not_required
def health(request):
    """For load balancers and uptime monitors: checks the app can reach the database."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    on_platform = getattr(connection, "schema_name", "public") == "public"
    response = JsonResponse({
        "status": "ok",
        "app": settings.APP_NAME,
        "product": settings.PRODUCT_NAME,
        "church": None if on_platform else ChurchProfile.cached().name,
    })
    # The mobile and desktop apps check this address before connecting to it.
    response["Access-Control-Allow-Origin"] = "*"
    return response
