"""Admin-app screens for the membership register, groups & fellowships, inductions and sermons."""

import csv
import io

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.media import ranged_file_response
from core.permissions import has_cap, require_cap
from core.utils import csv_response, parse_date, today

from . import services
from .forms import (
    BulkInductForm,
    GroupForm,
    InductForm,
    MemberForm,
    MemberImportForm,
    PortalAccountForm,
    SermonForm,
)
from .models import Group, GroupMembership, Member, Sermon
from .services import MembershipError

# ------------------------------------------------------------------- members

def _filtered_members(request):
    members = Member.objects.all()
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "current")
    gender = request.GET.get("gender", "")
    age = request.GET.get("age", "")
    group = request.GET.get("group", "")
    if q:
        members = members.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(middle_name__icontains=q) | Q(phone__icontains=q)
            | Q(email__icontains=q) | Q(member_number__iexact=q) | Q(residence__icontains=q)
        )
    if status == "current":
        members = members.filter(status__in=Member.CURRENT)
    elif status:
        members = members.filter(status=status)
    if gender:
        members = members.filter(gender=gender)
    if age == "unknown":
        members = members.filter(date_of_birth__isnull=True)
    elif age:
        bounds = Member.birth_range_for(age)
        if bounds:
            members = members.filter(date_of_birth__gt=bounds[0], date_of_birth__lte=bounds[1])
    if group:
        members = members.filter(group_memberships__group_id=group, group_memberships__status=GroupMembership.ACTIVE)
    return members, {"q": q, "status": status, "gender": gender, "age": age, "group": group}


@require_cap("view_members")
def member_list(request):
    members, filters = _filtered_members(request)
    members = members.annotate(
        groups_count=Count("group_memberships", filter=Q(group_memberships__status=GroupMembership.ACTIVE)),
    ).order_by("last_name", "first_name", "pk")
    if request.GET.get("export") == "csv":
        return csv_response("members.csv", [
            "Member no.", "Title", "First name", "Middle name", "Last name", "Gender", "Date of birth", "Age group",
            "Marital status", "Phone", "Email", "Residence", "Town", "County", "Status", "Joined", "Baptized", "Groups",
        ], [[m.member_number, m.title, m.first_name, m.middle_name, m.last_name, m.get_gender_display(), m.date_of_birth or "",
             m.age_group_label, m.get_marital_status_display(), m.phone, m.email, m.residence, m.town, m.county,
             m.get_status_display(), m.date_joined or "", "Yes" if m.baptized else "No", m.groups_count] for m in members])
    page = Paginator(members, 50).get_page(request.GET.get("page"))
    return render(request, "members/member_list.html", {
        "page_obj": page, "filters": filters, "count": members.count(),
        "statuses": Member.STATUS_CHOICES, "genders": Member.GENDER_CHOICES, "age_groups": Member.AGE_GROUPS,
        "groups": Group.objects.filter(is_active=True),
    })


@require_cap("view_members")
def member_detail(request, pk):
    member = get_object_or_404(Member.objects.select_related("user", "donor"), pk=pk)
    memberships = member.group_memberships.select_related("group", "inducted_by").order_by("status", "group__name")
    return render(request, "members/member_detail.html", {
        "member": member, "memberships": memberships,
        "induct_form": InductForm(),
        "portal_form": PortalAccountForm(initial={"username": member.user.username if member.user else _suggest_username(member)}),
        "can_manage": has_cap(request.user, "manage_members"),
        "can_see_giving": has_cap(request.user, "view_donors"),
    })


def _suggest_username(member):
    from django.contrib.auth.models import User

    base = f"{member.first_name}.{member.last_name}".lower().replace(" ", "")
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


@require_cap("manage_members")
def member_edit(request, pk=None):
    member = get_object_or_404(Member, pk=pk) if pk else None
    form = MemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        member = form.save()
        if member.user and (member.user.email != member.email or not member.is_current):
            member.user.email = member.email
            member.user.is_active = member.is_current
            member.user.save(update_fields=["email", "is_active"])
        messages.success(request, f"{member} saved.")
        return redirect(member.get_absolute_url())
    return render(request, "members/member_form.html", {"form": form, "member": member})


@require_POST
@require_cap("manage_members")
def member_induct(request, pk):
    member = get_object_or_404(Member, pk=pk)
    form = InductForm(request.POST)
    if form.is_valid():
        try:
            services.induct(member, form.cleaned_data["group"], request.user, form.cleaned_data["role"], form.cleaned_data["inducted_on"])
            messages.success(request, f"{member.first_name} was inducted into {form.cleaned_data['group']}.")
        except MembershipError as e:
            messages.error(request, str(e))
    return redirect(member.get_absolute_url())


