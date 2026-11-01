"""
Ecclesia Connect — the members app.

Members see fellowships, church groups and sermons, and manage their own
contact details. When the church switches it on in Church settings, they also
see their own giving and a summary of the church's finances (see finances.py).
No other financial screens exist here: no donor lists, payroll or data entry.
"""

from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from core.media import ranged_file_response
from core.models import ChurchProfile
from core.utils import today
from giving.views import statement_data
from members import services
from members.models import Group, GroupMembership, Sermon
from members.services import MembershipError

from . import finances
from .forms import PortalAuthenticationForm, ProfileForm


def member_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        member = getattr(request.user, "member_profile", None)
        if member is None or not member.is_current:
            logout(request)
            messages.error(request, "Your login isn't linked to a current member record. Please contact the church office.")
            return redirect("login")
        request.member = member
        return view(request, *args, **kwargs)

    return wrapper


class LoginView(auth_views.LoginView):
    template_name = "portal/login.html"
    authentication_form = PortalAuthenticationForm
    redirect_authenticated_user = True
    next_page = reverse_lazy("portal:home")


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "portal/password.html"
    success_url = reverse_lazy("portal:profile")

    def form_valid(self, form):
        messages.success(self.request, "Your password was changed.")
        return super().form_valid(form)


def _membership_map(member):
    return {gm.group_id: gm for gm in member.group_memberships.all()}


def _decorate(groups, member):
    memberships = _membership_map(member)
    for g in groups:
        gm = memberships.get(g.pk)
        g.my_status = gm.status if gm else None
        g.my_role = gm.get_role_display() if gm and gm.status == GroupMembership.ACTIVE else ""
        g.can_join, g.join_reason = g.eligibility(member)
        if g.can_join and not g.open_to_requests:
            g.can_join, g.join_reason = False, "Speak to the leaders or the church office to join."
    return groups


@member_required
def home(request):
    member = request.member
    my_groups = member.active_memberships().order_by("group__name")
    pending = member.group_memberships.filter(status=GroupMembership.PENDING).select_related("group")
    joined_ids = member.group_memberships.filter(status__in=[GroupMembership.ACTIVE, GroupMembership.PENDING]).values("group")
    suggestions = [g for g in _decorate(list(Group.with_counts().filter(is_active=True, open_to_requests=True).exclude(pk__in=joined_ids)), member) if g.can_join][:4]
    return render(request, "portal/home.html", {
        "member": member, "my_groups": my_groups, "pending": pending, "suggestions": suggestions,
        "sermons": Sermon.objects.filter(is_published=True)[:3],
    })


@member_required
def groups(request):
    kind = request.GET.get("type", "")
    qs = Group.with_counts().filter(is_active=True).order_by("group_type", "name")
    if kind:
        qs = qs.filter(group_type=kind)
    items = _decorate(list(qs), request.member)
    by_type = {}
    for g in items:
        by_type.setdefault(g.get_group_type_display(), []).append(g)
    return render(request, "portal/groups.html", {"by_type": by_type, "types": Group.TYPE_CHOICES, "kind": kind})


@member_required
def group_detail(request, pk):
    group = get_object_or_404(Group.with_counts(), pk=pk, is_active=True)
    _decorate([group], request.member)
    is_member = group.my_status == GroupMembership.ACTIVE
    return render(request, "portal/group_detail.html", {
        "group": group, "is_member": is_member,
        "leaders": group.leaders(),
        # Fellow members' names are only shown to people in the group.
        "fellow_members": group.active().order_by("member__first_name") if is_member else None,
    })


@require_POST
@member_required
def group_join(request, pk):
    group = get_object_or_404(Group, pk=pk, is_active=True)
    try:
        services.request_to_join(request.member, group)
        messages.success(request, f"Your request to join {group.name} was sent. The church office or a leader will confirm it.")
    except MembershipError as e:
        messages.error(request, str(e))
    return redirect("portal:group_detail", pk=pk)


