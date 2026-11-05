"""Optional single-process agent documents in the ownership database.

AGENTS_PERSIST=1 requires a file-backed MOORING_DB. Values are saved on assignment,
never by mutating a retrieved object. Toolkits, transports and credentials are not documents.
One agents process per database is supported; jobs are not distributed.
"""
import os
from collections.abc import MutableMapping
from contextlib import contextmanager
from threading import RLock

from pydantic import TypeAdapter
from mooring.core import access, store


def persistence_enabled() -> bool:
    value = os.environ.get('AGENTS_PERSIST', '0')
    if value not in ('0', '1'):
        raise ValueError('AGENTS_PERSIST must be 0 or 1')
    if value == '1' and os.environ.get('MOORING_DB', ':memory:') in ('', ':memory:'):
        raise ValueError('AGENTS_PERSIST=1 requires a file-backed MOORING_DB')
    return value == '1'


class AgentStore(MutableMapping):
    """Ownership-aware mapping; durable values use an explicit schema/codec."""
    def __init__(self, namespace, model, *, owner_kind=None, encode=None, decode=None):
        self.namespace = namespace
        self.owner_kind = owner_kind or namespace
        self.adapter = TypeAdapter(model)
        self.encode = encode or (lambda value: value)
        self.decode = decode or (lambda value: value)
        self.memory = {}
        self.lock = RLock()

    @contextmanager
    def atomic(self):
        # Shared DB lock also covers distinct mappings (e.g. sheet and plan updates).
        with store.db().lock if persistence_enabled() else self.lock:
            yield

    def __getitem__(self, key):
        if not access.allowed(self.owner_kind, key):
            raise KeyError(key)
        with self.atomic():
            if not persistence_enabled():
                return self.memory[key]
            rows = store.db().execute('SELECT body FROM docs WHERE namespace=? AND key=?', (self.namespace, key))
            if not rows:
                raise KeyError(key)
            return self.decode(self.adapter.validate_json(rows[0][0]))

    def __setitem__(self, key, value):
        with self.atomic():
            access.claim(self.owner_kind, key)
            if not persistence_enabled():
                self.memory[key] = value
                return
            body = self.adapter.dump_json(self.adapter.validate_python(self.encode(value))).decode()
            store.db().execute('INSERT OR REPLACE INTO docs VALUES (?,?,?)', (self.namespace, key, body))

    def __delitem__(self, key):
        with self.atomic():
            self[key]  # ownership and existence
            if not persistence_enabled():
                del self.memory[key]
            else:
                store.db().execute('DELETE FROM docs WHERE namespace=? AND key=?', (self.namespace, key))

    def __iter__(self):
        with self.atomic():
            keys = list(self.memory) if not persistence_enabled() else [r[0] for r in store.db().execute(
                'SELECT key FROM docs WHERE namespace=? ORDER BY rowid', (self.namespace,))]
            return iter([key for key in keys if access.allowed(self.owner_kind, key)])

    def __len__(self):
        return sum(1 for _ in self)
