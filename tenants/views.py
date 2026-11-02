"""The platform console (Pizza Technologies' super admins) and the public church finder."""

import csv
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    AccountForm,
    AddLoginForm,
    AnnouncementForm,
    ChurchCreateForm,
    ChurchEditForm,
    DomainForm,
    PaymentForm,
    PlanFormSet,
    TeamMemberForm,
)
from .models import Announcement, Church, Domain, Payment, Plan, PlatformProfile, SupportSession
from .security import LockoutMixin, PlatformPasswordResetForm, client_ip, reset_allowed


def platform_admin_required(view):
    @login_not_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('platform:login')}?next={request.get_full_path()}")
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def app_addresses(request, church):
    admin = settings.ADMIN_APP_URL or request.build_absolute_uri("/").rstrip("/")
    members = settings.MEMBERS_APP_URL
    if not members and "-admin." in admin:
        members = admin.replace("-admin.", "-members.")
    path = f"/{settings.CHURCH_URL_PREFIX}/{church.slug}/"
    return {"admin": admin + path, "members": (members + path) if members else "",
            "domains": list(church.domains.values_list("domain", flat=True))}


# ------------------------------------------------------------- signing in

class PlatformAuthForm(LockoutMixin, AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser:
            raise self.get_invalid_login_error()


@method_decorator(login_not_required, name="dispatch")
class PlatformLoginView(auth_views.LoginView):
    template_name = "tenants/login.html"
    authentication_form = PlatformAuthForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return reverse("platform:dashboard")


@login_not_required
def logout_view(request):
    if request.method == "POST":
        logout(request)
    return redirect("platform:login")


def _clear_platform_flag(user):
    PlatformProfile.objects.update_or_create(user=user, defaults={"must_change_password": False})


@method_decorator(platform_admin_required, name="dispatch")
class PlatformPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "tenants/password_change.html"
    success_url = reverse_lazy("platform:account")

    def form_valid(self, form):
        response = super().form_valid(form)
        _clear_platform_flag(self.request.user)
        messages.success(self.request, "Your password was changed.")
        return response


@method_decorator(login_not_required, name="dispatch")
class PlatformPasswordResetView(auth_views.PasswordResetView):
    template_name = "tenants/password_reset.html"
    form_class = PlatformPasswordResetForm
    email_template_name = "emails/password_reset.txt"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("platform:password_reset_done")
    extra_email_context = {"app_name": "the Ecclesia platform console", "reset_url_name": "platform:password_reset_confirm"}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "email_configured": settings.EMAIL_CONFIGURED}

    def form_valid(self, form):
        if not settings.EMAIL_CONFIGURED or not reset_allowed(self.request):
            return redirect(self.success_url)
        return super().form_valid(form)


@method_decorator(login_not_required, name="dispatch")
class PlatformPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "tenants/password_reset_done.html"


