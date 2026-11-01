from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from core.utils import today

from .models import Group, GroupMembership


class MembershipError(Exception):
    """A rule violation to show the user."""


@transaction.atomic
def induct(member, group, user=None, role=GroupMembership.MEMBER, on=None, note=""):
    """Add (or re-add) a member to a group after checking gender and age eligibility."""
    if not group.is_active:
        raise MembershipError(f"{group.name} is not active.")
    allowed, reason = group.eligibility(member)
    if not allowed:
        raise MembershipError(reason)
    membership, created = GroupMembership.objects.get_or_create(group=group, member=member, defaults={"role": role})
    if not created and membership.status == GroupMembership.ACTIVE:
        raise MembershipError(f"{member.full_name} is already in {group.name}.")
    membership.status = GroupMembership.ACTIVE
    membership.role = role
    membership.inducted_on = on or today()
    membership.inducted_by = user
    membership.left_on = None
    if note:
        membership.note = note
    membership.save()
    return membership


def induct_many(members, group, user=None, role=GroupMembership.MEMBER, on=None):
    """Induct several members; returns (added, [(member, reason)] skipped)."""
    added, skipped = [], []
    for member in members:
        try:
            added.append(induct(member, group, user, role, on))
        except MembershipError as e:
            skipped.append((member, str(e)))
    return added, skipped


@transaction.atomic
def request_to_join(member, group):
    """A member asks to join from the members app; an office user or leader approves it later."""
    if not group.is_active or not group.open_to_requests:
        raise MembershipError(f"{group.name} isn't taking requests. Please speak to the leaders or the church office.")
    allowed, reason = group.eligibility(member)
    if not allowed:
        raise MembershipError(reason)
    membership = GroupMembership.objects.filter(group=group, member=member).first()
    if membership and membership.status == GroupMembership.ACTIVE:
        raise MembershipError(f"You are already a member of {group.name}.")
    if membership and membership.status == GroupMembership.PENDING:
        raise MembershipError("Your request is already waiting for approval.")
    if membership is None:
        membership = GroupMembership(group=group, member=member)
    membership.status = GroupMembership.PENDING
    membership.role = GroupMembership.MEMBER
    membership.requested_at = timezone.now()
    membership.save()
    return membership


@transaction.atomic
def decline_request(membership, user=None, note=""):
    if membership.status != GroupMembership.PENDING:
        raise MembershipError("This request has already been handled.")
    membership.status = GroupMembership.DECLINED
    membership.inducted_by = user
    membership.note = note[:255]
    membership.save()
    return membership


@transaction.atomic
def remove(membership, on=None):
    if membership.status != GroupMembership.ACTIVE:
        raise MembershipError("This person isn't an active member of the group.")
    membership.status = GroupMembership.LEFT
    membership.left_on = on or today()
    membership.save()
    return membership


@transaction.atomic
def set_portal_account(member, username, password):
    """Create or update the member's login for the members app (no staff roles)."""
    username = username.strip()
    if not username:
        raise MembershipError("Choose a username.")
    user = member.user
    if User.objects.filter(username__iexact=username).exclude(pk=getattr(user, "pk", None)).exists():
        raise MembershipError(f"The username “{username}” is taken.")
    if user is None:
        user = User(username=username)
    user.username = username
    user.first_name, user.last_name = member.first_name, member.last_name
    user.email = member.email
    user.is_active = True
    user.set_password(password)
    user.save()
    member.user = user
    member.save(update_fields=["user"])
    return user


def membership_stats(members=None):
    """Counts by status, gender and age group — the gender-sensitive overview."""
    from .models import Member

    members = list(members if members is not None else Member.objects.all())
    current = [m for m in members if m.is_current]
    genders = [g for g, _ in Member.GENDER_CHOICES]
    by_gender = {g: sum(1 for m in current if m.gender == g) for g in genders}
    age_rows = []
    for key, label, *_ in Member.AGE_GROUPS + [(None, "Age not recorded", 0, 0)]:
        row = {g: sum(1 for m in current if m.age_group == key and m.gender == g) for g in genders}
        row.update({"key": key, "label": label, "total": sum(row[g] for g in genders)})
        age_rows.append(row)
    by_status = {s: sum(1 for m in members if m.status == s) for s, _ in Member.STATUS_CHOICES}
    return {
        "total": len(current),
        "by_gender": by_gender,
        "by_gender_pct": {g: (round(by_gender[g] * 100 / len(current)) if current else 0) for g in genders},
        "age_rows": [r for r in age_rows if r["total"] or r["key"]],
        "by_status": by_status,
        "baptized": sum(1 for m in current if m.baptized),
        "with_portal": sum(1 for m in current if m.user_id),
        "groups": Group.with_counts().filter(is_active=True).order_by("group_type", "name"),
    }


# --------------------------------------------------------- giving records

def _digits(phone):
    """Last nine digits, so 0712 345 678 and +254 712 345 678 match."""
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 else ""


def donor_match(member, donor):
    """Why this donor looks like this member ("email", "phone", "name"), or None."""
    if member.email and donor.email and member.email.strip().lower() == donor.email.strip().lower():
        return "email"
    if _digits(member.phone) and _digits(member.phone) == _digits(donor.phone):
        return "phone"
    if (member.first_name.strip().lower(), member.last_name.strip().lower()) == (
        donor.first_name.strip().lower(), donor.last_name.strip().lower()
    ):
        return "name"
    return None


MATCH_RANK = {"email": 0, "phone": 1, "name": 2}


def unlinked_donors():
    from giving.models import Donor

    return Donor.objects.filter(is_active=True, member__isnull=True)


def suggest_donors(member, donors=None):
    """[(donor, reason)] of unlinked giving records that look like this member, best first."""
    donors = list(unlinked_donors()) if donors is None else donors
    found = [(d, r) for d in donors if (r := donor_match(member, d))]
    return sorted(found, key=lambda dr: (MATCH_RANK[dr[1]], dr[0].sort_name))


@transaction.atomic
def link_donor(member, donor):
    from giving.models import Donor

    donor = Donor.objects.select_for_update().get(pk=donor.pk)
    other = type(member).objects.filter(donor=donor).exclude(pk=member.pk).first()
    if other:
        raise MembershipError(f"That giving record already belongs to {other.full_name}.")
    member.donor = donor
    member.save(update_fields=["donor", "updated_at"])
    if not donor.is_member:
        donor.is_member = True
        donor.member_since = donor.member_since or member.date_joined
        donor.save(update_fields=["is_member", "member_since"])
    return donor


@transaction.atomic
def create_donor_for(member):
    """Start a giving record from the member's details and link it."""
    from giving.models import Donor

    if member.donor_id:
        raise MembershipError(f"{member.full_name} already has a giving record.")
    donor = Donor.objects.create(
        donor_type=Donor.INDIVIDUAL, first_name=member.first_name, last_name=member.last_name,
        email=member.email, phone=member.phone,
        address_line1=member.postal_address or member.residence, city=member.town, state=member.county,
        country=member.country, is_member=True, member_since=member.date_joined,
    )
    member.donor = donor
    member.save(update_fields=["donor", "updated_at"])
    return donor