@require_POST
@require_cap("manage_members")
def member_portal(request, pk):
    member = get_object_or_404(Member.objects.select_related("user"), pk=pk)
    if request.POST.get("action") == "disable" and member.user:
        member.user.is_active = False
        member.user.save(update_fields=["is_active"])
        messages.success(request, "Members app access disabled.")
        return redirect(member.get_absolute_url())
    form = PortalAccountForm(request.POST)
    if form.is_valid():
        if member.user and (member.user.is_superuser or member.user.groups.exists()):
            messages.error(request, "This login also has staff roles; change its password under Users & roles.")
            return redirect(member.get_absolute_url())
        try:
            services.set_portal_account(member, form.cleaned_data["username"], form.cleaned_data["password"])
            messages.success(request, f"{member.first_name} can now sign in to the members app as “{form.cleaned_data['username']}”.")
        except MembershipError as e:
            messages.error(request, str(e))
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(member.get_absolute_url())


MEMBER_IMPORT_COLUMNS = {
    "first_name": ["first name", "first_name", "firstname", "first"],
    "middle_name": ["middle name", "middle_name", "other names"],
    "last_name": ["last name", "last_name", "surname", "lastname"],
    "gender": ["gender", "sex"],
    "date_of_birth": ["date of birth", "dob", "birth date", "date_of_birth"],
    "phone": ["phone", "mobile", "telephone", "phone number"],
    "email": ["email", "e-mail"],
    "residence": ["residence", "estate", "area"],
    "town": ["town", "city"],
    "county": ["county", "region", "state"],
    "occupation": ["occupation", "profession"],
}


def _parse_gender(value):
    v = (value or "").strip().lower()
    if v in ("f", "female", "woman", "w"):
        return Member.FEMALE
    if v in ("m", "male", "man"):
        return Member.MALE
    return Member.UNSPECIFIED


@require_cap("manage_members")
def member_import(request):
    form = MemberImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        raw = form.cleaned_data["file"].read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))
        headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        mapping = {field: headers[a] for field, aliases in MEMBER_IMPORT_COLUMNS.items() for a in aliases if a in headers}
        if not {"first_name", "last_name"} <= set(mapping):
            form.add_error("file", "The file needs 'First name' and 'Last name' columns.")
        else:
            created = skipped = 0
            errors = []
            for n, row in enumerate(reader, start=2):
                values = {f: (row.get(col) or "").strip() for f, col in mapping.items()}
                if not values.get("first_name") or not values.get("last_name"):
                    continue
                dup = Member.objects.filter(first_name__iexact=values["first_name"], last_name__iexact=values["last_name"])
                if values.get("phone"):
                    dup = dup.filter(phone=values["phone"])
                if dup.exists():
                    skipped += 1
                    continue
                values["gender"] = _parse_gender(values.get("gender"))
                dob = values.pop("date_of_birth", "")
                try:
                    with transaction.atomic():
                        Member.objects.create(date_of_birth=parse_date(dob), **values)
                    created += 1
                except Exception as e:  # noqa: BLE001 — report the row and carry on
                    errors.append(f"Row {n}: {e}")
            result = {"created": created, "skipped": skipped, "errors": errors[:20]}
            messages.success(request, f"Imported {created} member(s); skipped {skipped} already on the register.")
    return render(request, "members/member_import.html", {"form": form, "result": result, "columns": MEMBER_IMPORT_COLUMNS})


@require_cap("view_members")
def membership_summary(request):
    stats = services.membership_stats()
    if request.GET.get("export") == "csv":
        rows = [["Gender", g, stats["by_gender"][code]] for code, g in Member.GENDER_CHOICES]
        rows += [["Age group", r["label"], r["total"]] for r in stats["age_rows"]]
        rows += [["Group", grp.name, grp.total] for grp in stats["groups"]]
        return csv_response("membership-summary.csv", ["Category", "Item", "Count"], rows)
    recent = GroupMembership.objects.filter(status=GroupMembership.ACTIVE, inducted_on__isnull=False).select_related("member", "group").order_by("-inducted_on", "-id")[:10]
    return render(request, "members/summary.html", {"stats": stats, "genders": Member.GENDER_CHOICES, "recent": recent})


# -------------------------------------------------------------------- groups

@require_cap("view_members")
def group_list(request):
    groups = Group.with_counts().order_by("group_type", "name")
    show = request.GET.get("show", "active")
    if show == "active":
        groups = groups.filter(is_active=True)
    leaders = {}
    for gm in GroupMembership.objects.filter(status=GroupMembership.ACTIVE).exclude(role=GroupMembership.MEMBER).select_related("member"):
        leaders.setdefault(gm.group_id, []).append(gm)
    by_type = {}
    for g in groups:
        g.leader_list = leaders.get(g.pk, [])
        by_type.setdefault(g.get_group_type_display(), []).append(g)
    return render(request, "members/group_list.html", {
        "by_type": by_type, "show": show,
        "pending_total": GroupMembership.objects.filter(status=GroupMembership.PENDING).count(),
    })


