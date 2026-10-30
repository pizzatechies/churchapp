"""
Automatic audit trail.

Every create, change and delete of a financially significant record is written
to AuditLog together with the user who made it and the fields that changed.
"""

from datetime import date, datetime
from decimal import Decimal

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .middleware import audit_enabled, get_current_user

AUDITED_MODELS = {
    "core.churchprofile",
    "auth.user",
    "ledger.account",
    "ledger.fund",
    "ledger.journalentry",
    "ledger.reconciliation",
    "ledger.budget",
    "giving.donor",
    "giving.contributionbatch",
    "giving.contribution",
    "giving.campaign",
    "giving.pledge",
    "expenses.vendor",
    "expenses.expense",
    "expenses.expensepayment",
    "payroll.employee",
    "payroll.payrollitem",
    "payroll.payrollrun",
    "payroll.paycheck",
    "fixedassets.fixedasset",
    "fixedassets.depreciationrun",
}

IGNORED_FIELDS = {"password", "last_login", "updated_at", "created_at"}


def _label(instance):
    return instance._meta.label_lower


def _serialize(value):
    if isinstance(value, (Decimal,)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _snapshot(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in IGNORED_FIELDS:
            continue
        data[field.name] = _serialize(getattr(instance, field.attname))
    return data


def _write(action, instance, changes):
    from .models import AuditLog

    AuditLog.objects.create(
        user=get_current_user(),
        action=action,
        model=instance._meta.verbose_name.title(),
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
        changes=changes,
    )


@receiver(pre_save)
def _remember_previous_state(sender, instance, raw=False, **kwargs):
    if raw or not audit_enabled() or _label(instance) not in AUDITED_MODELS or not instance.pk:
        return
    previous = sender._default_manager.filter(pk=instance.pk).first()
    instance._audit_previous = _snapshot(previous) if previous else None


@receiver(post_save)
def _log_save(sender, instance, created, raw=False, **kwargs):
    if raw or not audit_enabled() or _label(instance) not in AUDITED_MODELS:
        return
    current = _snapshot(instance)
    if created:
        _write("create", instance, {k: [None, v] for k, v in current.items() if v not in (None, "")})
        return
    previous = getattr(instance, "_audit_previous", None) or {}
    changes = {k: [previous.get(k), v] for k, v in current.items() if previous.get(k) != v}
    if changes:
        _write("update", instance, changes)


@receiver(post_delete)
def _log_delete(sender, instance, **kwargs):
    if not audit_enabled() or _label(instance) not in AUDITED_MODELS:
        return
    _write("delete", instance, {k: [v, None] for k, v in _snapshot(instance).items() if v not in (None, "")})
