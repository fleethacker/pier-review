"""Opt-in agents identity, bounded HTTP bodies and per-principal request limits.

Unset keys mean local-demo mode. Incoming credentials are forwarded only after
validation, preserving the caller's modeling identity rather than using a shared
service principal. This is not a role/identity-provider or multi-host design.
"""
import hmac
import json
import os
import threading
import time
from contextvars import ContextVar

from mooring.core import access, metrics

credential = ContextVar('agents_modeling_credential', default=None)


def setting(name, default=''):
    return os.environ.get(f'AGENTS_{name}', os.environ.get(f'MOORING_{name}', default))


class AccessError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


def identity(headers):
    raw = setting('API_KEYS')
    if not raw:
        if setting('AUTH_REQUIRED', '0') == '1':
            raise AccessError(503, 'Authentication is required but not configured')
        return 'local-demo', False, None
    try:
        keys = json.loads(raw)
        if (not isinstance(keys, dict) or not keys or
            any(not isinstance(p, str) or not p or len(p) > 128 or not isinstance(k, str) or len(k) < 32
                for p, k in keys.items()) or len(set(keys.values())) != len(keys)):
            raise ValueError()
    except (ValueError, TypeError):
        raise AccessError(503, 'Authentication configuration is invalid') from None
    authorization = headers.get('authorization', '')
    supplied = authorization[7:] if authorization.startswith('Bearer ') else ''
    found = None
    for principal, key in keys.items():
        if hmac.compare_digest(supplied.encode(), key.encode()):
            found = principal
    if found is None:
        raise AccessError(401, 'Valid bearer credentials are required')
    return found, True, authorization


class RateLimit:
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.windows = clock, threading.Lock(), {}

    def allow(self, principal, maximum):
        now = self.clock()
        with self.lock:
            start, count = self.windows.get(principal, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self.windows[principal] = (start, count + 1)
            return count < maximum, max(1, int(60 - (now - start)) + 1)


RATE = RateLimit()


class Controls:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin1'): v.decode('latin1') for k, v in scope.get('headers', [])}

        async def reject(status, detail, retry=None):
            response_headers = [(b'content-type', b'application/json')]
            if retry:
                response_headers.append((b'retry-after', str(retry).encode()))
            if status == 401:
                response_headers.append((b'www-authenticate', b'Bearer'))
            await send({'type': 'http.response.start', 'status': status, 'headers': response_headers})
            await send({'type': 'http.response.body', 'body': json.dumps({'detail': detail}).encode()})

        try:
            principal, enabled, bearer = ('health', False, None) if scope['path'] == '/api/v1/health' else identity(headers)
        except AccessError as exc:
            return await reject(exc.status, exc.detail)
        try:
            maximum = int(os.environ.get('AGENTS_RATE_PER_MINUTE', '600' if enabled else '0'))
            limit = int(os.environ.get('AGENTS_MAX_BODY_BYTES', '9000000'))
            if maximum < 0 or limit <= 0:
                raise ValueError()
        except ValueError:
            return await reject(503, 'Request limit configuration is invalid')
        allowed, retry = RATE.allow(principal, maximum) if maximum else (True, 0)
        if not allowed:
            metrics.add('agents_rate_limit_rejections')
            return await reject(429, 'Per-principal request rate exceeded', retry)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > limit:
                metrics.add('agents_body_limit_rejections')
                return await reject(413, 'Request body exceeds configured limit')
            if not message.get('more_body', False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        who = access.principal.set(principal)
        enforce = access.enforced.set(enabled)
        token = credential.set(bearer)
        try:
            await self.app(scope, bounded_receive, send)
        finally:
            credential.reset(token)
            access.enforced.reset(enforce)
            access.principal.reset(who)