@require_cap("view_members")
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk)
    can_manage = has_cap(request.user, "manage_members")
    form = BulkInductForm(request.POST or None, group=group) if can_manage else None
    if request.method == "POST" and can_manage and form.is_valid():
        added, skipped = services.induct_many(form.cleaned_data["members"], group, request.user,
                                              form.cleaned_data["role"], form.cleaned_data["inducted_on"])
        if added:
            messages.success(request, f"Inducted {len(added)} member{'s' if len(added) != 1 else ''} into {group.name}.")
        for member, reason in skipped:
            messages.warning(request, f"{member}: {reason}")
        return redirect(group.get_absolute_url())
    memberships = group.memberships.select_related("member", "inducted_by")
    return render(request, "members/group_detail.html", {
        "group": group, "form": form, "can_manage": can_manage,
        "active": memberships.filter(status=GroupMembership.ACTIVE).order_by(GroupMembership.role_order(), "member__last_name"),
        "pending": memberships.filter(status=GroupMembership.PENDING).order_by("requested_at"),
        "past": memberships.filter(status=GroupMembership.LEFT).order_by("-left_on")[:20],
        "counts": group.gender_counts(), "roles": GroupMembership.ROLE_CHOICES,
    })


@require_POST
@require_cap("manage_members")
def membership_action(request, pk):
    membership = get_object_or_404(GroupMembership.objects.select_related("group", "member"), pk=pk)
    action = request.POST.get("action")
    try:
        if action == "approve":
            services.induct(membership.member, membership.group, request.user, GroupMembership.MEMBER)
            messages.success(request, f"{membership.member} was inducted into {membership.group}.")
        elif action == "decline":
            services.decline_request(membership, request.user, request.POST.get("note", ""))
            messages.success(request, "Request declined.")
        elif action == "remove":
            services.remove(membership)
            messages.success(request, f"{membership.member} removed from {membership.group}.")
        elif action == "role":
            role = request.POST.get("role")
            if role in dict(GroupMembership.ROLE_CHOICES):
                membership.role = role
                membership.save(update_fields=["role"])
                messages.success(request, f"{membership.member} is now {membership.get_role_display().lower()}.")
    except MembershipError as e:
        messages.error(request, str(e))
    return redirect(request.POST.get("next") or membership.group.get_absolute_url())


@require_cap("manage_members")
def group_edit(request, pk=None):
    group = get_object_or_404(Group, pk=pk) if pk else None
    form = GroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        group = form.save()
        messages.success(request, f"{group} saved.")
        return redirect(group.get_absolute_url())
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"Edit {group}" if group else "New group or fellowship",
        "subtitle": "Fellowships, ministries, home cells, choirs, classes and committees.",
        "cancel_url": reverse("members:group_list"),
    })


# ------------------------------------------------------------------- sermons

@require_cap("manage_sermons")
def sermon_list(request):
    sermons = Sermon.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        sermons = sermons.filter(Q(title__icontains=q) | Q(preacher__icontains=q) | Q(series__icontains=q) | Q(scripture__icontains=q))
    page = Paginator(sermons, 25).get_page(request.GET.get("page"))
    return render(request, "members/sermon_list.html", {"page_obj": page, "q": q})


@require_cap("manage_sermons")
def sermon_edit(request, pk=None):
    sermon = get_object_or_404(Sermon, pk=pk) if pk else None
    form = SermonForm(request.POST or None, request.FILES or None, instance=sermon)
    if request.method == "POST":
        if "delete" in request.POST and sermon:
            for f in (sermon.audio_file, sermon.video_file, sermon.notes_file):
                if f:
                    f.delete(save=False)
            sermon.delete()
            messages.success(request, "Sermon deleted.")
            return redirect("members:sermon_list")
        if form.is_valid():
            sermon = form.save(commit=False)
            if not sermon.created_by_id:
                sermon.created_by = request.user
            sermon.save()
            messages.success(request, "Sermon saved." + (" Members can now see it in the members app." if sermon.is_published else " It is not published yet."))
            return redirect("members:sermon_list")
    return render(request, "members/sermon_form.html", {"form": form, "sermon": sermon})


@require_cap("manage_sermons")
def sermon_media(request, pk, kind):
    sermon = get_object_or_404(Sermon, pk=pk)
    field = {"audio": sermon.audio_file, "video": sermon.video_file, "notes": sermon.notes_file}.get(kind)
    return ranged_file_response(request, field, as_attachment=kind == "notes")


def congregation_snapshot():
    """Small summary for the admin dashboard."""
    stats = services.membership_stats()
    return {
        "stats": stats,
        "pending_requests": GroupMembership.objects.filter(status=GroupMembership.PENDING).select_related("member", "group")[:6],
        "latest_sermons": Sermon.objects.all()[:4],
        "new_inductions": GroupMembership.objects.filter(status=GroupMembership.ACTIVE, inducted_on__gte=today().replace(day=1)).count(),
    }
