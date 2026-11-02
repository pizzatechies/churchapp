"""Helpers for management commands that work inside one church."""

from django.core.management.base import CommandError
from django.db import connection


def add_church_argument(parser):
    parser.add_argument("--church", help="The church's web address name (slug). Default: the church served at the main addresses.")


def use_church(slug=None):
    """Switch the database to a church's schema and return the Church."""
    from .models import Church

    connection.set_schema_to_public()
    church = Church.objects.filter(slug=slug).first() if slug else Church.objects.filter(is_default=True).first()
    if church is None:
        church = Church.objects.first() if not slug and Church.objects.count() == 1 else None
    if church is None:
        raise CommandError(f"No church called {slug!r}." if slug else
                           "Which church? Pass --church <web address name>, or mark one as served at the main addresses.")
    connection.set_tenant(church)
    return church