@method_decorator(login_not_required, name="dispatch")
class PlatformPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "tenants/password_reset_confirm.html"
    success_url = reverse_lazy("platform:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        _clear_platform_flag(form.user)
        return response


@method_decorator(login_not_required, name="dispatch")
class PlatformPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "tenants/password_reset_complete.html"


@platform_admin_required
def account(request):
    profile, _ = PlatformProfile.objects.get_or_create(user=request.user)
    form = AccountForm(request.POST or None, instance=request.user, initial={"phone": profile.phone})
    if request.method == "POST" and form.is_valid():
        form.save()
        profile.phone = form.cleaned_data["phone"]
        profile.save(update_fields=["phone"])
        messages.success(request, "Your details were saved.")
        return redirect("platform:account")
    return render(request, "tenants/account.html", {"form": form, "profile": profile})


# -------------------------------------------------------------- churches

@platform_admin_required
def dashboard(request):
    churches = list(Church.objects.select_related("plan").order_by("name"))
    if request.method == "POST" and "refresh" in request.POST:
        for c in churches:
            services.collect_usage(c)
        messages.success(request, "Usage refreshed for every church.")
        return redirect("platform:dashboard")
    stale = [c for c in churches if services.usage_is_stale(c)][:3]
    for c in stale:  # a few per visit keeps the page quick; "Refresh usage" does them all
        services.collect_usage(c)
    q = request.GET.get("q", "").strip().lower()
    state = request.GET.get("state", "")
    rows = []
    for c in churches:
        code, label = c.state
        if q and q not in c.name.lower() and q not in c.slug:
            continue
        if state and code != state:
            continue
        rows.append({"church": c, "state": code, "state_label": label, "limits": services.limits(c)})
    today = timezone.localdate()
    paying = [c for c in churches if c.state[0] == Church.ACTIVE]
    stats = {
        "total": len(churches),
        "active": len(paying),
        "trial": sum(1 for c in churches if c.state[0] == Church.TRIAL),
        "overdue": sum(1 for c in churches if c.state[0] == "overdue"),
        "suspended": sum(1 for c in churches if not c.is_accessible),
        "mrr": sum((c.monthly_value for c in paying), Decimal("0")),
        "collected": Payment.objects.filter(paid_on__gte=today.replace(day=1)).aggregate(t=Sum("amount"))["t"] or Decimal("0"),
        "members": sum((c.usage or {}).get("members", 0) for c in churches),
    }
    by_plan = [(p, sum(1 for c in churches if c.plan_id == p.pk)) for p in Plan.objects.all()]
    return render(request, "tenants/dashboard.html", {
        "rows": rows, "stats": stats, "by_plan": by_plan, "q": q, "state": state,
        "states": [("active", "Active"), ("trial", "Free trial"), ("overdue", "Overdue"), ("suspended", "Suspended"), ("cancelled", "Cancelled")],
        "email_configured": settings.EMAIL_CONFIGURED,
    })


@platform_admin_required
def church_create(request):
    form = ChurchCreateForm(request.POST or None, initial={"plan": Plan.objects.filter(code="harvest").first(),
                                                           "is_default": not Church.objects.filter(is_default=True).exists()})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            church, user, password = services.create_church(
                name=d["name"], slug=d["slug"], plan=d["plan"], billing_cycle=d["billing_cycle"], country=d["country"],
                trial_days=d["trial_days"], admin_username=d["admin_username"], admin_email=d["admin_email"],
                admin_password=d["admin_password"] or None, contact_name=d["contact_name"], contact_email=d["contact_email"],
                contact_phone=d["contact_phone"], notes=d["notes"], created_by=request.user, is_default=d["is_default"],
            )
        except services.PlatformError as e:
            form.add_error(None, str(e))
        else:
            if d["trial_days"] == 0:
                Church.objects.filter(pk=church.pk).update(trial_ends=timezone.localdate())
            return render(request, "tenants/church_created.html", {
                "church": church, "username": user.username, "password": password, "email": user.email,
                "addresses": app_addresses(request, church),
            })
    return render(request, "tenants/church_form.html", {"form": form, "plans": Plan.objects.filter(is_active=True)})


@platform_admin_required
def church_detail(request, pk):
    church = get_object_or_404(Church.objects.select_related("plan"), pk=pk)
    if request.GET.get("refresh") or services.usage_is_stale(church, minutes=10):
        services.collect_usage(church)
    return render(request, "tenants/church_detail.html", {
        "church": church, "state": church.state, "limits": services.limits(church),
        "addresses": app_addresses(request, church), "logins": services.church_logins(church),
        "add_login_form": AddLoginForm(), "roles": AddLoginForm().fields["role"].choices,
        "support_sessions": church.support_sessions.select_related("platform_user")[:8],
        "payments": church.payments.select_related("recorded_by")[:24], "payment_form": PaymentForm(church=church),
        "domain_form": DomainForm(), "usage": church.usage or {},
    })


@platform_admin_required
def church_edit(request, pk):
    church = get_object_or_404(Church, pk=pk)
    form = ChurchEditForm(request.POST or None, instance=church)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{church.name} was updated.")
        return redirect("platform:church_detail", pk=pk)
    return render(request, "tenants/church_edit.html", {"form": form, "church": church})


@require_POST
@platform_admin_required
def payment_add(request, pk):
    church = get_object_or_404(Church, pk=pk)
    form = PaymentForm(request.POST, church=church)
    if form.is_valid():
        d = form.cleaned_data
        payment = services.record_payment(church, amount=d["amount"], months=d["months"], method=d["method"], reference=d["reference"],
                                          paid_on=d["paid_on"], notes=d["notes"], user=request.user)
        messages.success(request, f"Payment recorded. {church.name} is paid up to {payment.covers_to:%d %b %Y}.")
    else:
        messages.error(request, "The payment wasn't recorded: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("platform:church_detail", pk=pk)


@require_POST
@platform_admin_required
def church_status(request, pk):
    church = get_object_or_404(Church, pk=pk)
    action = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()[:255]
    if action == "suspend":
        church.status, church.suspended_reason = Church.SUSPENDED, reason or "Suspended by the platform"
        messages.warning(request, f"{church.name} is suspended. Its people see a 'paused' page until you reactivate it.")
    elif action == "cancel":
        church.status, church.suspended_reason = Church.CANCELLED, reason or "Cancelled"
        messages.warning(request, f"{church.name} is cancelled. Its records are kept and it can be reactivated.")
    elif action == "reactivate":
        church.status = Church.ACTIVE if church.paid_until else Church.TRIAL
        church.suspended_reason = ""
        messages.success(request, f"{church.name} is open again.")
    church.save(update_fields=["status", "suspended_reason"])
    return redirect("platform:church_detail", pk=pk)


@require_POST
@platform_admin_required
def church_reset_admin(request, pk):
    church = get_object_or_404(Church, pk=pk)
    try:
        username, password = services.reset_admin_password(church, int(request.POST.get("user", 0)))
    except (User.DoesNotExist, ValueError):
        messages.error(request, "That login wasn't found.")
        return redirect("platform:church_detail", pk=pk)
    return render(request, "tenants/password_issued.html", {
        "church": church, "username": username, "password": password, "addresses": app_addresses(request, church),
    })


@require_POST
@platform_admin_required
def church_domain(request, pk):
    church = get_object_or_404(Church.objects.select_related("plan"), pk=pk)
    if request.POST.get("remove"):
        Domain.objects.filter(tenant=church, pk=request.POST["remove"]).delete()
        messages.success(request, "Web address removed.")
        return redirect("platform:church_detail", pk=pk)
    if not church.plan.custom_domains:
        messages.error(request, f"Own web addresses are part of the Kingdom plan. {church.name} is on {church.plan.name}.")
        return redirect("platform:church_detail", pk=pk)
    form = DomainForm(request.POST)
    if form.is_valid():
        if Domain.objects.filter(domain=form.cleaned_data["domain"]).exists():
            messages.error(request, "That web address is already in use.")
        else:
            Domain.objects.create(tenant=church, domain=form.cleaned_data["domain"], is_primary=not church.domains.exists())
            messages.success(request, "Web address added. Also add it to ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS on the server.")
    else:
        messages.error(request, "Enter a web address such as members.yourchurch.org.")
    return redirect("platform:church_detail", pk=pk)


# ------------------------------------------------- acting in a church

@require_POST
@platform_admin_required
def church_enter(request, pk):
    """Open the church's admin app as an administrator (logged in the church's audit trail)."""
    church = get_object_or_404(Church, pk=pk)
    try:
        token = services.start_support_session(church, request.user, request.POST.get("reason", "").strip(), client_ip(request))
    except services.PlatformError as e:
        messages.error(request, str(e))
        return redirect("platform:church_detail", pk=pk)
    return redirect(f"/{settings.CHURCH_URL_PREFIX}/{church.slug}/accounts/support/{token}/")


@require_POST
@platform_admin_required
def church_login_action(request, pk):
    """Manage any church's logins: add, new temporary password, activate/deactivate, change role."""
    church = get_object_or_404(Church.objects.select_related("plan"), pk=pk)
    action = request.POST.get("action")
    back = request.POST.get("next") or reverse("platform:church_detail", args=[pk])
    back = back if back.startswith("/platform/") else reverse("platform:church_detail", args=[pk])
    try:
        if action == "add":
            form = AddLoginForm(request.POST)
            if not form.is_valid():
                messages.error(request, "The login wasn't added: " + "; ".join(e for errs in form.errors.values() for e in errs))
                return redirect(back)
            d = form.cleaned_data
            user, password = services.add_church_login(church, d["username"], d["email"], d["role"], d["first_name"], d["last_name"])
            return render(request, "tenants/password_issued.html", {
                "church": church, "username": user.username, "password": password, "addresses": app_addresses(request, church),
                "added": True,
            })
        user_id = int(request.POST.get("user", 0))
        if action == "reset":
            username, password = services.reset_login_password(church, user_id)
            return render(request, "tenants/password_issued.html", {
                "church": church, "username": username, "password": password, "addresses": app_addresses(request, church),
            })
        if action in ("activate", "deactivate"):
            username = services.set_login_active(church, user_id, action == "activate")
            messages.success(request, f"{username} {'can sign in again' if action == 'activate' else 'can no longer sign in'}.")
        elif action == "role":
            username = services.set_login_role(church, user_id, request.POST.get("role", ""))
            messages.success(request, f"{username} is now {request.POST.get('role')}.")
    except services.PlatformError as e:
        messages.error(request, str(e))
    except (User.DoesNotExist, ValueError):
        messages.error(request, "That login wasn't found.")
    except Exception as e:  # noqa: BLE001 — e.g. an unknown role name
        messages.error(request, f"That didn't work: {e}")
    return redirect(back)


@platform_admin_required
def people(request):
    q = request.GET.get("q", "").strip()
    return render(request, "tenants/people.html", {"q": q, "results": services.find_people(q) if q else None})


@platform_admin_required
def announcements(request):
    form = AnnouncementForm(request.POST or None)
    form.fields["churches"].queryset = Church.objects.order_by("name")
    if request.method == "POST" and request.POST.get("toggle"):
        a = get_object_or_404(Announcement, pk=request.POST["toggle"])
        a.is_active = not a.is_active
        a.save(update_fields=["is_active"])
        messages.success(request, "Announcement " + ("switched on." if a.is_active else "switched off."))
        return redirect("platform:announcements")
    if request.method == "POST" and form.is_valid():
        a = form.save(commit=False)
        a.created_by = request.user
        a.save()
        form.save_m2m()
        messages.success(request, "Announcement posted. Churches see it within a minute.")
        return redirect("platform:announcements")
    return render(request, "tenants/announcements.html", {"form": form, "items": Announcement.objects.prefetch_related("churches")[:50]})


@platform_admin_required
def support_log(request):
    return render(request, "tenants/support_log.html", {
        "sessions": SupportSession.objects.select_related("church", "platform_user")[:200],
    })


# ------------------------------------------------------- money and plans

@platform_admin_required
def payments(request):
    qs = Payment.objects.select_related("church", "recorded_by")
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="ecclesia-payments.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Church", "Amount", "Method", "Reference", "Months", "Covers from", "Covers to", "Recorded by"])
        for p in qs:
            writer.writerow([p.paid_on, p.church.name, p.amount, p.get_method_display(), p.reference, p.months, p.covers_from,
                             p.covers_to, p.recorded_by.username if p.recorded_by else ""])
        return response
    months = {}
    for p in qs:
        key = p.paid_on.replace(day=1)
        months[key] = months.get(key, Decimal("0")) + p.amount
    return render(request, "tenants/payments.html", {"payments": qs[:200], "months": sorted(months.items(), reverse=True)[:12]})


