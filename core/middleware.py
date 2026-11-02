from contextvars import ContextVar

_current_user = ContextVar("current_user", default=None)
_audit_enabled = ContextVar("audit_enabled", default=True)


def _schema():
    from django.db import connection

    return getattr(connection, "schema_name", "public")


def get_current_user():
    """The signed-in user, but only while working in the schema (church) their login belongs to.

    A platform super admin creating or helping a church has a login in the shared schema, not in
    that church, so their actions there aren't attributed to an unrelated user with the same id.
    """
    value = _current_user.get()
    if value is None:
        return None
    user, schema = value
    if user is not None and getattr(user, "is_authenticated", False) and (schema is None or schema == _schema()):
        return user
    return None


def audit_enabled():
    if not _audit_enabled.get():
        return False
    from django.db import connection

    # The platform's shared schema has no audit table; each church's schema has its own.
    return getattr(connection, "schema_name", "") != "public"


class audit_disabled:
    """Context manager used by bulk loaders (demo data) to skip audit logging."""

    def __enter__(self):
        self._token = _audit_enabled.set(False)

    def __exit__(self, *exc):
        _audit_enabled.reset(self._token)


class acting_as:
    """Attribute audit-log entries to a user outside of a request (management commands)."""

    def __init__(self, user):
        self.user = user

    def __enter__(self):
        self._token = _current_user.set((self.user, None))

    def __exit__(self, *exc):
        _current_user.reset(self._token)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_user.set((getattr(request, "user", None), _schema()))
        try:
            return self.get_response(request)
        finally:
            _current_user.reset(token)