@require_POST
@member_required
def group_cancel(request, pk):
    gm = GroupMembership.objects.filter(group_id=pk, member=request.member, status=GroupMembership.PENDING).first()
    if gm:
        gm.delete()
        messages.success(request, "Request withdrawn.")
    return redirect("portal:group_detail", pk=pk)


@member_required
def sermons(request):
    qs = Sermon.objects.filter(is_published=True)
    q = request.GET.get("q", "").strip()
    series = request.GET.get("series", "")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(preacher__icontains=q) | Q(scripture__icontains=q) | Q(summary__icontains=q))
    if series:
        qs = qs.filter(series=series)
    all_series = Sermon.objects.filter(is_published=True).exclude(series="").order_by("series").values_list("series", flat=True).distinct()
    return render(request, "portal/sermons.html", {
        "page_obj": Paginator(qs, 12).get_page(request.GET.get("page")), "q": q, "series": series, "all_series": all_series,
    })


@member_required
def sermon_detail(request, pk):
    sermon = get_object_or_404(Sermon, pk=pk, is_published=True)
    more = Sermon.objects.filter(is_published=True).exclude(pk=pk)
    more = (more.filter(series=sermon.series) if sermon.series else more)[:4]
    return render(request, "portal/sermon_detail.html", {"sermon": sermon, "more": more})


@member_required
def sermon_media(request, pk, kind):
    sermon = get_object_or_404(Sermon, pk=pk, is_published=True)
    field = {"audio": sermon.audio_file, "video": sermon.video_file, "notes": sermon.notes_file}.get(kind)
    return ranged_file_response(request, field, as_attachment=kind == "notes")


@member_required
def profile(request):
    member = request.member
    form = ProfileForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        form.save()
        if member.user and member.user.email != member.email:
            member.user.email = member.email
            member.user.save(update_fields=["email"])
        messages.success(request, "Your details were updated.")
        return redirect("portal:profile")
    return render(request, "portal/profile.html", {
        "member": member, "form": form, "memberships": member.active_memberships().order_by("group__name"),
    })


def _year(request):
    try:
        year = int(request.GET.get("year") or today().year)
    except ValueError:
        return today().year
    return year if 2000 <= year <= today().year else today().year


@member_required
def giving(request):
    """My giving: the member's own gifts, pledges and statements, nobody else's."""
    profile = ChurchProfile.get()
    if not profile.members_see_own_giving:
        if profile.members_see_finances:
            return redirect("portal:church_finances")
        raise Http404
    year = _year(request)
    return render(request, "portal/giving.html", {
        "profile": profile, "year": year, "mine": finances.member_giving(request.member, year),
    })


@member_required
def church_finances(request):
    """The church's financial summary, shared for accountability: totals only."""
    profile = ChurchProfile.get()
    if not profile.members_see_finances:
        if profile.members_see_own_giving:
            return redirect("portal:giving")
        raise Http404
    cutoff = finances.cutoff_date(profile)
    return render(request, "portal/church_finances.html", {
        "profile": profile, "summary": finances.church_summary(cutoff, profile) if cutoff else None,
    })


@member_required
def giving_statement(request, year):
    """A printable statement of the member's own gifts for one calendar year."""
    profile = ChurchProfile.get()
    donor = request.member.donor
    if not profile.members_see_own_giving or donor is None or not 2000 <= year <= today().year:
        raise Http404
    start, end = date(year, 1, 1), min(date(year, 12, 31), today())
    data = statement_data(start, end, donor)
    return render(request, "portal/giving_statement.html", {
        "statement": data[0] if data else None, "donor": donor, "year": year, "start": start, "end": end, "generated": today(),
    })


def error_404(request, exception=None):
    return render(request, "portal/error.html", {"title": "Page not found", "message": "That page doesn't exist."}, status=404)


def error_403(request, exception=None):
    return render(request, "portal/error.html", {"title": "Not available", "message": "This page isn't available in the members app."}, status=403)




def switch_church(request):
    """Inside the mobile app: go back to the app's start screen to connect to a different church."""
    return render(request, "portal/switch_church.html")