@platform_admin_required
def plans(request):
    formset = PlanFormSet(request.POST or None, queryset=Plan.objects.all())
    if request.method == "POST" and formset.is_valid():
        formset.save()
        messages.success(request, "Plans saved. New prices apply from each church's next payment.")
        return redirect("platform:plans")
    return render(request, "tenants/plans.html", {"formset": formset})


@platform_admin_required
def team(request):
    form = TeamMemberForm(request.POST or None)
    issued = None
    if request.method == "POST" and request.POST.get("deactivate"):
        user = get_object_or_404(User, pk=request.POST["deactivate"], is_superuser=True)
        if user == request.user:
            messages.error(request, "You can't deactivate your own login.")
        elif User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
            messages.error(request, "Keep at least one active super admin.")
        else:
            user.is_active = False
            user.save(update_fields=["is_active"])
            messages.success(request, f"{user.username} can no longer sign in.")
        return redirect("platform:team")
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        password = services.temporary_password()
        user = User.objects.create_superuser(d["username"], d["email"], password, first_name=d["first_name"], last_name=d["last_name"])
        PlatformProfile.objects.create(user=user, must_change_password=True)
        issued = {"username": user.username, "password": password}
        form = TeamMemberForm()
    return render(request, "tenants/team.html", {
        "form": form, "issued": issued, "members": User.objects.filter(is_superuser=True).order_by("username"),
    })


# ------------------------------------------------------- public pages

@login_not_required
def find_church(request):
    slug = request.GET.get("church", "").strip().lower()
    church = Church.objects.filter(slug=slug).first() if slug else None
    if church:
        return redirect(f"/{settings.CHURCH_URL_PREFIX}/{church.slug}/")
    return render(request, "tenants/find_church.html", {
        "slug": slug, "not_found": bool(slug), "members_app": settings.APP_NAME.endswith("Connect"),
    })
