"""Opt-in single-process API controls. No trusted proxy or remote identity service assumed."""
import hmac
import json
import re
import os
import threading
import time

from mooring.core import access, metrics


class AccessError(Exception):
    def __init__(self, code, message): self.code,self.message=code,message


def identity(headers):
    raw = os.environ.get("MOORING_API_KEYS", "")
    required = os.environ.get("MOORING_AUTH_REQUIRED", "0") == "1"
    if not raw:
        if required: raise AccessError(503,"Authentication is required but not configured")
        return "local-demo",False
    try:
        keys=json.loads(raw)
        if not isinstance(keys,dict) or not keys or any(not isinstance(p,str) or not p or len(p)>128 or
            not isinstance(k,str) or len(k)<32 for p,k in keys.items()) or len(set(keys.values()))!=len(keys):
            raise ValueError()
    except (ValueError,TypeError):
        raise AccessError(503,"Authentication configuration is invalid") from None
    authorization=headers.get("authorization","")
    supplied=authorization[7:] if authorization.startswith("Bearer ") else ""
    found=None
    for p,key in keys.items():
        if hmac.compare_digest(supplied.encode(),key.encode()): found=p
    if found is None: raise AccessError(401,"Valid bearer credentials are required")
    return found,True


class RateLimit:
    def __init__(self, clock=time.monotonic):
        self.clock,self.lock,self.windows=clock,threading.Lock(),{}

    def allow(self, principal, maximum):
        now=self.clock()
        with self.lock:
            start,count=self.windows.get(principal,(now,0))
            if now-start >= 60: start,count=now,0
            self.windows[principal]=(start,count+1)
            return count<maximum,max(1,int(60-(now-start))+1)


RATE = RateLimit()


UPLOAD_PATH=re.compile(r"^/api/v1/missions/[^/]+/(media|track|track/file)$")
FORECAST_PATHS = {
    "/api/v1/mooring/forecast/resolve",
    "/api/v1/mooring/forecast-plan",
    "/api/v1/mooring/forecast-plan/recheck",
}


class Controls:
    """Buffer bounded HTTP bodies before parsing; scope identity through response streaming."""
    def __init__(self, app): self.app=app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            headers={k.decode("latin1"):v.decode("latin1") for k,v in scope.get("headers",[])}
            try: principal,enabled=identity(headers)
            except AccessError as exc:
                return await send({"type":"websocket.close","code":4401,"reason":exc.message})
            token=access.principal.set(principal)
            enforcement=access.enforced.set(enabled)
            try: return await self.app(scope,receive,send)
            finally:
                access.principal.reset(token); access.enforced.reset(enforcement)
        if scope["type"] != "http":
            return await self.app(scope,receive,send)
        headers={k.decode("latin1"):v.decode("latin1") for k,v in scope.get("headers",[])}
        async def reject(code,message,retry=None):
            head=[(b"content-type",b"application/json")]
            if retry: head.append((b"retry-after",str(retry).encode()))
            if code==401: head.append((b"www-authenticate",b"Bearer"))
            await send({"type":"http.response.start","status":code,"headers":head})
            await send({"type":"http.response.body","body":json.dumps({"detail":message}).encode()})
        if scope["path"] in ("/api/v1/health",):
            principal,enabled="health",False
        else:
            try: principal,enabled=identity(headers)
            except AccessError as exc: return await reject(exc.code,exc.message)
        try:
            maximum=int(os.environ.get("MOORING_RATE_PER_MINUTE","600" if enabled else "0"))
            limit=int(os.environ.get("MOORING_MAX_BODY_BYTES","1048576"))
            if scope.get("method") == "POST" and scope["path"] in FORECAST_PATHS:
                # Native six-minute forecasts retain every knot and its provenance.
                # Respect an explicitly configured global cap unless separately overridden.
                limit=int(os.environ.get("MOORING_MAX_FORECAST_BODY_BYTES",
                    os.environ.get("MOORING_MAX_BODY_BYTES", str(4*1024*1024))))
            if scope.get("method")=="POST" and UPLOAD_PATH.match(scope["path"]):
                # S5 uploads (images <= 8 MB, track files <= 20 MB, JSON tracks) get their own, still bounded, limit;
                # the routes enforce their per-item limits after this.
                limit=int(os.environ.get("MOORING_MAX_UPLOAD_BYTES",str(32*1024*1024)))
            if maximum < 0 or limit <= 0: raise ValueError()
        except ValueError:
            return await reject(503,"Request limit configuration is invalid")
        permitted,retry=RATE.allow(principal,maximum) if maximum else (True,0)
        if not permitted:
            metrics.add("rate_limit_rejections")
            return await reject(429,"Per-principal request rate exceeded",retry)
        body=bytearray()
        while True:
            message=await receive()
            if message["type"]=="http.disconnect": return
            body.extend(message.get("body",b""))
            if len(body)>limit:
                metrics.add("body_limit_rejections")
                return await reject(413,"Request body exceeds configured limit")
            if not message.get("more_body",False): break
        delivered=False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {"type":"http.request","body":bytes(body),"more_body":False}
            return await receive()
        token=access.principal.set(principal)
        enforcement=access.enforced.set(enabled)
        try: await self.app(scope,bounded_receive,send)
        finally:
            access.principal.reset(token); access.enforced.reset(enforcement)
