"""Request identity and durable ownership. No implicit access to legacy/unowned resources.

Authentication is applied by the modeling API; worker context is copied explicitly.
Disabled authentication is a local-demo mode, never a production security boundary.
"""
from contextvars import ContextVar

principal = ContextVar("mooring_principal", default="local-demo")
enforced = ContextVar("mooring_access_enforced", default=False)


def claim(kind, key):
    from .store import db
    d = db()
    with d.lock:
        d.execute("INSERT OR IGNORE INTO ownership VALUES (?,?,?)", (kind,key,principal.get()))
        rows = d.execute("SELECT principal FROM ownership WHERE kind=? AND key=?", (kind,key))
        if rows[0][0] != principal.get() and enforced.get():
            raise PermissionError("resource belongs to another principal")


def allowed(kind, key):
    if not enforced.get(): return True
    from .store import db
    rows = db().execute("SELECT principal FROM ownership WHERE kind=? AND key=?",(kind,key))
    return bool(rows and rows[0][0] == principal.get())
